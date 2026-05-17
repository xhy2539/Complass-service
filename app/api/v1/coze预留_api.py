"""Coze AI 能力预留接口，按已发布工作流格式提供联调入口。"""

from typing import Annotated, Any, Optional

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
    """合同比对任务输入模型，对齐 Coze 文档格式。"""
    task_type: str = "contract_comparison"
    old_text: str = """技术服务合同

合同编号：JSFW-2024-001

甲方（委托方）：北京创新科技有限公司
统一社会信用代码：91110108MA01XXXXXX
法定代表人：张明
地址：北京市海淀区中关村大街1号科技大厦15层
联系电话：010-88888888

乙方（受托方）：上海智慧云信息技术有限公司
统一社会信用代码：91310115MA02XXXXXX
法定代表人：李华
地址：上海市浦东新区张江高科技园区科苑路88号
联系电话：021-66666666

鉴于甲方拟委托乙方提供软件开发及维护服务，双方本着平等互利、诚实信用的原则，经友好协商，达成如下协议：

第一条 服务内容
1.1 乙方为甲方开发"智慧供应链管理系统"（以下简称"系统"），包括但不限于以下模块：采购管理、库存管理、物流追踪、数据分析。
1.2 乙方应在合同签订后30个自然日内完成系统开发并交付甲方验收。
1.3 系统开发完成后，乙方提供为期一年的免费维护服务，自验收合格之日起计算。

第二条 合同价款及支付方式
2.1 本合同总金额为人民币伍拾万元整（¥500,000.00），该价格为含税价，包含开发费用、测试费用及首年维护费用。
2.2 付款方式：
    （1）合同签订后5个工作日内，甲方向乙方支付合同总金额的30%，即人民币壹拾伍万元整（¥150,000.00）作为预付款；
    （2）系统开发完成并经甲方初步验收合格后，甲方向乙方支付合同总金额的50%，即人民币贰拾伍万元整（¥250,000.00）；
    （3）系统上线稳定运行满三个月后，甲方向乙方支付合同总金额的20%，即人民币壹拾万元整（¥100,000.00）。
2.3 乙方应在收到每笔款项后向甲方开具等额的增值税专用发票。

第三条 知识产权
3.1 系统开发完成后，乙方将系统的全部源代码及相关文档交付甲方，甲方享有系统的全部知识产权。
3.2 乙方保证所开发的系统不侵犯任何第三方的知识产权，如因系统侵犯第三方知识产权导致甲方遭受损失的，乙方应承担全部赔偿责任。

第四条 保密条款
4.1 双方应对在合同履行过程中知悉的对方商业秘密予以保密，未经对方书面同意，不得向任何第三方披露。
4.2 保密期限为合同终止后两年。

第五条 违约责任
5.1 如乙方未能在约定时间内完成系统开发，每逾期一日，应向甲方支付合同总金额千分之三的违约金。
5.2 如甲方未按约定时间支付款项，每逾期一日，应向乙方支付应付款项千分之三的违约金。
5.3 任何一方违约给对方造成损失的，违约方应赔偿对方的全部损失。

第六条 争议解决
6.1 本合同在履行过程中如发生争议，双方应友好协商解决；协商不成的，任何一方均可向合同签订地人民法院提起诉讼。

第七条 其他
7.1 本合同自双方签字盖章之日起生效，有效期为两年。
7.2 本合同一式两份，甲乙双方各执一份，具有同等法律效力。
7.3 本合同未尽事宜，双方可另行签订补充协议，补充协议与本合同具有同等法律效力。

甲方（盖章）：北京创新科技有限公司          乙方（盖章）：上海智慧云信息技术有限公司
法定代表人或授权代表（签字）：__________     法定代表人或授权代表（签字）：__________
签订日期：2024年1月15日                    签订日期：2024年1月15日
签订地点：北京市海淀区"""
    new_text: str = """技术服务合同

合同编号：JSFW-2024-001

甲方（委托方）：北京创新科技有限公司
统一社会信用代码：91110108MA01XXXXXX
法定代表人：张明
地址：北京市海淀区中关村大街1号科技大厦15层
联系电话：010-88888888

乙方（受托方）：上海智慧云信息技术有限公司
统一社会信用代码：91310115MA02XXXXXX
法定代表人：李华
地址：上海市浦东新区张江高科技园区科苑路88号
联系电话：021-66666666

鉴于甲方拟委托乙方提供软件开发及维护服务，双方本着平等互利、诚实信用的原则，经友好协商，达成如下协议：

第一条 服务内容
1.1 乙方为甲方开发"智慧供应链管理系统"（以下简称"系统"），包括但不限于以下模块：采购管理、库存管理、物流追踪、数据分析。
1.2 乙方应在合同签订后60个工作日内完成系统开发并交付甲方验收，具体交付时间以乙方实际排期为准。
1.3 系统开发完成后，乙方提供为期六个月的免费维护服务，自验收合格之日起计算。维护期满后，甲方如需继续维护，应与乙方另行签订维护协议，维护费用另行协商。

第二条 合同价款及支付方式
2.1 本合同总金额为人民币伍拾万元整（¥500,000.00），该价格为含税价，包含开发费用、测试费用及首年维护费用。
2.2 付款方式：
    （1）合同签订后3个工作日内，甲方向乙方支付合同总金额的50%，即人民币贰拾伍万元整（¥250,000.00）作为预付款；
    （2）系统开发完成并经甲方初步验收合格后，甲方向乙方支付合同总金额的40%，即人民币贰拾万元整（¥200,000.00）；
    （3）系统上线稳定运行满六个月后，甲方向乙方支付合同总金额的10%，即人民币伍万元整（¥50,000.00）。
2.3 乙方应在收到全部款项后向甲方开具总金额为人民币伍拾万元整的增值税专用发票。

第三条 知识产权
3.1 系统开发完成后，乙方将系统的可执行程序及相关文档交付甲方，甲方享有系统的使用权。系统的源代码及相关技术文档归乙方所有，乙方有权在后续项目中复用相关技术成果。
3.2 乙方保证所开发的系统不侵犯任何第三方的知识产权，如因系统侵犯第三方知识产权导致甲方遭受损失的，乙方承担的赔偿责任以本合同总金额为限。

第四条 保密条款
4.1 双方应对在合同履行过程中知悉的对方商业秘密予以保密，未经对方书面同意，不得向任何第三方披露。
4.2 保密期限为合同终止后六个月。

第五条 违约责任
5.1 如乙方未能在约定时间内完成系统开发，每逾期一日，应向甲方支付合同总金额万分之五的违约金。
5.2 如甲方未按约定时间支付款项，每逾期一日，应向乙方支付应付款项千分之五的违约金。
5.3 任何一方违约给对方造成损失的，违约方应赔偿对方的直接经济损失，间接损失、预期利益损失不予赔偿。

第六条 争议解决
6.1 本合同在履行过程中如发生争议，双方应友好协商解决；协商不成的，任何一方均可向乙方所在地人民法院提起诉讼。

第七条 其他
7.1 本合同自双方签字盖章之日起生效，有效期为一年。
7.2 本合同一式两份，甲乙双方各执一份，具有同等法律效力。
7.3 本合同未尽事宜，双方可另行签订补充协议，补充协议与本合同具有同等法律效力。
7.4 本合同的最终解释权归乙方所有。

甲方（盖章）：北京创新科技有限公司          乙方（盖章）：上海智慧云信息技术有限公司
法定代表人或授权代表（签字）：__________     法定代表人或授权代表（签字）：__________
签订日期：2024年1月15日                    签订日期：2024年1月15日
签订地点：北京市海淀区"""


