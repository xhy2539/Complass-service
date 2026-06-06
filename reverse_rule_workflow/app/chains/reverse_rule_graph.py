import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from typing import Callable
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from app.kb.fallback import fallback_reverse_rule_cases
from app.models.reverse_rule import CandidateRuleBatch
from app.models.reverse_rule import CandidateRuleForDB
from app.models.reverse_rule import ContractBaseInfo
from app.models.reverse_rule import ContractPair
from app.models.reverse_rule import DiffResult
from app.models.reverse_rule import FinalRuleResult
from app.models.reverse_rule import RetrievedCase
from app.models.reverse_rule import RuleExtractionTrace
from app.prompts import RULE_GENERATION_PROMPT
from app.services.base_info import identify_base_info_for_pair
from app.services.base_info import identify_base_info_with_heuristics
from app.services.base_info import merge_base_info_with_input
from app.services.base_info import pair_with_base_info
from app.services.diff_service import ContractContextIndex
from app.services.diff_service import detect_candidate_diffs
from app.services.diff_service import diff_contract_pair
from app.services.diff_service import split_and_index_contract
from app.services.query_builder import build_retrieval_queries
from app.services.reverse_rule_tools import build_context_pack
from app.services.review_perspective import normalize_review_perspective
from app.services.rule_merger import merge_candidate_rules

RuleGenerator = Callable[
    [ContractPair, DiffResult, list[RetrievedCase], ContractBaseInfo | None],
    list[CandidateRuleForDB],
]


class ReverseRuleState(TypedDict, total=False):
    raw_pairs: list[dict[str, Any]]
    pairs: list[ContractPair]
    context_indexes: list[ContractContextIndex]
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
    retrieved: list[RetrievedCase] = []
    substantive_clauses = [
        clause for clause in diff_result.changed_clauses if clause.is_substantive
    ]

    for index, query in enumerate(queries):
        clause = (
            substantive_clauses[index] if index < len(substantive_clauses) else None
        )
        review_module = clause.review_module if clause else None

        # 1. Try RAG service first
        try:
            from app.kb.rag_client import rag_search

            rag_results = rag_search(
                query=query,
                review_module=review_module,
                contract_type=contract_type,
                review_role=review_role,
                top_k=k,
            )
            if rag_results:
                retrieved.extend(_parse_retrieved_cases(rag_results))
                continue
        except Exception:
            pass

        # 2. RAG failed or returned empty — local retriever
        try:
            import app.kb.retriever as retriever

            raw_results = retriever.retrieve_reverse_rule_cases(
                query,
                review_module=review_module,
                contract_type=contract_type,
                review_role=review_role,
                k=k,
            )
            retrieved.extend(_parse_retrieved_cases(raw_results))
        except Exception:
            pass

    return retrieved or fallback_reverse_rule_cases(diff_result, k=k)


def generate_rules_for_pair(
    pair: ContractPair,
    diff_result: DiffResult,
    retrieved_cases: list[RetrievedCase],
    base_info: ContractBaseInfo | None = None,
) -> list[CandidateRuleForDB]:
    if _has_llm_credentials():
        structured_rules = _try_generate_with_structured_llm(
            pair, diff_result, retrieved_cases, base_info
        )
        if structured_rules is not None and len(structured_rules) > 0:
            return structured_rules
        # structured output failed or returned empty — try plain JSON text
        text_rules = _try_generate_rules_with_text_llm(
            pair, diff_result, retrieved_cases, base_info
        )
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
                            "上下文包: {context_json}",
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
            len(rules),
            len(raw),
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
            data = (
                rule.model_dump()
                if isinstance(rule, CandidateRuleForDB)
                else dict(rule)
            )
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


def _pair_prompt_payload(pair: ContractPair) -> dict[str, Any]:
    return {
        "pair_id": pair.pair_id,
        "contract_type": pair.contract_type,
        "review_role": pair.review_role,
    }


def _context_prompt_payload(
    pair: ContractPair, diff_result: DiffResult
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for diff in diff_result.changed_clauses:
        if not diff.is_substantive:
            continue
        context_pack = build_context_pack(
            pair.pair_id, pair.before_text, pair.after_text, diff
        )
        payload.append(context_pack.model_dump())
    return payload


def process_pair(
    pair: ContractPair,
    diff_result: DiffResult,
    base_info: ContractBaseInfo | None = None,
    rule_generator: RuleGenerator | None = None,
) -> list[CandidateRuleForDB]:
    enriched_pair = pair_with_base_info(pair, base_info)
    queries = build_retrieval_queries(
        diff_result, enriched_pair.contract_type, enriched_pair.review_role
    )
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
    diffs_by_pair_id = {
        diff_result.pair_id: diff_result for diff_result in diff_results
    }
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
    graph.add_node("split_and_index_contract", _split_and_index_contract_node)
    graph.add_node("diff_pairs", _diff_pairs_node)
    graph.add_node("process_all_pairs", _process_all_pairs_node)
    graph.add_node("merge_rules", _merge_rules_node)
    graph.add_node("return_result", _return_result_node)
    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "identify_base_info")
    graph.add_edge("validate_input", "split_and_index_contract")
    graph.add_edge("split_and_index_contract", "diff_pairs")
    graph.add_edge(["identify_base_info", "diff_pairs"], "process_all_pairs")
    graph.add_edge("process_all_pairs", "merge_rules")
    graph.add_edge("merge_rules", "return_result")
    graph.add_edge("return_result", END)
    return graph.compile()


