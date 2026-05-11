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
    """合同比对任务输入模型，对齐 Coze 文档字段。"""
    old_version_text: str
    new_version_text: str


class ContractComparisonOutput(BaseModel):
    """合同比对任务输出模型，对齐 Coze 文档结构。"""
    output: dict[str, Any]


@coze预留_router.post("/contract/comparison", response_model=ContractComparisonOutput)
async def analyze_contract_comparison(input_data: ContractComparisonInput) -> ContractComparisonOutput:
    """
    合同版本比对语义增强接口。

    输入字段：old_version_text, new_version_text。
    输出字段：output.diff_list, output.stats, output.summary。
    """
    try:
        coze_service = get_coze_service()
        parameters = build_comparison_workflow_input(
            input_data.old_version_text,
            input_data.new_version_text,
        )
        result = await coze_service.call_workflow(coze_service.comparison_workflow_id, parameters)
        normalized = normalize_comparison_workflow_result(result)
        raw_output = normalized.get("raw_output", {})
        return ContractComparisonOutput(output=raw_output.get("output", {}))

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
