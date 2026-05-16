"""Coze AI 能力预留接口，按已发布工作流格式提供联调入口。"""

from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.coze_service import (
    CozeServiceError,
    build_comparison_workflow_input,
    get_coze_service,
    normalize_comparison_workflow_result,
)

coze预留_router = APIRouter(prefix="/coze", tags=["Coze AI 能力（预留）"])


class ContractComparisonInput(BaseModel):
    """合同比对任务输入模型，对齐新版 Coze 文档格式。"""
    task_type: str = "contract_comparison"
    old_text: str = "采购合同\n\n第三条 价格与结算\n本合同项下货物单价为人民币 500 元/件，总价为人民币 50,000 元。\n\n甲方应在乙方交付全部货物并经甲方验收合格，且甲方收到乙方开具的合法有效增值税专用发票后30个工作日内支付全部合同款。"
    new_text: str = "采购合同\n\n第三条 价格与结算\n本合同项下货物总价为人民币 50,000 元，具体单价由双方另行确认。\n\n甲方应在乙方交付货物后15个工作日内支付全部合同款。"
    diff_stats: dict[str, int] = {"total": 1, "added": 0, "deleted": 0, "modified": 1}
    diff_count: int = 1
    diff_texts: list[dict[str, str]] = [
        {"type": "modified", "content": "付款条款发生修改：旧版约定甲方在乙方交付全部货物并经甲方验收合格，且收到乙方合法有效增值税专用发票后30个工作日内付款；新版改为乙方交付货物后15个工作日内付款，删除了验收合格和收到发票作为付款前提，并缩短付款期限。"}
    ]


class ContractComparisonOutput(BaseModel):
    """合同比对任务输出模型，对齐新版 Coze 文档结构。"""
    success: bool
    enhanced: list[dict[str, Any]]
    total_risks: int
    stats: dict[str, int] | None = None
    summary: str | None = None
    message: str = ""


@coze预留_router.post("/contract/comparison", response_model=ContractComparisonOutput)
async def analyze_contract_comparison(input_data: ContractComparisonInput) -> ContractComparisonOutput:
    """
    合同版本比对语义增强接口。

    输入字段：task_type, old_text, new_text, diff_stats, diff_count, diff_texts。
    输出字段：success, enhanced[], total_risks, stats, summary, message。
    """
    try:
        coze_service = get_coze_service()
        parameters = build_comparison_workflow_input(
            task_type=input_data.task_type,
            old_text=input_data.old_text,
            new_text=input_data.new_text,
            diff_stats=input_data.diff_stats,
            diff_texts=input_data.diff_texts,
        )
        result = await coze_service.call_workflow(coze_service.comparison_workflow_id, parameters)
        normalized = normalize_comparison_workflow_result(result)
        return ContractComparisonOutput(
            success=normalized.get("success", True),
            enhanced=normalized.get("enhanced", []),
            total_risks=normalized.get("total_risks", 0),
            stats=normalized.get("stats"),
            summary=normalized.get("summary"),
            message=normalized.get("message", ""),
        )

    except CozeServiceError as e:
        raise HTTPException(status_code=502, detail=f"Coze 服务调用失败: {e}")


class SingleContractAnalysisOutput(BaseModel):
    """单合同审查任务输出模型，对齐 Coze 文档结构。"""
    agreeCount: str
    highlevelriskCount: str
    lowlevelriskCount: str
    output: list[dict[str, Any]]


@coze预留_router.post("/contract/review", response_model=SingleContractAnalysisOutput)
async def analyze_single_contract(
    file: Annotated[UploadFile, File(description="合同文件")]
) -> SingleContractAnalysisOutput:
    """
    单合同 AI 风险分析接口。

    后端先调用 Coze 文件上传接口获取 file_id，再按文档格式调用审查工作流。
    """
    try:
        content = await file.read()
        coze_service = get_coze_service()
        normalized = await coze_service.review_contract_file(
            content=content,
            filename=file.filename or "contract",
            content_type=file.content_type,
        )
        raw_output = normalized.get("raw_output", {})
        return SingleContractAnalysisOutput(
            agreeCount=str(raw_output.get("agreeCount", "0")),
            highlevelriskCount=str(raw_output.get("highlevelriskCount", "0")),
            lowlevelriskCount=str(raw_output.get("lowlevelriskCount", "0")),
            output=raw_output.get("output", []),
        )
    except CozeServiceError as e:
        raise HTTPException(status_code=502, detail=f"Coze 服务调用失败: {e}")
