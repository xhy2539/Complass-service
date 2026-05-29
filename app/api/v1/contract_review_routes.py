"""单合同审查路由，提供文件上传、任务创建、解析和风险分析接口。"""

import logging
import re
import uuid
from datetime import datetime
from typing import Annotated
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.api.v1.auth import get_current_user
from app.models.database import Paragraph
from app.models.database import ReviewTask
from app.models.database import RiskLevel
from app.models.database import RiskPoint
from app.models.database import RiskStatus
from app.models.database import Sentence
from app.models.database import TaskStatus
from app.models.database import User
from app.models.database_connection import get_db
from app.schemas.review import ReviewExportRequest
from app.schemas.review import ReviewRiskListResponse
from app.schemas.review import ReviewTaskCreateResponse
from app.schemas.review import ReviewTaskListResponse
from app.schemas.review import ReviewTaskQueryResponse
from app.schemas.review import ReviewTaskSchema
from app.schemas.review import RiskPointSchema
from app.schemas.review import RiskStatsSchema
from app.services.document_exporter import DocumentExporter
from app.services.document_parser import DocumentParseError
from app.services.document_parser import DocumentParser
from app.services.rule_service import build_enabled_rules_snapshot
from app.services.rule_service import find_rule_snapshot
from app.services.sanitization_service import restore_text_from_mapping
from app.services.sanitization_service import sanitize_contract_text
from app.services.sanitization_service import sanitize_docx_bytes

logger = logging.getLogger(__name__)

