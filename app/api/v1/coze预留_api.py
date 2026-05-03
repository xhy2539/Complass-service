"""Coze AI 能力预留接口，供后续 AI 工程师接入真实 Coze 工作流。

当前为 Mock 模式，接口结构已对齐 Coze API 规范。
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.coze_service import CozeServiceError, get_coze_service

coze预留_router = APIRouter(prefix="/coze", tags=["Coze AI 能力（预留）"])


class ContractComparisonInput(BaseModel):
    """合同比对任务输入模型。"""
    task_type: str = "contract_comparison"
    old_text: str
    new_text: str
    diff_stats: dict[str, int]
    diff_count: int
    diff_texts: list[dict[str, Any]]


class ContractComparisonOutput(BaseModel):
    """合同比对任务输出模型。"""
    success: bool
    enhanced: list[dict[str, Any]]
    total_risks: int
    message: str = ""


@coze预留_router.post("/contract/comparison", response_model=ContractComparisonOutput)
async def analyze_contract_comparison(input_data: ContractComparisonInput) -> ContractComparisonOutput:
    """
    合同版本比对语义增强接口。

    供 AI 工程师接入真实 Coze 工作流使用。

    输入：
        - old_text / new_text: 双版本合同全文
        - diff_stats: 差异统计
        - diff_texts: 差异内容列表 (Object Array)

    输出：
        - enhanced: 每条差异的语义增强结果
        - total_risks: 风险数量统计

    ---
    Coze 工作流需实现：
        输入变量：task_type, old_text, new_text, diff_stats, diff_count, diff_texts
        输出变量：enhanced (JSON Array), total_risks (Number)
    ---
    """
    try:
        coze_service = get_coze_service()

        result = await coze_service.call_workflow({
            "task_type": input_data.task_type,
            "old_text": input_data.old_text,
            "new_text": input_data.new_text,
            "diff_stats": input_data.diff_stats,
            "diff_count": input_data.diff_count,
            "diff_texts": input_data.diff_texts
        })

        return ContractComparisonOutput(
            success=True,
            enhanced=result.get("enhanced", []),
            total_risks=result.get("total_risks", 0),
            message="Coze 分析完成"
        )

    except CozeServiceError as e:
        raise HTTPException(status_code=502, detail=f"Coze 服务调用失败: {e}")


class SingleContractAnalysisInput(BaseModel):
    """单合同审查任务输入模型。"""
    task_type: str = "contract_review"
    file_name: str
    file_type: str
    text: str
    char_count: int
    paragraph_count: int


class SingleContractAnalysisOutput(BaseModel):
    """单合同审查任务输出模型。"""
    success: bool
    overall_conclusion: str
    risk_summary: dict[str, int]  # {"high": 0, "medium": 0, "low": 0}
    risk_points: list[dict[str, Any]]
    suggest_deep_review: bool
    message: str = ""


@coze预留_router.post("/contract/review", response_model=SingleContractAnalysisOutput)
async def analyze_single_contract(input_data: SingleContractAnalysisInput) -> SingleContractAnalysisOutput:
    """
    单合同 AI 风险分析接口。

    供 AI 工程师接入真实 Coze 工作流使用。

    输入：
        - file_name: 文件名
        - file_type: 文件类型
        - text: 合同全文
        - char_count: 字符数
        - paragraph_count: 段落数

    输出：
        - overall_conclusion: 总体结论
        - risk_summary: 风险统计
        - risk_points: 风险点列表
        - suggest_deep_review: 是否建议进入深审

    ---
    Coze 工作流需实现：
        输入变量：task_type, file_name, file_type, text, char_count, paragraph_count
        输出变量：overall_conclusion, risk_summary, risk_points, suggest_deep_review
    ---
    """
    # 当前为 Mock 实现，待 AI 工程师接入真实 Coze 工作流
    mock_response = {
        "success": True,
        "overall_conclusion": "合同风险较低，未发现明显异常条款",
        "risk_summary": {"high": 0, "medium": 1, "low": 2},
        "risk_points": [
            {
                "title": "付款条款待明确",
                "level": "medium",
                "reason": "合同中未明确约定具体付款时间和方式",
                "suggestion": "建议补充付款条款明细",
                "position": None
            },
            {
                "title": "合同格式规范",
                "level": "low",
                "reason": "合同结构完整，条款清晰",
                "suggestion": "可直接使用",
                "position": None
            }
        ],
        "suggest_deep_review": False,
        "message": "当前为 Mock 模式，请联系 AI 工程师接入真实 Coze 工作流"
    }

    return SingleContractAnalysisOutput(**mock_response)


class TextStructureInput(BaseModel):
    """文本结构分析输入模型。"""
    task_type: str = "text_structure_analysis"
    file_name: str
    file_type: str
    text: str  # 原始或初步解析的纯文本
    existing_paragraphs: list[dict]  # 后端初步划分的段落，用于参考
    char_count: int


class TextStructureOutput(BaseModel):
    """文本结构分析输出模型。"""
    success: bool
    structured_paragraphs: list[dict]  # 结构化段落列表
    paragraph_count: int
    sentence_count: int
    key_clauses: list[str]  # 识别出的关键条款
    message: str = ""


class RiskLocationInput(BaseModel):
    """风险点位置定位输入模型。"""
    task_type: str = "risk_location"
    risk_title: str  # 风险标题
    risk_reason: str  # 风险原因
    risk_suggestion: str  # 建议处理
    text: str  # 合同全文（脱敏后）
    paragraphs: list[dict]  # 段落列表，每项包含 text, char_offset_start, char_offset_end, page_number
    char_count: int  # 字符总数
    current_location: Optional[dict] = None  # 后端算法得出的当前位置（参考）


class RiskLocationOutput(BaseModel):
    """风险点位置定位输出模型。"""
    success: bool
    matched_paragraph_index: int  # 匹配段落索引
    char_offset_start: int  # 字符起始位置
    char_offset_end: int  # 字符结束位置
    matched_text: str  # 匹配的原文片段
    confidence: float  # 置信度 0-1
    reasoning: str  # 匹配理由
    message: str = ""


@coze预留_router.post("/risk/locate", response_model=RiskLocationOutput)
async def locate_risk_position(input_data: RiskLocationInput) -> RiskLocationOutput:
    """
    风险点位置定位接口。

    当后端基于规则的位置匹配算法效果不好时，调用此接口让 Coze 帮助定位风险点在原文中的位置。

    输入：
        - risk_title: 风险标题
        - risk_reason: 风险原因
        - risk_suggestion: 建议处理方式
        - text: 合同全文（脱敏后）
        - paragraphs: 段落列表（包含位置信息）
        - char_count: 字符总数
        - current_location: 后端算法得出的当前位置（可选，供 Coze 参考）

    输出：
        - matched_paragraph_index: 匹配段落索引
        - char_offset_start: 字符起始位置
        - char_offset_end: 字符结束位置
        - matched_text: 匹配的原文片段
        - confidence: 置信度 0-1
        - reasoning: 匹配理由

    ---
    Coze 工作流需实现：
        输入变量：task_type, risk_title, risk_reason, risk_suggestion, text, paragraphs, char_count, current_location
        输出变量：matched_paragraph_index, char_offset_start, char_offset_end, matched_text, confidence, reasoning
    ---
    """
    # 当前为 Mock 实现
    # 简单模拟：从 paragraphs 中找到包含 risk_title 或 risk_reason 关键词的段落
    paragraphs = input_data.paragraphs or []

    best_match = None
    best_score = 0

    for idx, para in enumerate(paragraphs):
        para_text = para.get("text", "")
        score = 0

        # 标题关键词匹配
        if input_data.risk_title and any(kw in para_text for kw in input_data.risk_title.split() if len(kw) >= 2):
            score += 3

        # 原因关键词匹配
        if input_data.risk_reason and any(kw in para_text for kw in input_data.risk_reason.split() if len(kw) >= 2):
            score += 2

        # 建议关键词匹配
        if input_data.risk_suggestion and any(kw in para_text for kw in input_data.risk_suggestion.split() if len(kw) >= 2):
            score += 1

        if score > best_score:
            best_score = score
            best_match = para
            best_match_index = idx

    if best_match and best_score > 0:
        return RiskLocationOutput(
            success=True,
            matched_paragraph_index=best_match_index,
            char_offset_start=best_match.get("char_offset_start", 0),
            char_offset_end=best_match.get("char_offset_end", 0),
            matched_text=best_match.get("text", ""),
            confidence=min(best_score / 5.0, 1.0),  # 归一化到 0-1
            reasoning=f"通过关键词匹配找到相关段落，匹配得分: {best_score}",
            message="当前为 Mock 模式，请联系 AI 工程师接入真实 Coze 工作流"
        )

    # 未找到匹配
    if paragraphs:
        fallback_para = paragraphs[len(paragraphs) // 2]
        return RiskLocationOutput(
            success=True,
            matched_paragraph_index=len(paragraphs) // 2,
            char_offset_start=fallback_para.get("char_offset_start", 0),
            char_offset_end=fallback_para.get("char_offset_end", 0),
            matched_text=fallback_para.get("text", ""),
            confidence=0.1,
            reasoning="未找到明确匹配段落，使用中间段落作为回退",
            message="当前为 Mock 模式，请联系 AI 工程师接入真实 Coze 工作流"
        )

    return RiskLocationOutput(
        success=False,
        matched_paragraph_index=0,
        char_offset_start=0,
        char_offset_end=0,
        matched_text="",
        confidence=0.0,
        reasoning="无法定位风险点位置，段落列表为空",
        message="当前为 Mock 模式，请联系 AI 工程师接入真实 Coze 工作流"
    )


@coze预留_router.post("/text/structure", response_model=TextStructureOutput)
async def analyze_text_structure(input_data: TextStructureInput) -> TextStructureOutput:
    """
    文本结构分析接口。

    用于改进合同文本的段落划分和句子拆分。
    当后端解析的段落过碎时，可调用此接口让 Coze 重新组织文本结构。

    输入：
        - file_name: 文件名
        - file_type: 文件类型
        - text: 合同全文（脱敏后）
        - existing_paragraphs: 后端初步划分的段落（可参考或忽略）
        - char_count: 字符数

    输出：
        - structured_paragraphs: 结构化后的段落列表，每项包含：
            - text: 段落文本
            - index: 段落索引
            - paragraph_type: 段落类型 (heading1/heading2/heading3/body)
            - paragraph_level: 标题层级 (0=正文, 1-3=标题层级)
            - is_key_clause: 是否关键条款
            - sentence_count: 句数
        - paragraph_count: 段落总数
        - sentence_count: 句子总数
        - key_clauses: 关键条款文本列表

    ---
    Coze 工作流需实现：
        输入变量：task_type, file_name, file_type, text, existing_paragraphs, char_count
        输出变量：structured_paragraphs (JSON Array), paragraph_count, sentence_count, key_clauses (JSON Array)
    ---
    """
    # 当前为 Mock 实现，直接使用后端初步划分的段落
    # 真实 Coze 实现可以重新组织段落结构、合并过碎的段落
    paragraphs = input_data.existing_paragraphs or []
    paragraph_count = len(paragraphs) if paragraphs else 1
    sentence_count = sum(1 for p in paragraphs for s in p.get("sentences", []))

    # 从 existing_paragraphs 中提取段落类型信息
    # 如果后端传的是 Paragraph dataclass 转换的 dict，会有 paragraph_type 字段
    structured_paragraphs = []
    for p in paragraphs[:50]:  # 限制数量
        para_dict = {
            "text": p.get("text", "")[:500],  # 限制单段长度
            "index": p.get("index", len(structured_paragraphs)),
            "paragraph_type": p.get("paragraph_type", "body"),
            "paragraph_level": p.get("paragraph_level", 0),
            "is_key_clause": p.get("is_key_clause", False),
            "sentence_count": len(p.get("sentences", [])) if p.get("sentences") else 0
        }
        structured_paragraphs.append(para_dict)

    # 提取关键条款
    key_clauses = [p["text"] for p in structured_paragraphs if p.get("is_key_clause")]

    mock_response = {
        "success": True,
        "structured_paragraphs": structured_paragraphs,
        "paragraph_count": paragraph_count,
        "sentence_count": sentence_count,
        "key_clauses": key_clauses,
        "message": "当前为 Mock 模式，文本结构分析接口预留完成"
    }

    return TextStructureOutput(**mock_response)