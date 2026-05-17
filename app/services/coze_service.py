"""Coze AI 服务，提供工作流调用、文件上传和结果格式转换。"""

import json
import logging
from typing import Any

import httpx

from app.core.complass_service_settings import get_complass_service_settings

logger = logging.getLogger(__name__)


def _to_int(value: Any, default: int = 0) -> int:
    """将 Coze 可能返回的字符串计数字段转为整数。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def map_document_risk_level(value: str | None) -> str:
    """将 Coze 文档中的中文风险等级映射为后端枚举值。"""
    risk_level = (value or "").strip().lower()
    if risk_level in {"高风险", "high"}:
        return "high"
    if risk_level in {"中风险", "medium", "mid"}:
        return "medium"
    return "low"


def map_document_change_type(value: str | None) -> str:
    """将 Coze 文档中的中文差异类型映射为后端差异类型。"""
    change_type = (value or "").strip().lower()
    if change_type in {"新增", "add", "added"}:
        return "added"
    if change_type in {"删除", "delete", "deleted"}:
        return "deleted"
    return "modified"


def build_comparison_workflow_input(
    old_text: str,
    new_text: str,
    diff_stats: dict[str, int],
    diff_texts: list[dict[str, str]],
    task_type: str = "contract_comparison",
) -> dict[str, Any]:
    """构建合同比对 Coze 工作流输入，对齐 Coze 文档格式。"""
    return {
        "task_type": task_type,
        "old_text": old_text,
        "new_text": new_text,
    }


def build_review_workflow_input(file_id: str) -> dict[str, str]:
    """构建合同审查 Coze 工作流输入，优先使用文档要求的 JSON 字符串。"""
    return {"input": json.dumps({"file_id": file_id}, ensure_ascii=False, separators=(",", ":"))}


def build_review_workflow_object_input(file_id: str) -> dict[str, dict[str, str]]:
    """构建合同审查 Coze 工作流对象入参，用于字符串格式失败后的重试。"""
    return {"input": {"file_id": file_id}}


def build_workflow_run_payload(workflow_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """构建 Coze 通用工作流运行接口请求体。"""
    return {
        "workflow_id": workflow_id,
        "parameters": parameters,
    }


def extract_business_data(response_data: dict[str, Any]) -> dict[str, Any]:
    """从 Coze 外层响应中提取业务 JSON，兼容 data 为字符串或对象。"""
    # 检查错误码，即使没有 data 字段也要检查
    code = response_data.get("code")
    if code is not None and code != 0:
        message = response_data.get("msg") or response_data.get("message") or "Coze API 调用失败"
        raise CozeServiceError(f"Coze 返回错误: code={code}, msg={message}")

    if "data" not in response_data:
        return response_data

    data = response_data.get("data")
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            raise CozeServiceError(f"Coze data 字段不是合法 JSON: {e}")
        return parsed if isinstance(parsed, dict) else {"output": parsed}

    if isinstance(data, dict):
        return data

    return {"output": data}


def normalize_comparison_workflow_result(result: dict[str, Any]) -> dict[str, Any]:
    """将 Coze 合同比对文档输出转换为后端已有的增强结果结构。"""
    logger.info(f"[Coze] normalize_comparison_workflow_result 输入: {json.dumps(result, ensure_ascii=False)[:2000]}")

    if "enhanced" in result:
        logger.info("[Coze] 直接返回 enhanced 格式结果")
        return {
            "success": result.get("success", True),
            "enhanced": result.get("enhanced", []),
            "total_risks": result.get("total_risks", 0),
            "stats": result.get("stats", {}),
            "summary": result.get("summary", result.get("message", "")),
            "raw_output": result,
        }

    output = result.get("output") or {}
    diff_list = output.get("diff_list") or []
    stats = output.get("stats") or {}
    logger.info(f"[Coze] output字段: {json.dumps(output, ensure_ascii=False)[:1000]}")
    logger.info(f"[Coze] diff_list: {diff_list}")
    logger.info(f"[Coze] stats: {stats}")

    enhanced = []
    for item in diff_list:
        change_type = map_document_change_type(item.get("type"))
        risk_level = map_document_risk_level(item.get("risk_level"))
        old_text = item.get("old") or ""
        new_text = item.get("new") or ""
        original = new_text or old_text or f"{old_text} -> {new_text}".strip()

        enhanced.append({
            "original": original,
            "change_type": change_type,
            "category": item.get("rule_id"),
            "summary": item.get("analysis", ""),
            "risk_level": risk_level,
            "evidence": f"旧版：{old_text}\n新版：{new_text}".strip(),
            "impact": item.get("analysis", ""),
            "suggestion": item.get("advice", ""),
            "rule_id": item.get("rule_id"),
            "type": item.get("type"),
            "old": old_text,
            "new": new_text,
            "analysis": item.get("analysis", ""),
            "advice": item.get("advice", ""),
        })

    return {
        "success": True,
        "enhanced": enhanced,
        "total_risks": sum(1 for item in enhanced if item.get("risk_level") in {"high", "medium"}),
        "stats": {
            "added": _to_int(stats.get("addCount")),
            "deleted": _to_int(stats.get("deleteCount")),
            "modified": _to_int(stats.get("modifyCount")),
        },
        "summary": output.get("summary", ""),
        "raw_output": result,
    }


def normalize_review_workflow_result(result: dict[str, Any]) -> dict[str, Any]:
    """将 Coze 合同审查文档输出（PDF格式）转换为后端任务和风险点结构。"""
    if "risk_points" in result:
        return result

    logger.info(f"[Coze] 原始工作流返回: {json.dumps(result, ensure_ascii=False)[:1000]}")

    # PDF 文档字段：agreeCount, highlevelriskCount, lowlevelriskCount (string类型)
    high_count = _to_int(result.get("highlevelriskCount"))
    low_count = _to_int(result.get("lowlevelriskCount"))
    passed_count = _to_int(result.get("agreeCount"))

    risk_points = []
    for item in result.get("output") or []:
        logger.info(f"[Coze] 处理风险点 item: {json.dumps(item, ensure_ascii=False)}")
        risk_points.append({
            "title": item.get("key", ""),
            "level": map_document_risk_level(item.get("risk", "")),
            "reason": item.get("tip", ""),
            "suggestion": item.get("advice", ""),
            "evidence": item.get("content", ""),
            "impact": item.get("tip", ""),
            "replace_text": item.get("replace_text", ""),
        })

    return {
        "success": True,
        "overall_conclusion": f"合同审查完成，通过 {passed_count} 项，高风险 {high_count} 项，低风险 {low_count} 项。",
        "risk_summary": {
            "high": high_count,
            "medium": 0,
            "low": low_count,
            "passed": passed_count,
        },
        "risk_points": risk_points,
        "suggest_deep_review": high_count > 0,
        "message": result.get("message", ""),
        "raw_output": result,
    }


class CozeServiceError(Exception):
    """Coze 服务异常。"""
    pass


class CozeService:
    """Coze API 调用服务。"""

    def __init__(self):
        self.settings = get_complass_service_settings()
        self.api_base = self.settings.coze_api_base_url.rstrip("/")
        self.token = self.settings.coze_access_token or self.settings.coze_api_token
        self.comparison_workflow_id = (
            self.settings.coze_comparison_workflow_id
            or self.settings.coze_workflow_id
        )
        self.review_workflow_id = self.settings.coze_review_workflow_id

    async def call_workflow(self, workflow_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """
        调用 Coze 工作流。

        Args:
            workflow_id: Coze 工作流 ID
            parameters: 工作流 parameters 入参

        Returns:
            工作流返回结果

        Raises:
            CozeServiceError: 调用失败时抛出
        """
        if not self.token:
            raise CozeServiceError("缺少 COZE_ACCESS_TOKEN，无法调用 Coze 工作流")

        url = f"{self.api_base}/v1/workflow/run"
        payload = build_workflow_run_payload(workflow_id, parameters)

        logger.info(f"[Coze] 开始调用工作流: workflow_id={workflow_id}")
        logger.info(f"[Coze] 工作流入参长度: old_text={len(parameters.get('old_text', ''))}, new_text={len(parameters.get('new_text', ''))}")
        logger.info(f"[Coze] 工作流 parameters 内容: task_type={parameters.get('task_type')}, old_text前20字={parameters.get('old_text', '')[:20]}, new_text前20字={parameters.get('new_text', '')[:20]}")
        logger.debug(f"[Coze] 工作流入参: {json.dumps(parameters, ensure_ascii=False)[:1000]}")

        async with httpx.AsyncClient(timeout=self.settings.coze_workflow_timeout_seconds) as client:
            try:
                logger.info(f"[Coze] 完整请求 payload: {json.dumps(payload, ensure_ascii=False)[:2000]}")
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )

                if response.status_code != 200:
                    logger.error(f"[Coze] API 返回错误状态码: {response.status_code}, body: {response.text}")
                    raise CozeServiceError(f"Coze API 调用失败: {response.status_code} {response.text}")

                response_json = response.json()
                logger.info(f"[Coze] 原始响应状态码: {response.status_code}")
                logger.info(f"[Coze] 原始响应 body: {json.dumps(response_json, ensure_ascii=False)[:2000]}")

                result = extract_business_data(response_json)
                logger.info(f"[Coze] 解析后业务数据: {json.dumps(result, ensure_ascii=False)[:2000]}")
                return result

            except httpx.HTTPError as e:
                logger.error(f"[Coze] 网络错误: {type(e).__name__}: {e!r}")
                raise CozeServiceError(f"Coze API 网络错误: {type(e).__name__}: {e!r}")

    async def upload_file(self, content: bytes, filename: str, content_type: str | None = None) -> str:
        """上传合同文件到 Coze 并返回 file_id。"""
        if not self.token:
            raise CozeServiceError("缺少 COZE_ACCESS_TOKEN，无法上传 Coze 文件")

        url = f"{self.api_base}/v1/files/upload"
        files = {
            "file": (filename, content, content_type or "application/octet-stream")
        }

        logger.info(f"[Coze] 开始上传文件: {filename}")

        async with httpx.AsyncClient(timeout=self.settings.coze_upload_timeout_seconds) as client:
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    files=files,
                )

                if response.status_code != 200:
                    raise CozeServiceError(f"Coze 文件上传失败: {response.status_code} {response.text}")

                data = response.json()
                if data.get("code") not in (None, 0):
                    message = data.get("msg") or data.get("message") or "Coze 文件上传失败"
                    raise CozeServiceError(str(message))

                file_id = (data.get("data") or {}).get("id")
                if not file_id:
                    raise CozeServiceError("Coze 文件上传响应缺少 data.id")

                logger.info(f"[Coze] 文件上传成功: {filename} -> file_id={file_id}")
                return file_id

            except httpx.HTTPError as e:
                raise CozeServiceError(f"Coze 文件上传网络错误: {type(e).__name__}: {e!r}")

    async def review_contract_file(
        self,
        content: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """上传合同文件后按 Coze 文档格式调用合同审查工作流。"""
        file_id = await self.upload_file(content, filename, content_type)
        logger.info(f"[Coze] 开始审查合同: file_id={file_id}, workflow_id={self.review_workflow_id}")
        try:
            result = await self.call_workflow(
                self.review_workflow_id,
                build_review_workflow_input(file_id),
            )
        except CozeServiceError:
            logger.warning(f"[Coze] JSON格式调用失败，尝试对象格式重试")
            result = await self.call_workflow(
                self.review_workflow_id,
                build_review_workflow_object_input(file_id),
            )
        return normalize_review_workflow_result(result)

    async def enhance_diff_result(self, diff_summary: dict[str, Any]) -> dict[str, Any]:
        """
        对 diff 结果进行语义增强。

        Args:
            diff_summary: 差异汇总结果，需包含 old_text、new_text、diff_stats、diff_texts

        Returns:
            语义增强后的结果
        """
        workflow_input = build_comparison_workflow_input(
            old_text=diff_summary.get("old_text", ""),
            new_text=diff_summary.get("new_text", ""),
            diff_stats=diff_summary.get("diff_stats", {"total": 0, "added": 0, "deleted": 0, "modified": 0}),
            diff_texts=diff_summary.get("diff_texts", []),
        )
        result = await self.call_workflow(self.comparison_workflow_id, workflow_input)
        return normalize_comparison_workflow_result(result)


def get_coze_service() -> CozeService:
    """获取 Coze 服务实例。"""
    return CozeService()
