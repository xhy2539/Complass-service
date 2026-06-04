import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.kb.fallback import fallback_reverse_rule_cases
from app.models.reverse_rule import (
    CandidateRuleForDB,
    CandidateRuleBatch,
    ContractBaseInfo,
    ContractPair,
    DiffResult,
    FinalRuleResult,
    RetrievedCase,
    RuleExtractionTrace,
)
from app.prompts import RULE_GENERATION_PROMPT
from app.services.base_info import (
    identify_base_info_for_pair,
    identify_base_info_with_heuristics,
    merge_base_info_with_input,
    pair_with_base_info,
)
from app.services.diff_service import diff_contract_pair
from app.services.query_builder import build_retrieval_queries
from app.services.rule_merger import merge_candidate_rules
from app.services.review_perspective import normalize_review_perspective

RuleGenerator = Callable[
    [ContractPair, DiffResult, list[RetrievedCase], ContractBaseInfo | None],
    list[CandidateRuleForDB],
]


class ReverseRuleState(TypedDict, total=False):
    raw_pairs: list[dict[str, Any]]
    pairs: list[ContractPair]
    base_infos: list[ContractBaseInfo]
    diff_results: list[DiffResult]
    pair_rules: list[CandidateRuleForDB]
    rules: list[CandidateRuleForDB]
    result: FinalRuleResult
    rule_generator: RuleGenerator | None


def validate_input(contract_pairs: list[dict[str, Any]]) -> list[ContractPair]:
    if not 1 <= len(contract_pairs) <= 5:
        raise ValueError("contract_pairs 必须包含 1-5 组合同")

    pairs: list[ContractPair] = []
    for index, raw_pair in enumerate(contract_pairs, start=1):
        data = dict(raw_pair)
        data.setdefault("pair_id", f"pair-{index}")
        pairs.append(ContractPair.model_validate(data))
    return pairs


def retrieve_cases_for_diff(
    queries: list[str],
    diff_result: DiffResult,
    contract_type: str | None = None,
    review_role: str | None = None,
    k: int = 3,
) -> list[RetrievedCase]:
    try:
        import app.kb.retriever as retriever

        retrieved: list[RetrievedCase] = []
        substantive_clauses = [clause for clause in diff_result.changed_clauses if clause.is_substantive]
        for index, query in enumerate(queries):
            clause = substantive_clauses[index] if index < len(substantive_clauses) else None
            raw_results = retriever.retrieve_reverse_rule_cases(
                query,
                review_module=clause.review_module if clause else None,
                contract_type=contract_type,
                review_role=review_role,
                k=k,
            )
            retrieved.extend(_parse_retrieved_cases(raw_results))
        return retrieved or fallback_reverse_rule_cases(diff_result, k=k)
    except Exception:
        return fallback_reverse_rule_cases(diff_result, k=k)


def generate_rules_for_pair(
    pair: ContractPair,
    diff_result: DiffResult,
    retrieved_cases: list[RetrievedCase],
    base_info: ContractBaseInfo | None = None,
) -> list[CandidateRuleForDB]:
    if _has_llm_credentials():
        structured_rules = _try_generate_with_structured_llm(pair, diff_result, retrieved_cases, base_info)
        if structured_rules is not None and len(structured_rules) > 0:
            return structured_rules
        # structured output failed or returned empty — try plain JSON text
        text_rules = _try_generate_rules_with_text_llm(pair, diff_result, retrieved_cases, base_info)
        if text_rules is not None and len(text_rules) > 0:
            return text_rules
    return _generate_rules_with_stub(pair, diff_result, retrieved_cases, base_info)


