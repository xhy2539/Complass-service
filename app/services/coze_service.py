"""Coze AI 服务，提供工作流调用和语义增强能力。"""

from typing import Any

import httpx

from app.core.complass_service_settings import get_complass_service_settings


class CozeServiceError(Exception):
    """Coze 服务异常。"""
    pass


class CozeService:
    """Coze API 调用服务。"""

    def __init__(self):
        self.settings = get_complass_service_settings()
        self.api_base = self.settings.coze_api_base_url
        self.token = self.settings.coze_api_token
        self.workflow_id = self.settings.coze_workflow_id
        self.mock_enabled = self.settings.coze_mock_enabled

    async def call_workflow(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        """
        调用 Coze 工作流。

        Args:
            workflow_input: 工作流输入参数

        Returns:
            工作流返回结果

        Raises:
            CozeServiceError: 调用失败时抛出
        """
        if self.mock_enabled or not self.token:
            return self._mock_response(workflow_input)

        url = f"{self.api_base}/v1/workflows/{self.workflow_id}/run"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json"
                    },
                    json=workflow_input
                )

                if response.status_code != 200:
                    raise CozeServiceError(f"Coze API 调用失败: {response.status_code}")

                return response.json()

            except httpx.HTTPError as e:
                raise CozeServiceError(f"Coze API 网络错误: {e}")

    def _mock_response(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        """
        返回模拟响应，用于开发和测试。

        Args:
            workflow_input: 工作流输入参数

        Returns:
            模拟的增强结果
        """
        task_type = workflow_input.get("task_type", "")

        if task_type == "contract_review":
            # 单合同审查 Mock 响应
            text = workflow_input.get("text", "")
            char_count = workflow_input.get("char_count", 0)

            return {
                "success": True,
                "overall_conclusion": "合同风险较低，未发现明显异常条款",
                "risk_summary": {"high": 0, "medium": 1, "low": 2},
                "risk_points": [
                    {
                        "title": "付款条款待明确",
                        "level": "medium",
                        "category": "付款条款",
                        "reason": "合同中未明确约定具体付款时间和方式",
                        "evidence": "合同正文中未找到关于付款时间、付款方式的明确条款",
                        "impact": "可能导致付款纠纷，影响合同执行",
                        "suggestion": "建议补充付款条款明细，包括付款时间、付款方式、付款账户等",
                        "position": None
                    },
                    {
                        "title": "合同格式规范",
                        "level": "low",
                        "category": "合同结构",
                        "reason": "合同结构完整，条款清晰",
                        "evidence": "合同包含完整的标题、标的、价款、违约责任等条款",
                        "impact": "无明显影响",
                        "suggestion": "可直接使用",
                        "position": None
                    },
                    {
                        "title": "附件条款完整",
                        "level": "low",
                        "category": "附件约定",
                        "reason": "合同包含完整的附件说明",
                        "evidence": "合同明确约定了附件清单及效力",
                        "impact": "无明显影响",
                        "suggestion": "无需修改",
                        "position": None
                    }
                ],
                "suggest_deep_review": False,
                "message": "当前为 Mock 模式，请联系 AI 工程师接入真实 Coze 工作流"
            }

        # 默认：合同比对 Mock 响应
        diff_texts = workflow_input.get("diff_texts", [])

        mock_enhanced = []
        for item in diff_texts:
            change_type = item.get("type", item.get("change_type", "unknown"))
            content = item.get("content", "")

            # 为不同 change_type 设置不同的 category
            category_map = {
                "added": "新增条款",
                "deleted": "删除条款",
                "modified": "修改条款"
            }

            mock_enhanced.append({
                "original": content,
                "change_type": change_type,
                "category": category_map.get(change_type, "未知"),
                "summary": f"【{change_type}】{content[:50]}..." if len(content) > 50 else f"【{change_type}】{content}",
                "risk_level": "medium" if change_type == "modified" else "low",
                "evidence": f"差异内容：{content[:100]}..." if len(content) > 100 else f"差异内容：{content}",
                "impact": "建议关注此改动，可能影响合同权益" if change_type == "modified" else "无明显影响",
                "suggestion": "建议人工确认" if change_type == "modified" else "可忽略"
            })

        return {
            "success": True,
            "enhanced": mock_enhanced,
            "total_risks": sum(1 for e in mock_enhanced if e["risk_level"] != "low")
        }

    async def enhance_diff_result(self, diff_summary: dict[str, Any]) -> dict[str, Any]:
        """
        对 diff 结果进行语义增强。

        Args:
            diff_summary: 差异汇总结果

        Returns:
            语义增强后的结果
        """
        # 构建 Coze 工作流输入（适配 Coze 的 Object/Object Array 类型）
        diff_items = (
            [{"type": "added", "content": text} for text in diff_summary.get("added_texts", [])]
            + [{"type": "deleted", "content": text} for text in diff_summary.get("deleted_texts", [])]
            + [{"type": "modified", "content": f"{m['old']} -> {m['new']}"} for m in diff_summary.get("modified_texts", [])]
        )

        workflow_input = {
            "task_type": "contract_comparison",
            "old_text": diff_summary.get("old_text", ""),
            "new_text": diff_summary.get("new_text", ""),
            "diff_stats": {
                "added": diff_summary.get("added", 0),
                "deleted": diff_summary.get("deleted", 0),
                "modified": diff_summary.get("modified", 0)
            },
            "diff_count": len(diff_items),
            "diff_texts": diff_items
        }

        return await self.call_workflow(workflow_input)


def get_coze_service() -> CozeService:
    """获取 Coze 服务实例。"""
    return CozeService()