import json
import os
import re
from pathlib import Path

from app.models.reverse_rule import ContractBaseInfo
from app.models.reverse_rule import ContractPair

BASE_INFO_PROMPT = """
你是合同基础信息识别助手。
请根据修改前后的合同文本判断合同类型、审核角色、合同主题和甲乙方业务身份。
只输出符合 ContractBaseInfo schema 的 JSON，不要输出 Markdown、代码块或解释。
如果文本无法可靠判断，请输出通用合同、通用角色、通用合同事项，并降低 confidence。
"""


def identify_base_info_for_pair(pair: ContractPair) -> ContractBaseInfo:
    if _has_llm_credentials():
        llm_result = _try_identify_with_structured_llm(pair)
        if llm_result is not None:
            return llm_result
    return identify_base_info_with_heuristics(pair)


def identify_base_info_with_heuristics(pair: ContractPair) -> ContractBaseInfo:
    text = f"{pair.before_text}\n{pair.after_text}"
    contract_type, type_score = _infer_contract_type(text)
    review_role, role_score = _infer_review_role(text)
    subject, subject_score = _infer_contract_subject(text)
    party_a_identity, party_b_identity, party_score = _infer_party_identities(
        text, contract_type
    )

    confidence = min(
        0.92, max(0.2, 0.2 + type_score + role_score + subject_score + party_score)
    )
    return ContractBaseInfo(
        pair_id=pair.pair_id,
        contract_type=contract_type,
        review_role=review_role,
        contract_subject=subject,
        party_a_identity=party_a_identity,
        party_b_identity=party_b_identity,
        confidence=round(confidence, 2),
    )


def merge_base_info_with_input(
    pair: ContractPair, base_info: ContractBaseInfo
) -> ContractBaseInfo:
    return base_info.model_copy(
        update={
            "contract_type": pair.contract_type or base_info.contract_type,
            "review_role": pair.review_role or base_info.review_role,
        }
    )


def pair_with_base_info(
    pair: ContractPair, base_info: ContractBaseInfo | None
) -> ContractPair:
    if base_info is None:
        return pair
    return pair.model_copy(
        update={
            "contract_type": pair.contract_type or base_info.contract_type,
            "review_role": pair.review_role or base_info.review_role,
        }
    )


def _infer_contract_type(text: str) -> tuple[str, float]:
    if "技术服务" in text:
        return "技术服务合同", 0.24
    if any(keyword in text for keyword in ("采购", "供应", "供货", "设备", "货物")):
        return "采购合同", 0.24
    if "合作" in text:
        return "合作协议", 0.22
    if any(keyword in text for keyword in ("服务", "委托", "咨询")):
        return "服务合同", 0.2
    return "通用合同", 0.03


def _infer_review_role(text: str) -> tuple[str, float]:
    if re.search(r"向\s*乙方\s*支付|支付[^。；;\n]*乙方", text):
        return "乙方", 0.2
    if re.search(r"乙方[^。；;\n]*(供应|供货|交付|安装|调试|服务|收款)", text):
        return "乙方", 0.18
    if re.search(r"甲方[^。；;\n]*(采购|付款|委托|验收|接收)", text):
        return "甲方", 0.14
    return "通用角色", 0.03


def _infer_contract_subject(text: str) -> tuple[str, float]:
    for raw_line in text.splitlines():
        line = raw_line.strip(" \t：:")
        if not line:
            continue
        if any(marker in line for marker in ("合同", "协议")) and len(line) <= 60:
            return _clean_subject(line), 0.18

    if "智能设备" in text and "安装调试" in text:
        return "智能设备采购及安装调试", 0.16
    if "设备" in text and "采购" in text:
        return "设备采购", 0.12
    if "服务" in text:
        return "服务事项", 0.1
    return "通用合同事项", 0.03


def _infer_party_identities(
    text: str, contract_type: str
) -> tuple[str | None, str | None, float]:
    if (
        re.search(r"甲方[^。；;\n]*采购", text)
        and re.search(r"乙方[^。；;\n]*(供应|供货)", text)
        and re.search(r"乙方[^。；;\n]*(安装|调试)", text)
    ):
        return "采购方", "供应及安装调试方", 0.18
    if contract_type == "采购合同":
        return "采购方", "供应方", 0.14
    if contract_type in {"服务合同", "技术服务合同"}:
        return "委托方", "服务方", 0.12
    if contract_type == "合作协议":
        return "合作方", "合作方", 0.08
    return None, None, 0.0


def _clean_subject(title: str) -> str:
    cleaned = re.sub(r"^[《“\"']|[》”\"']$", "", title.strip())
    cleaned = re.sub(r"(合同|协议)$", "", cleaned).strip()
    return cleaned or "通用合同事项"


def _has_llm_credentials() -> bool:
    if os.getenv("DISABLE_REAL_LLM") == "1":
        return False
    _load_env_file()
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "minimax":
        return bool(os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY"))


def _try_identify_with_structured_llm(pair: ContractPair) -> ContractBaseInfo | None:
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
                ("system", BASE_INFO_PROMPT),
                (
                    "human",
                    "\n".join(
                        [
                            "请识别以下合同修改对的基础信息。",
                            "合同组: {pair_json}",
                        ]
                    ),
                ),
            ]
        )
        response = (prompt | llm.with_structured_output(ContractBaseInfo)).invoke(
            {"pair_json": json.dumps(pair.model_dump(), ensure_ascii=False)}
        )
        return response.model_copy(update={"pair_id": pair.pair_id})
    except Exception:
        return None


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