def _try_generate_rules_with_text_llm(
    pair: ContractPair,
    diff_result: DiffResult,
    retrieved_cases: list[RetrievedCase],
    base_info: ContractBaseInfo | None = None,
) -> list[CandidateRuleForDB] | None:
    """用普通 JSON 文本方式调用 LLM，适用于不支持 structured output 的模型。"""
    config = _resolve_chat_model_config()
    try:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=config["model"],
            temperature=0,
            api_key=config["api_key"],
            base_url=config["base_url"],
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RULE_GENERATION_PROMPT),
                (
                    "human",
                    "\n".join(
                        [
                            "请根据以下结构化输入生成候选规则。",
                            "只输出 JSON，不要 Markdown，不要代码块，不要 <think> 内容。",
                            'JSON 顶层格式必须是 {{"rules": [...]}}。',
                            "合同组: {pair_json}",
                            "合同基础信息: {base_info_json}",
                            "差异结果: {diff_json}",
                            "知识库案例: {cases_json}",
                        ]
                    ),
                ),
            ]
        )
        raw = _try_generate_minimax_json_text(
            llm=llm,
            prompt=prompt,
            pair=pair,
            diff_result=diff_result,
            retrieved_cases=retrieved_cases,
            base_info=base_info,
        )
        _logger = logging.getLogger(__name__)
        if raw is None:
            _logger.warning("[ReverseRule LLM] JSON text generation returned None")
            return None
        rules = _parse_rule_batch_from_text(raw).rules
        _logger.info(
            "[ReverseRule LLM] JSON text parsed %d rules, raw text length=%d",
            len(rules), len(raw),
        )
        return rules
    except Exception as e:
        _logger = logging.getLogger(__name__)
        _logger.warning("[ReverseRule LLM] JSON text failed: %s", str(e)[:200])
        return None


def validate_candidate_rules(
    rules: list[CandidateRuleForDB],
    current_pair_id: str,
) -> list[CandidateRuleForDB]:
    valid_rules: list[CandidateRuleForDB] = []
    for rule in rules:
        try:
            data = rule.model_dump() if isinstance(rule, CandidateRuleForDB) else dict(rule)
            data["contract_type"] = data.get("contract_type") or "通用合同"
            if data.get("default_risk_level") not in {"低", "中", "高"}:
                data["default_risk_level"] = "中"
            parsed = CandidateRuleForDB.model_validate(data)
        except Exception:
            continue

        if not _has_required_rule_fields(parsed):
            continue
        if not any(trace.pair_id == current_pair_id for trace in parsed.traces):
            continue
        valid_rules.append(parsed)
    return valid_rules


def process_pair(
    pair: ContractPair,
    diff_result: DiffResult,
    base_info: ContractBaseInfo | None = None,
    rule_generator: RuleGenerator | None = None,
) -> list[CandidateRuleForDB]:
    enriched_pair = pair_with_base_info(pair, base_info)
    queries = build_retrieval_queries(diff_result, enriched_pair.contract_type, enriched_pair.review_role)
    retrieved_cases = retrieve_cases_for_diff(
        queries,
        diff_result,
        contract_type=enriched_pair.contract_type,
        review_role=enriched_pair.review_role,
    )
    generator = rule_generator or generate_rules_for_pair
    candidate_rules = generator(enriched_pair, diff_result, retrieved_cases, base_info)
    return validate_candidate_rules(candidate_rules, pair.pair_id)


def process_all_pairs(
    pairs: list[ContractPair],
    diff_results: list[DiffResult],
    base_infos: list[ContractBaseInfo],
    rule_generator: RuleGenerator | None = None,
) -> list[CandidateRuleForDB]:
    rules: list[CandidateRuleForDB] = []
    diffs_by_pair_id = {diff_result.pair_id: diff_result for diff_result in diff_results}
    base_infos_by_pair_id = {base_info.pair_id: base_info for base_info in base_infos}
    for pair in pairs:
        diff_result = diffs_by_pair_id.get(pair.pair_id)
        if diff_result is None:
            continue
        rules.extend(
            process_pair(
                pair,
                diff_result,
                base_infos_by_pair_id.get(pair.pair_id),
                rule_generator=rule_generator,
            )
        )
    return rules


def merge_rules(rules: list[CandidateRuleForDB]) -> list[CandidateRuleForDB]:
    return merge_candidate_rules(rules)


def run_reverse_rule_extraction(
    contract_pairs: list[dict[str, Any]],
    rule_generator: RuleGenerator | None = None,
) -> dict[str, Any]:
    graph = build_reverse_rule_graph()
    state: ReverseRuleState = {
        "raw_pairs": contract_pairs,
        "rule_generator": rule_generator,
    }
    final_state = graph.invoke(state)
    return final_state["result"].model_dump()