contract_review_router = APIRouter(tags=["合同审查"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _uuid() -> str:
    """生成 UUID。"""
    return str(uuid.uuid4())


def validate_file(file: UploadFile) -> None:
    """验证文件是否有效。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    if not DocumentParser.is_supported(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，仅支持: {', '.join(DocumentParser.SUPPORTED_EXTENSIONS)}",
        )


def compute_text_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度（基于字符集合的 Jaccard 相似度）。

    Args:
        text1: 文本1
        text2: 文本2

    Returns:
        相似度 0.0 ~ 1.0
    """
    if not text1 or not text2:
        return 0.0

    # 清理文本：去除标点、特殊字符，只保留中文、字母、数字
    clean_text1 = re.sub(r"[^\w\u4e00-\u9fff]", "", text1.lower())
    clean_text2 = re.sub(r"[^\w\u4e00-\u9fff]", "", text2.lower())

    if not clean_text1 or not clean_text2:
        return 0.0

    set1 = set(clean_text1)
    set2 = set(clean_text2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0


def extract_keywords(text: str, max_count: int = 5) -> list[str]:
    """
    从文本中提取关键词。

    Args:
        text: 输入文本
        max_count: 最大关键词数量

    Returns:
        关键词列表
    """
    # 去除常见停用词
    stop_words = {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
        "那",
        "它",
        "他",
        "她",
        "们",
        "这个",
        "那个",
        "什么",
        "怎么",
        "为什么",
        "如果",
        "因为",
        "所以",
        "但是",
        "而且",
        "或者",
        "以及",
    }

    # 按标点和空格分割
    words = re.split(r'[，。！？；：、""' "（）]", text)
    words = [w.strip() for w in words if w.strip()]

    # 过滤停用词和过短的词
    keywords = [w for w in words if w and len(w) >= 2 and w not in stop_words]

    # 返回前 max_count 个
    return keywords[:max_count]


def find_best_sentence_match(
    evidence: str, sentences_info: dict[int, dict]
) -> Optional[dict]:
    """
    查找与风险点证据最匹配的句子。

    Args:
        evidence: Coze返回的原文/证据
        sentences_info: 句子信息字典 {index: {text, id, ...}}

    Returns:
        匹配的句子信息 {id, text, ...} 或 None
    """
    if not evidence or not sentences_info:
        return None

    best_match = None
    best_score = 0.0

    # 策略1：精确包含匹配
    for idx, sent_info in sentences_info.items():
        sent_text = sent_info["text"]
        if evidence in sent_text or sent_text in evidence:
            # 如果完全包含，分数很高
            score = 2.0 if len(evidence) <= len(sent_text) else 1.5
            if score > best_score:
                best_score = score
                best_match = sent_info

    if best_score >= 1.0:
        return best_match

    # 策略2：关键词匹配
    keywords = extract_keywords(evidence)
    for idx, sent_info in sentences_info.items():
        sent_text = sent_info["text"]
        match_count = sum(1 for kw in keywords if kw in sent_text)
        if match_count > best_score:
            best_score = match_count
            best_match = sent_info

    if best_score >= 1.0:
        return best_match

    # 策略3：相似度匹配
    best_similarity = 0.0
    similarity_match = None

    for idx, sent_info in sentences_info.items():
        sim = compute_text_similarity(evidence, sent_info["text"])
        if sim > best_similarity:
            best_similarity = sim
            similarity_match = sent_info

    if best_similarity >= 0.3 and best_similarity > best_score:
        return similarity_match

    return best_match if best_match else None


def find_best_paragraph_match(
    title: str, reason: str, paragraphs_info: dict[int, dict]
) -> tuple[Optional[dict], Optional[str]]:
    """
    查找与风险点最匹配的段落。

    使用多策略匹配：
    1. 关键词精确匹配
    2. 文本相似度匹配
    3. 回退策略：取风险点对应段落位置

    Args:
        title: 风险标题
        reason: 风险原因
        paragraphs_info: 段落信息字典 {index: {text, char_offset_start, ...}}

    Returns:
        (position, original_text) 或 (None, None)
    """
    search_text = f"{title} {reason}"
    keywords = extract_keywords(search_text)

    best_match = None
    best_score = 0.0
    matched_idx = None

    # 策略1：关键词精确匹配
    for idx, para_info in paragraphs_info.items():
        para_text = para_info["text"]
        match_count = sum(1 for kw in keywords if kw in para_text)

        if match_count > best_score:
            best_score = match_count
            best_match = para_info
            matched_idx = idx
            # 如果关键词精确命中，分数更高
            if any(kw == para_text[: len(kw)] for kw in keywords if len(kw) >= 4):
                best_score += 0.5

    # 如果关键词匹配分数足够高，直接返回
    if best_score >= 1.0:
        return {
            "paragraph_index": matched_idx,
            "char_offset_start": best_match["char_offset_start"],
            "char_offset_end": best_match["char_offset_end"],
            "match_strategy": "keyword",
        }, best_match["text"]

    # 策略2：文本相似度匹配
    # 取 title 和 reason 中最长的句子作为匹配目标
    target_text = title if len(title) > len(reason) else reason
    if not target_text.strip():
        target_text = reason

    best_similarity = 0.0
    similarity_match = None
    similarity_idx = None

    for idx, para_info in paragraphs_info.items():
        # 计算与段落的相似度
        sim_title = compute_text_similarity(target_text, para_info["text"])
        sim_reason = (
            compute_text_similarity(reason[:50], para_info["text"])
            if len(reason) > 50
            else compute_text_similarity(reason, para_info["text"])
        )

        # 取两个相似度的最大值
        max_sim = max(sim_title, sim_reason)

        if max_sim > best_similarity:
            best_similarity = max_sim
            similarity_match = para_info
            similarity_idx = idx

    # 如果相似度超过阈值（0.3），使用相似度匹配结果
    if best_similarity >= 0.3 and best_similarity > best_score:
        return {
            "paragraph_index": similarity_idx,
            "char_offset_start": similarity_match["char_offset_start"],
            "char_offset_end": similarity_match["char_offset_end"],
            "match_strategy": "similarity",
            "similarity_score": round(best_similarity, 2),
        }, similarity_match["text"]

    # 策略3：回退策略
    # 如果以上策略都没找到好的匹配，取中间位置的段落
    if paragraphs_info:
        para_indices = sorted(paragraphs_info.keys())
        mid_idx = len(para_indices) // 2
        fallback_idx = para_indices[mid_idx]
        fallback_para = paragraphs_info[fallback_idx]

        return {
            "paragraph_index": fallback_idx,
            "char_offset_start": fallback_para["char_offset_start"],
            "char_offset_end": fallback_para["char_offset_end"],
            "match_strategy": "fallback",
        }, fallback_para["text"]

    return None, None


@contract_review_router.post("/reviews", response_model=ReviewTaskCreateResponse)
async def create_review_task(
    file: Annotated[UploadFile, File(description="合同文件，支持 docx/pdf/txt")],
    use_coze: bool = True,
    contract_type: str = "通用",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewTaskCreateResponse:
    """
    创建单合同审查任务。

    流程：上传文件 → 创建任务 → 解析 → Coze分析（如启用）→ 保存结果
    返回 task_id 供后续查询。
    """
    validate_file(file)

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10MB 限制")

    # 解析文档
    try:
        parse_result = DocumentParser.parse(content, file.filename)
    except DocumentParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    logger.info(
        f"[Review] 文件解析完成: {file.filename}, 段落数={len(parse_result.paragraphs)}, 句子数={len(parse_result.sentences)}"
    )

    sanitization = sanitize_contract_text(parse_result.text)
    if sanitization.errors:
        raise HTTPException(status_code=422, detail="; ".join(sanitization.errors))

    rule_version = None
    rules_snapshot: list[dict] = []
    if use_coze:
        try:
            rule_version, rules_snapshot = build_enabled_rules_snapshot(
                db, contract_type
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not rules_snapshot:
            raise HTTPException(
                status_code=400, detail="当前合同类型没有可用的启用规则"
            )

    # 创建审查任务
    task_id = _uuid()
    task = ReviewTask(
        id=task_id,
        user_id=current_user.id,
        file_name=parse_result.file_name,
        file_type=parse_result.file_type,
        file_size=len(content),
        text=parse_result.text,
        char_count=parse_result.char_count,
        page_count=parse_result.page_count,
        paragraph_count=len(parse_result.paragraphs),
        sentence_count=len(parse_result.sentences),
        sanitized_text=sanitization.sanitized_text,
        sanitization_mapping_json=sanitization.mappings,
        sanitization_status="completed",
        rule_version_id=rule_version.id if rule_version else None,
        rules_snapshot_json=rules_snapshot,
        contract_type=contract_type,
        paragraphs_json=[p.__dict__ for p in parse_result.paragraphs],
        sentences_json=parse_result.sentences,
        position_info_json={
            "paragraphs": [
                {
                    "index": p.index,
                    "text": p.text,
                    "char_offset_start": p.char_offset_start,
                    "char_offset_end": p.char_offset_end,
                    "page_number": p.page_number,
                    "is_key_clause": p.is_key_clause,
                }
                for p in parse_result.paragraphs
            ],
            "sentences": parse_result.sentences,
        },
        comparison_data_json={
            "sentences": parse_result.sentences,
            "key_clauses": [p.text for p in parse_result.paragraphs if p.is_key_clause],
        },
        status=TaskStatus.PROCESSING,
    )

    db.add(task)

    # 创建段落记录
    for p in parse_result.paragraphs:
        paragraph = Paragraph(
            id=_uuid(),
            review_task_id=task_id,
            index=p.index,
            text=p.text,
            char_offset_start=p.char_offset_start,
            char_offset_end=p.char_offset_end,
            page_number=p.page_number,
            is_key_clause=p.is_key_clause,
            paragraph_type=p.paragraph_type,
            paragraph_level=p.paragraph_level,
        )
        db.add(paragraph)

    # 创建句子记录
    sentences_info = {}
    for idx, s in enumerate(parse_result.sentences):
        sentence_id = _uuid()
        sentence = Sentence(
            id=sentence_id,
            review_task_id=task_id,
            index=idx,
            text=s.get("text", ""),
            char_offset_start=s.get("char_offset_start"),
            char_offset_end=s.get("char_offset_end"),
            paragraph_index=s.get("paragraph_index"),
        )
        db.add(sentence)
        sentences_info[idx] = {"text": s.get("text", ""), "id": sentence_id}

    # 立即 flush，确保句子写入数据库，获取真实 ID
    db.flush()

    # 构建段落信息（用于风险点定位）
    paragraphs_info = {
        p.index: {
            "text": p.text,
            "char_offset_start": p.char_offset_start,
            "char_offset_end": p.char_offset_end,
            "page_number": p.page_number,
        }
        for p in parse_result.paragraphs
    }

    # 如果启用 Coze，分析风险
    if use_coze:
        if (
            current_user.token_quota > 0
            and current_user.token_used >= current_user.token_quota
        ):
            raise HTTPException(
                status_code=402, detail="Token 配额已用完，请联系管理员升级"
            )

        try:
            from app.services.coze_service import get_coze_service

            coze_service = get_coze_service()
            sanitized_docx = sanitize_docx_bytes(content, sanitization.mappings)
            coze_result, usage = await coze_service.review_contract_file(
                content=sanitized_docx,
                filename=parse_result.file_name,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                rules=rules_snapshot,
                rule_version_id=rule_version.id if rule_version else None,
                contract_type=contract_type,
                sanitized_text=sanitization.sanitized_text,
            )

            # 更新任务结果
            task.overall_conclusion = coze_result.get("overall_conclusion", "")
            task.risk_summary = coze_result.get(
                "risk_summary", {"high": 0, "medium": 0, "low": 0}
            )
            task.suggest_deep_review = coze_result.get("suggest_deep_review", False)
            task.coze_message = coze_result.get("message", "")
            task.token_cost = usage.get("token_count", 0)
            current_user.token_used = current_user.token_used + usage.get(
                "token_count", 0
            )
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()

            # 创建风险点记录
            risk_points_data = coze_result.get("risk_points", [])
            logger.info(f"[Review] Coze返回风险点数: {len(risk_points_data)}")

            for rp_data in risk_points_data:
                rule_code = rp_data.get("rule_code") or rp_data.get("rule_id")
                evidence = restore_text_from_mapping(
                    rp_data.get("evidence") or "", sanitization.mappings
                )
                reason = restore_text_from_mapping(
                    rp_data.get("reason") or "", sanitization.mappings
                )
                suggestion = restore_text_from_mapping(
                    rp_data.get("suggestion") or "", sanitization.mappings
                )

                # 使用改进的匹配算法定位风险点
                position, original_text = find_best_paragraph_match(
                    title=rp_data.get("title", ""),
                    reason=reason,
                    paragraphs_info=paragraphs_info,
                )

                # 查找最匹配的句子
                matched_sentence = find_best_sentence_match(
                    evidence=evidence, sentences_info=sentences_info
                )

                risk_point = RiskPoint(
                    id=_uuid(),
                    review_task_id=task_id,
                    title=rp_data.get("title", ""),
                    level=RiskLevel(rp_data.get("level", "medium")),
                    reason=reason,
                    evidence=evidence,
                    impact=restore_text_from_mapping(
                        rp_data.get("impact") or "", sanitization.mappings
                    ),
                    suggestion=suggestion,
                    replace_text=restore_text_from_mapping(
                        rp_data.get("replace_text") or "", sanitization.mappings
                    ),
                    rule_code=rule_code,
                    rule_snapshot_json=find_rule_snapshot(rules_snapshot, rule_code),
                    position=position,
                    sentence_id=matched_sentence["id"] if matched_sentence else None,
                    status=RiskStatus.PENDING,
                    source="coze",
                )
                db.add(risk_point)

        except Exception as e:
            # Coze 调用失败，任务标记为完成但无 AI 结果
            task.coze_message = f"AI 分析失败: {e}"
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()

    db.commit()

    return ReviewTaskCreateResponse(task_id=task_id, message="审查任务创建成功")


@contract_review_router.get(
    "/reviews/{task_id}", response_model=ReviewTaskQueryResponse
)
async def get_review_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewTaskQueryResponse:
    """查询审查任务详情，包括风险点列表。"""
    task = (
        db.query(ReviewTask)
        .filter(ReviewTask.id == task_id, ReviewTask.user_id == current_user.id)
        .first()
    )

    if not task:
        raise HTTPException(
            status_code=404, detail=f"审查任务 {task_id} 不存在或无权访问"
        )

    # 获取风险点（预加载 sentence 关系）
    risk_points = (
        db.query(RiskPoint)
        .options(joinedload(RiskPoint.sentence))
        .filter(RiskPoint.review_task_id == task_id)
        .all()
    )

    return ReviewTaskQueryResponse(
        task=ReviewTaskSchema.model_validate(task.to_dict()),
        risk_points=[
            RiskPointSchema.model_validate(rp.to_dict()) for rp in risk_points
        ],
        message="查询成功",
    )


@contract_review_router.get("/reviews", response_model=ReviewTaskListResponse)
async def list_review_tasks(
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewTaskListResponse:
    """查询当前用户的审查任务列表（支持分页和状态筛选）。"""
    query = db.query(ReviewTask).filter(ReviewTask.user_id == current_user.id)

    if status:
        try:
            status_enum = TaskStatus(status)
            query = query.filter(ReviewTask.status == status_enum)
        except ValueError:
            pass

    total = query.count()
    tasks = query.order_by(ReviewTask.created_at.desc()).offset(skip).limit(limit).all()

    return ReviewTaskListResponse(
        tasks=[ReviewTaskSchema.model_validate(t.to_dict()) for t in tasks],
        total=total,
        skip=skip,
        limit=limit,
    )


@contract_review_router.get(
    "/reviews/{task_id}/risks", response_model=ReviewRiskListResponse
)
async def get_review_task_risks(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewRiskListResponse:
    """查询指定审查任务的风险点列表。"""
    task = (
        db.query(ReviewTask)
        .filter(ReviewTask.id == task_id, ReviewTask.user_id == current_user.id)
        .first()
    )

    if not task:
        raise HTTPException(
            status_code=404, detail=f"审查任务 {task_id} 不存在或无权访问"
        )

    risk_points = (
        db.query(RiskPoint)
        .options(joinedload(RiskPoint.sentence))
        .filter(RiskPoint.review_task_id == task_id)
        .all()
    )

    total = len(risk_points)
    pending = sum(1 for rp in risk_points if rp.status == RiskStatus.PENDING)
    confirmed = sum(1 for rp in risk_points if rp.status == RiskStatus.CONFIRMED)
    ignored = sum(1 for rp in risk_points if rp.status == RiskStatus.IGNORED)

    return ReviewRiskListResponse(
        task_id=task_id,
        risk_points=[
            RiskPointSchema.model_validate(rp.to_dict()) for rp in risk_points
        ],
        total=total,
        risk_stats=RiskStatsSchema(
            total=total, pending=pending, confirmed=confirmed, ignored=ignored
        ),
    )


@contract_review_router.post("/reviews/{task_id}/export")
async def export_review_document(
    task_id: str,
    request: ReviewExportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    导出用户修改后的合同文档（清洁版 docx）。

    前端发送用户编辑后的完整合同文本，后端生成格式化 docx 文件返回。
    """
    # 验证任务存在且属于当前用户
    task = (
        db.query(ReviewTask)
        .filter(ReviewTask.id == task_id, ReviewTask.user_id == current_user.id)
        .first()
    )

    if not task:
        raise HTTPException(
            status_code=404, detail=f"审查任务 {task_id} 不存在或无权访问"
        )

    # 生成文件名
    original_name = task.file_name
    base_name = original_name.rsplit(".", 1)[0] if original_name else "合同"
    export_file_name = request.file_name or f"{base_name}_修改版.docx"

    # 导出为 docx
    docx_buffer = DocumentExporter.export_text_to_docx(
        text=request.final_text, file_name=export_file_name, title=base_name
    )

    # 返回文件流
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse

    # URL 编码文件名（处理中文）
    encoded_filename = quote(export_file_name)
    return StreamingResponse(
        docx_buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )
