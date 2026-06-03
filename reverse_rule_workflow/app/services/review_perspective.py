from typing import Literal


ReviewPerspective = Literal["甲方", "乙方", "通用"]

GENERIC_REVIEW_ROLES = {"", "通用", "通用角色", "中立", "双方", "合同相对方", "合同签署方"}

PARTY_A_ROLES = {
    "甲方",
    "起诉方",
    "采购方",
    "委托方",
    "用户方",
    "守约方",
    "通知接收方",
    "个人信息处理委托方",
}

PARTY_B_ROLES = {
    "乙方",
    "收款方",
    "服务方",
    "交付方",
    "披露方",
    "开发方",
    "履约方",
    "被限制方",
    "开票方",
    "被审计方",
    "供应方",
}


def normalize_review_perspective(review_role: str | None) -> ReviewPerspective:
    role = (review_role or "").strip()
    if role in PARTY_A_ROLES:
        return "甲方"
    if role in PARTY_B_ROLES:
        return "乙方"
    if role in GENERIC_REVIEW_ROLES:
        return "通用"
    return "通用"


def is_generic_review_role(review_role: str | None) -> bool:
    return normalize_review_perspective(review_role) == "通用"