def build_reverse_rule_graph():
    graph = StateGraph(ReverseRuleState)
    graph.add_node("validate_input", _validate_input_node)
    graph.add_node("identify_base_info", _identify_base_info_node)
    graph.add_node("diff_pairs", _diff_pairs_node)
    graph.add_node("process_all_pairs", _process_all_pairs_node)
    graph.add_node("merge_rules", _merge_rules_node)
    graph.add_node("return_result", _return_result_node)
    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "identify_base_info")
    graph.add_edge("validate_input", "diff_pairs")
    graph.add_edge(["identify_base_info", "diff_pairs"], "process_all_pairs")
    graph.add_edge("process_all_pairs", "merge_rules")
    graph.add_edge("merge_rules", "return_result")
    graph.add_edge("return_result", END)
    return graph.compile()


def _validate_input_node(state: ReverseRuleState) -> ReverseRuleState:
    return {"pairs": validate_input(state["raw_pairs"])}


def _identify_base_info_node(state: ReverseRuleState) -> ReverseRuleState:
    base_infos = [
        _resolve_base_info_for_pair(pair)
        for pair in state["pairs"]
    ]
    return {"base_infos": base_infos}


def _resolve_base_info_for_pair(pair: ContractPair) -> ContractBaseInfo:
    if pair.contract_type and pair.review_role:
        return merge_base_info_with_input(pair, identify_base_info_with_heuristics(pair))
    return merge_base_info_with_input(pair, identify_base_info_for_pair(pair))


def _diff_pairs_node(state: ReverseRuleState) -> ReverseRuleState:
    return {"diff_results": [diff_contract_pair(pair) for pair in state["pairs"]]}


def _process_all_pairs_node(state: ReverseRuleState) -> ReverseRuleState:
    return {
        "pair_rules": process_all_pairs(
            state["pairs"],
            state.get("diff_results", []),
            state.get("base_infos", []),
            rule_generator=state.get("rule_generator"),
        )
    }


def _merge_rules_node(state: ReverseRuleState) -> ReverseRuleState:
    return {"rules": merge_rules(state.get("pair_rules", []))}


def _return_result_node(state: ReverseRuleState) -> ReverseRuleState:
    rules = state.get("rules", [])
    if rules:
        summary = f"共生成 {len(rules)} 条候选审核规则。"
    else:
        summary = "未生成候选审核规则。"
    return {"result": FinalRuleResult(summary=summary, rules=rules)}


def _generate_rules_with_stub(
    pair: ContractPair,
    diff_result: DiffResult,
    retrieved_cases: list[RetrievedCase],
    base_info: ContractBaseInfo | None = None,
) -> list[CandidateRuleForDB]:
    rules: list[CandidateRuleForDB] = []
    cases_by_module: dict[str, RetrievedCase] = {}
    for case in retrieved_cases:
        cases_by_module.setdefault(case.review_module, case)
    for clause in diff_result.changed_clauses:
        if not clause.is_substantive:
            continue
        case = cases_by_module.get(clause.review_module)
        if case is None:
            rules.append(_rule_from_diff_without_case(pair, clause))
            continue
        rules.append(
            CandidateRuleForDB(
                contract_type=pair.contract_type or _first_text(case.contract_type) or "通用合同",
                review_perspective=normalize_review_perspective(pair.review_role),
                review_module=case.review_module,
                risk_name=case.risk_name,
                check_point=case.check_point,
                trigger_condition=case.trigger_condition,
                default_risk_level=case.default_risk_level or "中",
                suggestion_template=case.suggestion_template,
                example_clause=case.example_clause or clause.before,
                traces=[
                    RuleExtractionTrace(
                        pair_id=pair.pair_id,
                        evidence_before=clause.before,
                        evidence_after=clause.after,
                        diff_summary=clause.diff_summary,
                        user_intent=case.user_intent or case.change_pattern,
                        confidence=0.78,
                    )
                ],
            )
        )
    return rules