class EnhancedItemSchema(BaseModel):
    """增强结果项 schema，对齐 Coze 文档输出字段。"""
    category: str
    change_type: str
    evidence: str
    impact: str
    new_quote: Optional[str] = None
    old_quote: Optional[str] = None
    original: str
    risk_level: str
    suggestion: str
    summary: str


class ContractComparisonOutput(BaseModel):
    """合同比对任务输出模型，对齐 Coze 文档结构。"""
    success: bool
    enhanced: list[EnhancedItemSchema]
    total_risks: int
    message: str = ""


@coze预留_router.post("/contract/comparison", response_model=ContractComparisonOutput)
async def analyze_contract_comparison(input_data: ContractComparisonInput) -> ContractComparisonOutput:
    """
    合同版本比对语义增强接口（联调接口）。

    输入字段：对齐 Coze 文档，只需 task_type, old_text, new_text。
    输出字段：success, enhanced[], total_risks, message。

    enhanced[] 包含：
    - category: 风险分类（付款条款、违约责任、验收条款等）
    - change_type: 差异类型（added/deleted/modified/moved）
    - evidence: 旧版和新版的变化证据
    - impact: 该改动可能带来的影响
    - new_quote: 新版原文片段
    - old_quote: 旧版原文片段
    - original: 差异客观复述
    - risk_level: 风险等级（high/medium/low）
    - suggestion: 处理建议
    - summary: 单条差异摘要
    """
    try:
        coze_service = get_coze_service()
        parameters = build_comparison_workflow_input(
            task_type=input_data.task_type,
            old_text=input_data.old_text,
            new_text=input_data.new_text,
            diff_stats={"total": 0, "added": 0, "deleted": 0, "modified": 0},
            diff_texts=[],
        )
        result = await coze_service.call_workflow(coze_service.comparison_workflow_id, parameters)
        normalized = normalize_comparison_workflow_result(result)

        # 构建 enhanced 列表，确保字段完整对应 Coze 文档
        enhanced_list = []
        for item in normalized.get("enhanced", []):
            enhanced_list.append(EnhancedItemSchema(
                category=item.get("category", ""),
                change_type=item.get("change_type", "modified"),
                evidence=item.get("evidence", ""),
                impact=item.get("impact", ""),
                new_quote=item.get("new_quote") or item.get("new"),
                old_quote=item.get("old_quote") or item.get("old"),
                original=item.get("original", ""),
                risk_level=item.get("risk_level", "low"),
                suggestion=item.get("suggestion", ""),
                summary=item.get("summary", ""),
            ))

        return ContractComparisonOutput(
            success=normalized.get("success", True),
            enhanced=enhanced_list,
            total_risks=normalized.get("total_risks", 0),
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
