# 合规罗盘 API 接口文档

## 基本信息

- **服务地址**: `http://127.0.0.1:8000`
- **API 版本**: v1
- **Base Path**: `/api/v1`
- **认证方式**: Bearer Token (JWT)
- **支持文件格式**: `.docx`, `.pdf`, `.txt`
- **文件大小限制**: 10MB

---

## 目录

1. [用户认证](#1-用户认证)
2. [单合同审查](#2-单合同审查)
3. [合同版本比对](#3-合同版本比对)
4. [风险点人工确认](#4-风险点人工确认)
5. [Coze AI 接口（Coze 端对接）](#5-coze-ai-接口coze-端对接)
6. [枚举值说明](#6-枚举值说明)
7. [通用错误码](#7-通用错误码)

---

## 1. 用户认证

### 1.1 用户注册

**接口**: `POST /api/v1/auth/register`

**请求体**:
```json
{
  "email": "user@example.com",
  "nickname": "张三",
  "password": "123456"
}
```

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| email | string | 是 | 邮箱（唯一） |
| nickname | string | 是 | 昵称 |
| password | string | 是 | 密码（至少6位） |

**响应** (201 Created):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "nickname": "张三",
    "is_active": true,
    "is_verified": false,
    "created_at": "2026-05-07T10:00:00",
    "last_login_at": null
  }
}
```

---

### 1.2 用户登录

**接口**: `POST /api/v1/auth/login`

**请求体**:
```json
{
  "email": "user@example.com",
  "password": "123456"
}
```

**响应** (200 OK):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "nickname": "张三",
    "is_active": true,
    "is_verified": false,
    "created_at": "2026-05-07T10:00:00",
    "last_login_at": "2026-05-07T12:00:00"
  }
}
```

---

## 2. 单合同审查

### 2.1 创建审查任务

**接口**: `POST /api/v1/reviews`

**认证**: Required (Bearer Token)

**Content-Type**: `multipart/form-data`

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 合同文件（docx/pdf/txt） |
| use_coze | boolean | 否 | 是否启用 Coze 分析（默认 true） |

**流程**: 上传文件 → 创建任务 → 解析文档 → Coze 分析 → 保存结果

**响应** (201 Created):
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440001",
  "message": "审查任务创建成功"
}
```

---

### 2.2 查询审查任务详情

**接口**: `GET /api/v1/reviews/{task_id}`

**认证**: Required (Bearer Token)

**路径参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 审查任务 ID |

**响应** (200 OK):
```json
{
  "success": true,
  "task": {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "file_name": "合同.docx",
    "file_type": "docx",
    "char_count": 5000,
    "page_count": 5,
    "paragraph_count": 50,
    "sentence_count": 120,
    "overall_conclusion": "合同风险较低，未发现明显异常条款",
    "risk_summary": {
      "high": 0,
      "medium": 1,
      "low": 2
    },
    "suggest_deep_review": false,
    "status": "completed",
    "created_at": "2026-05-07T10:00:00",
    "completed_at": "2026-05-07T10:00:05",
    "risk_count": 3,
    "risk_stats": {
      "total": 3,
      "confirmed": 0,
      "ignored": 0,
      "pending": 3
    },
    "paragraphs": [
      {
        "id": "para-uuid",
        "review_task_id": "550e8400-e29b-41d4-a716-446655440001",
        "index": 0,
        "text": "合同标题：XXXX合同",
        "char_offset_start": 0,
        "char_offset_end": 10,
        "page_number": 1,
        "is_key_clause": false,
        "paragraph_type": "heading1",
        "paragraph_level": 1
      }
    ],
    "sentences": []
  },
  "risk_points": [
    {
      "id": "risk-uuid",
      "title": "付款条款待明确",
      "level": "medium",
      "reason": "合同中未明确约定具体付款时间和方式",
      "suggestion": "建议补充付款条款明细",
      "category": "付款条款",
      "evidence": "合同正文中未找到关于付款时间、付款方式的明确条款",
      "impact": "可能导致付款纠纷，影响合同执行",
      "position": {
        "paragraph_index": 5,
        "char_offset_start": 100,
        "char_offset_end": 200,
        "match_strategy": "keyword"
      },
      "original_text": "甲方应按照约定履行付款义务",
      "status": "pending",
      "confirmed_at": null,
      "confirmed_by_user_id": null,
      "confirmed_by": null,
      "ignore_reason": null,
      "review_comment": null,
      "source": "coze",
      "created_at": "2026-05-07T10:00:05"
    }
  ],
  "message": "查询成功"
}
```

---

### 2.3 查询审查任务列表

**接口**: `GET /api/v1/reviews`

**认证**: Required (Bearer Token)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| skip | integer | 否 | 跳过数量（默认 0） |
| limit | integer | 否 | 返回数量（默认 20） |
| status | string | 否 | 状态筛选（pending/processing/completed/failed） |

**响应** (200 OK):
```json
{
  "tasks": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "file_name": "合同.docx",
      "file_type": "docx",
      "status": "completed",
      "created_at": "2026-05-07T10:00:00",
      "risk_count": 3
    }
  ]
}
```

---

## 3. 合同版本比对

### 3.1 创建比对任务

**接口**: `POST /api/v1/comparisons`

**认证**: Required (Bearer Token)

**Content-Type**: `multipart/form-data`

**请求参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| old_file | file | 是 | 旧版本合同文件 |
| new_file | file | 是 | 新版本合同文件 |
| enhance | boolean | 否 | 是否启用 Coze 增强（默认 true） |

**流程**: 上传两个文件 → 创建任务 → 解析文档 → 文本 diff → Coze 增强 → 保存结果

**响应** (201 Created):
```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440002",
  "message": "版本比对任务创建成功",
  "old_file": {
    "name": "旧合同.docx",
    "type": "docx",
    "char_count": 5000,
    "page_count": 5,
    "paragraph_count": 50
  },
  "new_file": {
    "name": "新合同.docx",
    "type": "docx",
    "char_count": 5200,
    "page_count": 5,
    "paragraph_count": 52
  },
  "diff_stats": {
    "total": 10,
    "added": 3,
    "deleted": 2,
    "modified": 5
  }
}
```

---

### 3.2 查询比对任务详情

**接口**: `GET /api/v1/comparisons/{task_id}`

**认证**: Required (Bearer Token)

**路径参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | string | 比对任务 ID |

**响应** (200 OK):
```json
{
  "success": true,
  "task": {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "old_file_name": "旧合同.docx",
    "new_file_name": "新合同.docx",
    "old_file_type": "docx",
    "new_file_type": "docx",
    "old_char_count": 5000,
    "new_char_count": 5200,
    "diff_stats": {
      "total": 10,
      "added": 3,
      "deleted": 2,
      "modified": 5
    },
    "total_risks": 2,
    "status": "completed",
    "created_at": "2026-05-07T10:00:00",
    "completed_at": "2026-05-07T10:00:08"
  },
  "diff_details": [
    {
      "index": 0,
      "change_type": "modified",
      "old_text": "甲方应在30日内支付款项",
      "new_text": "甲方应在15日内支付款项",
      "similarity": 75,
      "old_position": {
        "paragraph_index": 5,
        "char_offset_start": 100,
        "char_offset_end": 115
      },
      "new_position": {
        "paragraph_index": 5,
        "char_offset_start": 100,
        "char_offset_end": 112
      }
    },
    {
      "index": 1,
      "change_type": "added",
      "old_text": null,
      "new_text": "新增条款：保密义务",
      "similarity": 0,
      "old_position": null,
      "new_position": {
        "paragraph_index": 10,
        "char_offset_start": 200,
        "char_offset_end": 210
      }
    }
  ],
  "risk_points": [
    {
      "id": "cmp-risk-uuid",
      "change_type": "modified",
      "old_text": "甲方应在30日内支付款项",
      "new_text": "甲方应在15日内支付款项",
      "similarity": 75,
      "summary": "付款期限从30天缩短至15天，需确认是否影响甲方资金安排",
      "risk_level": "medium",
      "category": "付款条款",
      "evidence": "旧：30日 → 新：15日",
      "impact": "缩短付款期限可能增加甲方资金压力",
      "suggestion": "建议确认是否影响甲方资金安排",
      "old_position": {},
      "new_position": {},
      "status": "pending",
      "confirmed_at": null,
      "source": "coze"
    }
  ],
  "coze_enhanced": [],
  "message": "查询成功"
}
```

---

### 3.3 查询比对任务列表

**接口**: `GET /api/v1/comparisons`

**认证**: Required (Bearer Token)

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| skip | integer | 否 | 跳过数量（默认 0） |
| limit | integer | 否 | 返回数量（默认 20） |
| status | string | 否 | 状态筛选 |

**响应** (200 OK):
```json
{
  "success": true,
  "tasks": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440002",
      "old_file_name": "旧合同.docx",
      "new_file_name": "新合同.docx",
      "status": "completed",
      "created_at": "2026-05-07T10:00:00"
    }
  ],
  "total": 1
}
```

---

## 4. 风险点人工确认

### 4.1 更新风险点状态

**接口**: `PATCH /api/v1/risks/{risk_id}/status`

**认证**: Required (Bearer Token)

**路径参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| risk_id | string | 风险点 ID（可来自审查任务或比对任务） |

**请求体**:
```json
{
  "status": "confirmed",
  "ignore_reason": null,
  "review_comment": "已与甲方确认，付款周期调整合理"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 是 | 新状态：`pending` / `confirmed` / `ignored` |
| ignore_reason | string | 否 | 忽略原因（当 status=`ignored` 时必填） |
| review_comment | string | 否 | 人工复核备注 |

**响应** (200 OK):
```json
{
  "risk_id": "risk-uuid",
  "old_status": "pending",
  "new_status": "confirmed",
  "message": "状态已更新为 confirmed"
}
```

---

### 4.2 查询风险点详情

**接口**: `GET /api/v1/risks/{risk_id}`

**认证**: Required (Bearer Token)

**响应** (200 OK):
```json
{
  "id": "risk-uuid",
  "title": "付款条款待明确",
  "level": "medium",
  "reason": "合同中未明确约定具体付款时间和方式",
  "suggestion": "建议补充付款条款明细",
  "category": "付款条款",
  "evidence": "合同正文中未找到关于付款时间、付款方式的明确条款",
  "impact": "可能导致付款纠纷，影响合同执行",
  "position": {
    "paragraph_index": 5,
    "char_offset_start": 100,
    "char_offset_end": 200
  },
  "original_text": "甲方应按照约定履行付款义务",
  "status": "confirmed",
  "confirmed_at": "2026-05-07T12:00:00",
  "confirmed_by_user_id": "user-uuid",
  "confirmed_by": "张三",
  "ignore_reason": null,
  "review_comment": "已与甲方确认",
  "source": "coze",
  "created_at": "2026-05-07T10:00:00",
  "updated_at": "2026-05-07T12:00:00"
}
```

---

## 5. Coze AI 接口（Coze 端对接）

### 5.1 单合同风险分析

**接口**: `POST /api/v1/coze/contract/review`

**认证**: Internal（后端内部调用）

**请求体**:
```json
{
  "task_type": "contract_review",
  "file_name": "合同.docx",
  "file_type": "docx",
  "text": "合同全文（脱敏后）...",
  "char_count": 5000,
  "paragraph_count": 50
}
```

**Coze 工作流需返回**:
```json
{
  "success": true,
  "overall_conclusion": "合同风险较低，未发现明显异常条款",
  "risk_summary": {
    "high": 0,
    "medium": 1,
    "low": 2
  },
  "risk_points": [
    {
      "title": "付款条款待明确",
      "level": "medium",
      "category": "付款条款",
      "reason": "合同中未明确约定具体付款时间和方式",
      "evidence": "合同正文中未找到关于付款时间、付款方式的明确条款",
      "impact": "可能导致付款纠纷，影响合同执行",
      "suggestion": "建议补充付款条款明细，包括付款时间、付款方式、付款账户等",
      "position": null
    }
  ],
  "suggest_deep_review": false,
  "message": ""
}
```

**风险点字段说明**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | string | 是 | 风险标题 |
| level | string | 是 | 风险等级：`high` / `medium` / `low` |
| category | string | 否 | 风险分类（如：付款条款、违约责任等） |
| reason | string | 否 | 风险原因 |
| evidence | string | 否 | 证据材料（引用原文） |
| impact | string | 否 | 影响程度 |
| suggestion | string | 否 | 建议处理方式 |
| position | object | 否 | 位置信息（见下方） |

**position 位置信息**:
```json
{
  "paragraph_index": 5,
  "char_offset_start": 100,
  "char_offset_end": 200
}
```

---

### 5.2 合同版本比对语义增强

**接口**: `POST /api/v1/coze/contract/comparison`

**认证**: Internal（后端内部调用）

**请求体**:
```json
{
  "task_type": "contract_comparison",
  "old_text": "旧合同全文（脱敏后）...",
  "new_text": "新合同全文（脱敏后）...",
  "diff_stats": {
    "total": 10,
    "added": 3,
    "deleted": 2,
    "modified": 5
  },
  "diff_count": 10,
  "diff_texts": [
    {
      "type": "added",
      "content": "新增条款：保密义务"
    },
    {
      "type": "modified",
      "content": "付款期限从30天改为15天"
    }
  ]
}
```

**Coze 工作流需返回**:
```json
{
  "success": true,
  "enhanced": [
    {
      "original": "付款期限从30天改为15天",
      "change_type": "modified",
      "category": "付款条款",
      "summary": "付款期限从30天缩短至15天，需确认是否影响甲方资金安排",
      "risk_level": "medium",
      "evidence": "旧：30日 → 新：15日",
      "impact": "缩短付款期限可能增加甲方资金压力",
      "suggestion": "建议确认是否影响甲方资金安排"
    }
  ],
  "total_risks": 2,
  "message": ""
}
```

**enhanced 字段说明**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| original | string | 是 | 原始差异内容 |
| change_type | string | 是 | 差异类型：`added` / `deleted` / `modified` |
| category | string | 否 | 风险分类 |
| summary | string | 否 | 语义增强摘要 |
| risk_level | string | 否 | 风险等级：`high` / `medium` / `low` |
| evidence | string | 否 | 证据材料 |
| impact | string | 否 | 影响程度 |
| suggestion | string | 否 | 建议处理方式 |

---

### 5.3 风险点位置定位（可选）

**接口**: `POST /api/v1/coze/risk/locate`

**认证**: Internal（后端内部调用）

**请求体**:
```json
{
  "task_type": "risk_location",
  "risk_title": "付款条款待明确",
  "risk_reason": "合同中未明确约定具体付款时间和方式",
  "risk_suggestion": "建议补充付款条款明细",
  "text": "合同全文（脱敏后）...",
  "paragraphs": [
    {
      "text": "合同标题",
      "char_offset_start": 0,
      "char_offset_end": 10,
      "page_number": 1
    }
  ],
  "char_count": 5000,
  "current_location": null
}
```

**Coze 工作流需返回**:
```json
{
  "success": true,
  "matched_paragraph_index": 5,
  "char_offset_start": 100,
  "char_offset_end": 200,
  "matched_text": "甲方应按照约定履行付款义务",
  "confidence": 0.85,
  "reasoning": "通过关键词匹配找到相关段落",
  "message": ""
}
```

---

### 5.4 文本结构分析（可选）

**接口**: `POST /api/v1/coze/text/structure`

**认证**: Internal（后端内部调用）

**请求体**:
```json
{
  "task_type": "text_structure_analysis",
  "file_name": "合同.docx",
  "file_type": "docx",
  "text": "合同全文（脱敏后）...",
  "existing_paragraphs": [],
  "char_count": 5000
}
```

**Coze 工作流需返回**:
```json
{
  "success": true,
  "structured_paragraphs": [
    {
      "text": "合同标题",
      "index": 0,
      "paragraph_type": "heading1",
      "paragraph_level": 1,
      "is_key_clause": false,
      "sentence_count": 1
    }
  ],
  "paragraph_count": 50,
  "sentence_count": 120,
  "key_clauses": ["违约责任条款", "保密条款"],
  "message": ""
}
```

---

## 6. 枚举值说明

### 任务状态 (TaskStatus)

| 值 | 说明 |
|------|------|
| `pending` | 待处理 |
| `processing` | 处理中 |
| `completed` | 已完成 |
| `failed` | 失败 |

### 风险等级 (RiskLevel)

| 值 | 说明 |
|------|------|
| `high` | 高风险 |
| `medium` | 中风险 |
| `low` | 低风险 |

### 风险点状态 (RiskStatus)

| 值 | 说明 |
|------|------|
| `pending` | 待处理（初始状态） |
| `confirmed` | 已确认 |
| `ignored` | 已忽略 |

### 差异类型 (change_type)

| 值 | 说明 |
|------|------|
| `added` | 新增内容 |
| `deleted` | 删除内容 |
| `modified` | 修改内容 |

---

## 7. 通用错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 400 | 请求参数错误 |
| 401 | 未认证或 Token 无效 |
| 403 | 无权访问该资源 |
| 404 | 资源不存在 |
| 413 | 文件过大（超过 10MB） |
| 415 | 不支持的文件格式 |
| 422 | 文档解析失败 |
| 502 | Coze 服务调用失败 |

### 错误响应格式

```json
{
  "detail": "错误详情描述"
}
```

---

## 附录

### A. 段落类型 (paragraph_type)

| 值 | 说明 |
|------|------|
| `heading1` | 一级标题 |
| `heading2` | 二级标题（如：第X条） |
| `heading3` | 三级标题（如：一、二、三） |
| `body` | 正文 |

### B. 关键条款识别关键词

后端会自动识别以下关键词所在的段落为关键条款：
- 违约、赔偿、责任、罚款
- 解除、终止
- 付款、金额、交付
- 保密、知识产权

### C. 脱敏规则

后端会自动对以下信息进行脱敏处理：
- 手机号 → `[手机号]`
- 固定电话 → `[电话号码]`
- 邮箱 → `[邮箱]`
- 银行卡号 → `[银行卡]`