def _try_generate_with_structured_llm(
    pair: ContractPair,
    diff_result: DiffResult,
    retrieved_cases: list[RetrievedCase],
    base_info: ContractBaseInfo | None = None,
) -> list[CandidateRuleForDB] | None:
    try:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI
    except Exception:
        return None

    config = _resolve_chat_model_config()
    try:
        llm = ChatOpenAI(
            model=config["model"],
            temperature=0,
            api_key=config["api_key"],
            base_url=config["base_url"],
            extra_body={"reasoning_split": True} if config.get("provider") == "minimax" else None,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RULE_GENERATION_PROMPT),
                (
                    "human",
                    "\n".join(
                        [
                            "请根据以下结构化输入生成候选规则。",
                            "只输出 JSON，不要 Markdown，不要代码块，不要 <think> 内容。",
                            'JSON 顶层格式必须是 {{"rules": [...]}}。',
                            "合同组: {pair_json}",
                            "合同基础信息: {base_info_json}",
                            "差异结果: {diff_json}",
                            "知识库案例: {cases_json}",
                        ]
                    ),
                ),
            ]
        )
        chain = prompt | llm.with_structured_output(CandidateRuleBatch)
        response = chain.invoke(
            {
                "pair_json": json.dumps(pair.model_dump(), ensure_ascii=False),
                "base_info_json": json.dumps(
                    base_info.model_dump() if base_info else {},
                    ensure_ascii=False,
                ),
                "diff_json": json.dumps(diff_result.model_dump(), ensure_ascii=False),
                "cases_json": json.dumps(
                    [case.model_dump() for case in retrieved_cases],
                    ensure_ascii=False,
                ),
            }
        )
        _logger = logging.getLogger(__name__)
        _logger.info(
            "[ReverseRule LLM] structured output returned %d rules",
            len(response.rules) if response else 0,
        )
    except Exception:
        _logger = logging.getLogger(__name__)
        _logger.info("[ReverseRule LLM] structured output failed, trying JSON text")
        raw_response = _try_generate_minimax_json_text(
            llm=llm if "llm" in locals() else None,
            prompt=prompt if "prompt" in locals() else None,
            pair=pair,
            diff_result=diff_result,
            retrieved_cases=retrieved_cases,
            base_info=base_info,
        )
        if raw_response is None:
            return None
        try:
            return _parse_rule_batch_from_text(
                raw_response,
                pair=pair,
                diff_result=diff_result,
            ).rules
        except Exception:
            return None
    return response.rules