def _validate_input_node(state: ReverseRuleState) -> ReverseRuleState:
    return {"pairs": validate_input(state["raw_pairs"])}


def _identify_base_info_node(state: ReverseRuleState) -> ReverseRuleState:
    base_infos = [_resolve_base_info_for_pair(pair) for pair in state["pairs"]]
    return {"base_infos": base_infos}


def _resolve_base_info_for_pair(pair: ContractPair) -> ContractBaseInfo:
    if pair.contract_type and pair.review_role:
        return merge_base_info_with_input(
            pair, identify_base_info_with_heuristics(pair)
        )
    return merge_base_info_with_input(pair, identify_base_info_for_pair(pair))


def _split_and_index_contract_node(state: ReverseRuleState) -> ReverseRuleState:
    return {
        "context_indexes": [
            split_and_index_contract(pair.pair_id, pair.before_text, pair.after_text)
            for pair in state["pairs"]
        ]
    }


def _diff_pairs_node(state: ReverseRuleState) -> ReverseRuleState:
    indexes_by_pair_id = {
        context_index.pair_id: context_index
        for context_index in state.get("context_indexes", [])
    }
    diff_results: list[DiffResult] = []
    for pair in state["pairs"]:
        context_index = indexes_by_pair_id.get(pair.pair_id)
        if context_index is None:
            diff_results.append(diff_contract_pair(pair))
            continue
        diff_results.append(
            DiffResult(
                pair_id=pair.pair_id,
                changed_clauses=detect_candidate_diffs(pair.pair_id, context_index),
            )
        )
    return {"diff_results": diff_results}


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
        if clause.review_module in _MODULE_TEMPLATE_RULES:
            rules.append(_rule_from_diff_without_case(pair, clause))
            continue
        case = cases_by_module.get(clause.review_module)
        if case is None:
            rules.append(_rule_from_diff_without_case(pair, clause))
            continue
        rules.append(
            CandidateRuleForDB(
                contract_type=pair.contract_type
                or _first_text(case.contract_type)
                or "通用合同",
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
            extra_body={"reasoning_split": True}
            if config.get("provider") == "minimax"
            else None,
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
                            "上下文包: {context_json}",
                            "知识库案例: {cases_json}",
                        ]
                    ),
                ),
            ]
        )
        chain = prompt | llm.with_structured_output(CandidateRuleBatch)
        response = chain.invoke(
            {
                "pair_json": json.dumps(_pair_prompt_payload(pair), ensure_ascii=False),
                "base_info_json": json.dumps(
                    base_info.model_dump() if base_info else {},
                    ensure_ascii=False,
                ),
                "diff_json": json.dumps(diff_result.model_dump(), ensure_ascii=False),
                "context_json": json.dumps(
                    _context_prompt_payload(pair, diff_result),
                    ensure_ascii=False,
                ),
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
            "model": os.getenv("LLM_MODEL_NAME")
            or os.getenv("MINIMAX_MODEL_NAME")
            or "MiniMax-M2.7",
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
                "pair_json": json.dumps(_pair_prompt_payload(pair), ensure_ascii=False),
                "base_info_json": json.dumps(
                    base_info.model_dump() if base_info else {},
                    ensure_ascii=False,
                ),
                "diff_json": json.dumps(diff_result.model_dump(), ensure_ascii=False),
                "context_json": json.dumps(
                    _context_prompt_payload(pair, diff_result),
                    ensure_ascii=False,
                ),
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
            len(text),
            text[:200],
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
    fenced = re.search(
        r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL | re.IGNORECASE
    )
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
        data["contract_type"] = (
            data["contract_type"][0] if data["contract_type"] else "通用合同"
        )
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
    substantive = [
        clause for clause in diff_result.changed_clauses if clause.is_substantive
    ]
    for clause in substantive:
        if review_module and clause.review_module == review_module:
            return clause
    return substantive[0] if substantive else None


_MODULE_TEMPLATE_RULES = {
    "付款条款",
    "服务水平",
    "知识产权",
    "交付验收",
    "押金退还",
    "数据安全",
    "管辖法院",
    "保密条款",
    "解除条款",
}


def _rule_from_diff_without_case(pair: ContractPair, clause: Any) -> CandidateRuleForDB:
    review_module = clause.review_module or "通用条款"
    template = _module_rule_template(review_module, clause)
    return CandidateRuleForDB(
        contract_type=pair.contract_type or "通用合同",
        review_perspective=normalize_review_perspective(pair.review_role),
        review_module=review_module,
        risk_name=template["risk_name"],
        check_point=template["check_point"],
        trigger_condition=template["trigger_condition"],
        default_risk_level="中",
        suggestion_template=template["suggestion_template"],
        example_clause=clause.before or clause.after,
        traces=[
            RuleExtractionTrace(
                pair_id=pair.pair_id,
                evidence_before=clause.before or "原合同未约定对应内容",
                evidence_after=clause.after or "修改后未保留对应内容",
                diff_summary=clause.diff_summary,
                user_intent="无高匹配知识库案例，仅基于修改行为反推候选审核规则，需人工确认后入库。",
                confidence=0.52,
            )
        ],
    )


def _module_rule_template(review_module: str, clause: Any) -> dict[str, str]:
    after = str(getattr(clause, "after", "") or "")
    before = str(getattr(clause, "before", "") or "")
    evidence = after or before
    if review_module == "付款条款":
        return {
            "risk_name": "付款及发票条件不明确",
            "check_point": "检查付款期限、付款起算节点、合法有效发票和付款前置条件是否明确。",
            "trigger_condition": f"合同未明确30日内付款、合法有效发票或付款起算条件时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确在验收或确认完成并收到合法有效发票后30日内付款，避免付款期限和发票条件不清。",
        }
    if review_module == "服务水平":
        return {
            "risk_name": "SLA响应和未达标扣减机制缺失",
            "check_point": "检查SLA响应时间、恢复时间、未达标整改和服务费扣减机制是否明确。",
            "trigger_condition": f"合同未明确1小时等响应时间、恢复时限或5%等服务费扣减机制时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确SLA响应时间、恢复时间、连续未达标的整改方案和服务费扣减机制。",
        }
    if review_module == "知识产权":
        return {
            "risk_name": "成果和源代码知识产权归属不明确",
            "check_point": "检查源代码、技术文档、接口文档、交付成果和既有组件的知识产权归属是否清晰。",
            "trigger_condition": f"合同未明确源代码、交付成果归属或未约定甲方所有及既有组件保留时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确知识产权归属，区分定制成果、源代码、技术文档和乙方既有组件或通用工具。",
        }
    if review_module == "交付验收":
        return {
            "risk_name": "验收标准和整改机制不明确",
            "check_point": "检查验收标准、验收期限、验收不合格处理和免费整改机制是否明确。",
            "trigger_condition": f"合同未明确验收标准、验收期限或整改期限时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确验收标准、组织验收期限、验收不合格后的免费整改期限和再次验收安排。",
        }
    if review_module == "押金退还":
        return {
            "risk_name": "押金退还条件和期限不明确",
            "check_point": "检查押金退还条件、房屋交接、款项结清和退还期限是否明确。",
            "trigger_condition": f"合同仅约定视情况退还押金，未明确7个工作日等退还期限或交接条件时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确交接、结清费用和无损坏等退还条件，并约定出租方在固定期限内退还押金。",
        }
    if review_module == "数据安全":
        return {
            "risk_name": "数据处理和返还删除义务不明确",
            "check_point": "检查数据处理目的、处理范围、数据返还、删除和书面证明义务是否明确。",
            "trigger_condition": f"合同未明确数据处理边界、10日内返还或删除及书面证明义务时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确数据处理目的和范围，约定合同终止后的返还、删除期限及书面证明。",
        }
    if review_module == "管辖法院":
        return {
            "risk_name": "争议解决和管辖法院约定不明确",
            "check_point": "检查争议解决路径、协商期限和管辖法院是否明确且便利。",
            "trigger_condition": f"合同未明确协商不成后的起诉路径、甲方所在地或有管辖权法院时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确协商不成后的争议解决方式，并约定管辖法院所在地，例如甲方所在地有管辖权的法院。",
        }
    if review_module == "保密条款":
        return {
            "risk_name": "保密范围和保密期限不明确",
            "check_point": "检查保密范围、客户数据、个人信息和合同终止后的保密期限是否明确。",
            "trigger_condition": f"合同未明确客户数据等保密范围或终止后5年等保密期限时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议明确保密范围、保密期限、客户数据和个人信息保护要求，并约定终止后的持续保密义务。",
        }
    if review_module == "解除条款":
        return {
            "risk_name": "解除通知和费用结算机制缺失",
            "check_point": "检查单方解除是否约定提前书面通知、已完成工作量和费用结算。",
            "trigger_condition": f"合同允许随时解除但未约定30日书面通知或结算已完成工作量时触发；参考修改后表述：{_clip(evidence)}",
            "suggestion_template": "建议约定解除需提前30日书面通知，并按已完成工作量进行费用结算。",
        }
    return {
        "risk_name": _risk_name_from_module(review_module),
        "check_point": f"检查{review_module}是否存在与本次修改相同或类似的风险安排。",
        "trigger_condition": f"{review_module}条款出现类似修改前表述，可能影响权利义务、责任承担或履约确定性时触发。",
        "suggestion_template": f"建议参考本次修改后的表达，明确{review_module}中的关键条件、责任边界和履行要求。",
    }


def _clip(text: str, limit: int = 80) -> str:
    stripped = text.strip()
    return stripped if len(stripped) <= limit else stripped[:limit] + "..."


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
            _logger = logging.getLogger(__name__)
            _logger.warning(
                "[ReverseRule] failed to parse retrieved case: %s",
                str(data.get("case_id", data))[:100],
            )
    return cases
