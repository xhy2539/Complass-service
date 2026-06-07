"""MiniMax M3 LLM Re-rank：Top-N → Top-K。"""

import json
import os
import threading

_lock = threading.Lock()

RERANK_PROMPT = """你是合同审核规则检索助手。
根据查询条件，从候选案例中选出最相关的 Top-{top_k} 条案例。
只输出一个 JSON 数组，包含选中的 case_id，不要其他内容。
格式：["case_id_1", "case_id_2", ...]

查询条件：
{query}

候选案例：
{cases_json}"""


def _get_llm_config() -> dict:
    return {
        "api_key": os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        "model": os.getenv("LLM_MODEL_NAME", "MiniMax-M2.7"),
    }


def rerank(
    query: str,
    candidates: list[dict],
    top_k: int = 3,
) -> list[dict]:
    """用 MiniMax M3 从候选集中精选 top_k 条。"""
    if len(candidates) <= top_k:
        return candidates

    # 精简候选数据，减少 token（保留检索关键字段用于重排）
    slimmed = []
    for c in candidates:
        slimmed.append(
            {
                "case_id": c["case_id"],
                "review_module": c.get("review_module", ""),
                "change_pattern": c.get("change_pattern", ""),
                "risk_name": c.get("risk_name", ""),
                "check_point": c.get("check_point", ""),
                "trigger_condition": c.get("trigger_condition", ""),
                "diff_summary": c.get("diff_summary", ""),
                "user_intent": c.get("user_intent", ""),
            }
        )

    prompt = RERANK_PROMPT.format(
        top_k=top_k,
        query=query,
        cases_json=json.dumps(slimmed, ensure_ascii=False, indent=2),
    )

    config = _get_llm_config()
    if not config["api_key"]:
        return candidates[:top_k]

    try:
        import httpx

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 512,
                },
            )
            if resp.status_code != 200:
                return candidates[:top_k]
            body = resp.json()
            content = body["choices"][0]["message"]["content"]

        # Parse LLM response: extract JSON array
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            selected_ids = json.loads(content[start : end + 1])
            # Map selected IDs back to candidates
            id_map = {c["case_id"]: c for c in candidates}
            result = [id_map[cid] for cid in selected_ids if cid in id_map]
            if result:
                return result[:top_k]
    except Exception:
        pass

    return candidates[:top_k]