def _has_llm_credentials() -> bool:
    if os.getenv("DISABLE_REAL_LLM") == "1":
        return False
    _load_env_file()
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "minimax":
        return bool(os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY"))


def _resolve_chat_model_config() -> dict[str, str | None]:
    _load_env_file()
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "minimax":
        return {
            "provider": "minimax",
            "model": os.getenv("LLM_MODEL_NAME") or os.getenv("MINIMAX_MODEL_NAME") or "MiniMax-M2.7",
            "api_key": os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY"),
            "base_url": (
                os.getenv("MINIMAX_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or "https://api.minimax.io/v1"
            ),
        }
    return {
        "provider": "openai",
        "model": os.getenv("LLM_MODEL_NAME", "gpt-4o-mini"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL"),
    }


def _load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _try_generate_minimax_json_text(
    *,
    llm: Any,
    prompt: Any,
    pair: ContractPair,
    diff_result: DiffResult,
    retrieved_cases: list[RetrievedCase],
    base_info: ContractBaseInfo | None = None,
) -> str | None:
    if llm is None or prompt is None:
        return None
    try:
        response = (prompt | llm).invoke(
            {
                "pair_json": json.dumps(pair.model_dump(), ensure_ascii=False),
                "base_info_json": json.dumps(
                    base_info.model_dump() if base_info else {},
                    ensure_ascii=False,
                ),
                "diff_json": json.dumps(diff_result.model_dump(), ensure_ascii=False),
                "cases_json": json.dumps(
                    [case.model_dump() for case in retrieved_cases],
                    ensure_ascii=False,
                ),
            }
        )
        text = _message_content_to_text(response)
        _logger = logging.getLogger(__name__)
        _logger.info(
            "[ReverseRule LLM] raw response length=%d, preview=%s",
            len(text), text[:200],
        )
        return text
    except Exception as e:
        _logger = logging.getLogger(__name__)
        _logger.warning("[ReverseRule LLM] minimax json text failed: %s", str(e)[:200])
        return None


def _parse_rule_batch_from_text(
    text: str,
    pair: ContractPair | None = None,
    diff_result: DiffResult | None = None,
) -> CandidateRuleBatch:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    else:
        object_start = cleaned.find("{")
        array_start = cleaned.find("[")
        starts = [index for index in (object_start, array_start) if index >= 0]
        start = min(starts) if starts else -1
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if start >= 0 and end >= start:
            cleaned = cleaned[start : end + 1]

    payload = json.loads(cleaned)
    if isinstance(payload, list):
        raw_rules = payload
    elif isinstance(payload, dict) and "rules" in payload:
        raw_rules = payload.get("rules") or []
    elif isinstance(payload, dict):
        raw_rules = [payload]
    else:
        raw_rules = []

    rules: list[CandidateRuleForDB] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            continue
        data = _coerce_llm_rule_data(raw_rule, pair=pair, diff_result=diff_result)
        try:
            rules.append(CandidateRuleForDB.model_validate(data))
        except Exception:
            continue
    return CandidateRuleBatch(rules=rules)


def _coerce_llm_rule_data(
    raw_rule: dict[str, Any],
    pair: ContractPair | None,
    diff_result: DiffResult | None,
) -> dict[str, Any]:
    data = dict(raw_rule)
    if "risk_name" not in data and "rule_name" in data:
        data["risk_name"] = data["rule_name"]
    if isinstance(data.get("contract_type"), list):
        data["contract_type"] = data["contract_type"][0] if data["contract_type"] else "通用合同"
    data.setdefault("contract_type", pair.contract_type if pair else "通用合同")
    data["review_perspective"] = normalize_review_perspective(
        data.get("review_perspective")
        or data.get("review_role")
        or (pair.review_role if pair else None)
    )
    data.setdefault("default_risk_level", "中")

    if not data.get("traces") and pair is not None and diff_result is not None:
        clause = _best_trace_clause(diff_result, data.get("review_module"))
        if clause is not None:
            data["traces"] = [
                {
                    "pair_id": pair.pair_id,
                    "evidence_before": clause.before,
                    "evidence_after": clause.after,
                    "diff_summary": clause.diff_summary,
                    "user_intent": "根据合同修改行为逆向推断候选审核规则",
                    "confidence": 0.72,
                }
            ]
    return data


def _best_trace_clause(diff_result: DiffResult, review_module: str | None):
    substantive = [clause for clause in diff_result.changed_clauses if clause.is_substantive]
    for clause in substantive:
        if review_module and clause.review_module == review_module:
            return clause
    return substantive[0] if substantive else None


def _rule_from_diff_without_case(pair: ContractPair, clause: Any) -> CandidateRuleForDB:
    review_module = clause.review_module or "通用条款"
    return CandidateRuleForDB(
        contract_type=pair.contract_type or "通用合同",
        review_perspective=normalize_review_perspective(pair.review_role),
        review_module=review_module,
        risk_name=_risk_name_from_module(review_module),
        check_point=f"检查{review_module}是否存在与本次修改相同或类似的风险安排。",
        trigger_condition=f"{review_module}条款出现类似修改前表述，可能影响权利义务、责任承担或履约确定性时触发。",
        default_risk_level="中",
        suggestion_template=f"建议参考本次修改后的表达，明确{review_module}中的关键条件、责任边界和履行要求。",
        example_clause=clause.before,
        traces=[
            RuleExtractionTrace(
                pair_id=pair.pair_id,
                evidence_before=clause.before,
                evidence_after=clause.after,
                diff_summary=clause.diff_summary,
                user_intent="无高匹配知识库案例，仅基于修改行为反推候选审核规则，需人工确认后入库。",
                confidence=0.52,
            )
        ],
    )


def _risk_name_from_module(review_module: str) -> str:
    if review_module.endswith("条款"):
        return f"{review_module}约定不明确"
    return f"{review_module}安排不当"


def _message_content_to_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(parts)
    return str(content)


def _has_required_rule_fields(rule: CandidateRuleForDB) -> bool:
    text_fields = (
        rule.contract_type,
        rule.review_module,
        rule.risk_name,
        rule.check_point,
        rule.trigger_condition,
        rule.suggestion_template,
        rule.example_clause,
    )
    if any(not field.strip() for field in text_fields):
        return False
    if not rule.traces:
        return False
    for trace in rule.traces:
        if not trace.evidence_before.strip() or not trace.evidence_after.strip():
            return False
    return True


def _first_text(value: list[str] | str | None) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _parse_retrieved_cases(raw_results: list[Any]) -> list[RetrievedCase]:
    cases: list[RetrievedCase] = []
    for raw in raw_results:
        data = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        data.pop("score", None)
        try:
            cases.append(RetrievedCase.model_validate(data))
        except Exception:
            continue
    return cases
