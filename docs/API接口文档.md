# 合规罗盘 API 接口文档

---

## 目录

1. [用户认证](#1-用户认证)
2. [单合同审查](#2-单合同审查)
3. [合同版本比对](#3-合同版本比对)
4. [风险点人工确认](#4-风险点人工确认)
5. [Coze 工作流对接（v0.2）](#5-coze-工作流对接v02)
6. [枚举值说明](#6-枚举值说明)
7. [通用错误码](#7-通用错误码)
8. [规则库管理](#8-规则库管理)
9. [优化合同版本与脱敏说明](#9-优化合同版本与脱敏说明)

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
| contract_type | string | 否 | 合同类型（默认"通用"，如"采购合同"、"服务合同"） |

**流程**: 上传文件 → 创建任务 → 解析文档 → 脱敏 → Coze 分析 → 还原脱敏 → 保存结果

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
      "low": 2,
      "passed": 50
    },
    "suggest_deep_review": false,
    "status": "completed",
    "sanitization_status": "completed",
    "sanitization_error": null,
    "rule_version_id": "version-uuid",
    "contract_type": "通用",
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
      "replace_text": "合同总金额为人民币壹拾万元整",
      "rule_code": "COM-FIN-001",
      "rule_snapshot_json": {
        "rule_code": "COM-FIN-001",
        "contract_type": "通用",
        "review_module": "财务",
        "risk_name": "合同金额不明确",
        "default_risk_level": "高",
        "suggestion_template": "建议明确合同总金额..."
      },
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
| contract_type | string | 否 | 合同类型（默认"通用"） |

**流程**: 上传两个文件 → 创建任务 → 解析文档 → 脱敏 → 文本 diff → Coze 增强 → 还原脱敏 → 保存结果

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
    "paragraph_count": 50,
    "sentence_count": 120
  },
  "new_file": {
    "name": "新合同.docx",
    "type": "docx",
    "char_count": 5200,
    "page_count": 5,
    "paragraph_count": 52,
    "sentence_count": 125
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

## 5. Coze 工作流对接（v0.2）

### 5.1 审查工作流（review）

**Coze API**: `POST https://api.coze.cn/v1/workflow/run`

**传入 parameters（input 字段内 JSON）**:

```json
{
  "file_id": "上传到Coze的文件ID",
  "contract_type": "通用",
  "rule_version_id": "version-uuid",
  "rules": [
    {
      "rule_code": "COM-FIN-001",
      "contract_type": "通用",
      "review_module": "财务",
      "risk_name": "合同金额不明确",
      "check_point": "是否明确合同总金额、币种、大小写金额",
      "trigger_condition": "合同仅写费用另行协商或未写明总金额",
      "default_risk_level": "高",
      "suggestion_template": "建议明确合同总金额、币种、大小写金额及费用构成",
      "example_clause": "合同费用由双方另行确认。"
    }
  ],
  "sanitized_text": "脱敏后的合同全文（新）",
  "sanitization_enabled": true
}
```

**Coze 工作流需返回**:

```json
{
  "agreeCount": 50,
  "highlevelriskCount": 1,
  "mediumlevelriskCount": 2,
  "lowlevelriskCount": 3,
  "output": [
    {
      "key": "合同金额不明确",
      "risk": "高",
      "tip": "合同仅写费用另行协商，未明确总金额",
      "advice": "建议在合同第二条明确约定合同总金额及费用构成",
      "content": "合同费用由双方另行协商确定。",
      "replace_text": "合同总金额为人民币XXX元（大写：XXX元整）",
      "rule_code": "COM-FIN-001"
    }
  ]
}
```

**output 字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| key | string | 风险标题 |
| risk | string | 风险等级：高/中/低/"通过"（通过项会被过滤） |
| tip | string | 风险原因 |
| advice | string | 修改建议 |
| content | string | 原文证据 |
| replace_text | string | 建议替换文本 |
| rule_code | string | **v0.2 新增**，命中规则的编号 |

### 5.2 比对工作流（comparison）

**Coze API**: `POST https://api.coze.cn/v1/workflow/run`

**传入 parameters**:

```json
{
  "task_type": "contract_comparison",
  "old_text": "脱敏后旧合同全文",
  "new_text": "脱敏后新合同全文",
  "diff_stats": { "total": 10, "added": 3, "deleted": 2, "modified": 5 },
  "diff_texts": [
    { "type": "modified", "content": "修改内容：公司A应向公司B支付100,000元 → 150,000元" },
    { "type": "added", "content": "新增内容：保密义务条款" },
    { "type": "deleted", "content": "删除内容：原第八条免责声明" }
  ],
  "contract_type": "通用",
  "rule_version_id": "version-uuid",
  "rules": [{ "rule_code": "COM-FIN-001", ... }]
}
```

**Coze 工作流需返回**:

```json
{
  "output": {
    "diff_list": [
      {
        "type": "modified",
        "risk_level": "中",
        "old": "公司A应向公司B支付100,000元",
        "new": "公司A应向公司B支付150,000元",
        "analysis": "付款金额从100,000元变更为150,000元，需确认变更依据",
        "advice": "建议在合同中注明金额变更的原因",
        "rule_id": "COM-FIN-001"
      }
    ],
    "stats": { "addCount": 3, "deleteCount": 2, "modifyCount": 5 },
    "summary": "本次修订共10处差异..."
  }
}
```

**diff_list 字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| type | string | 差异类型：added/deleted/modified |
| risk_level | string | 风险等级：高/中/低 |
| old | string | 旧版原文 |
| new | string | 新版原文 |
| analysis | string | 风险分析 |
| advice | string | 修改建议 |
| rule_id | string | 命中规则编号|


## 8. 规则库管理

所有规则库接口均需要 Bearer Token。

### 8.1 查询规则列表

**接口**: `GET /api/v1/rules`

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| skip | integer | 否 | 跳过数量，默认 0 |
| limit | integer | 否 | 返回数量，默认 20 |
| version_id | string | 否 | 规则版本 ID |
| contract_type | string | 否 | 合同类型 |
| enabled | boolean | 否 | 是否启用 |

**响应** (200 OK):
```json
{
  "rules": [
    {
      "id": "rule-uuid",
      "version_id": "version-uuid",
      "rule_code": "COM-FIN-001",
      "contract_type": "通用",
      "review_module": "财务",
      "risk_name": "合同金额不明确",
      "check_point": "是否明确合同总金额、币种、大小写金额",
      "trigger_condition": "合同仅写费用另行协商或未写明总金额",
      "default_risk_level": "高",
      "suggestion_template": "建议明确合同总金额、币种、大小写金额及费用构成",
      "example_clause": "合同费用由双方另行确认。",
      "enabled": true,
      "created_at": "2026-05-07T10:00:00",
      "updated_at": "2026-05-07T10:00:00"
    }
  ],
  "total": 59,
  "skip": 0,
  "limit": 20
}
```

### 8.2 创建、编辑、删除和启停规则

```http
POST /api/v1/rules
PATCH /api/v1/rules/{rule_id}
DELETE /api/v1/rules/{rule_id}
PATCH /api/v1/rules/{rule_id}/enabled
```

创建规则请求体：

```json
{
  "rule_code": "COM-FIN-001",
  "contract_type": "通用",
  "review_module": "财务",
  "risk_name": "合同金额不明确",
  "check_point": "是否明确合同总金额、币种、大小写金额",
  "trigger_condition": "合同仅写费用另行协商或未写明总金额",
  "default_risk_level": "高",
  "suggestion_template": "建议明确合同总金额、币种、大小写金额及费用构成",
  "example_clause": "合同费用由双方另行确认。",
  "enabled": true
}
```

`default_risk_level` 只允许：`高`、`中`、`低`。

### 8.3 CSV 批量导入规则

**接口**: `POST /api/v1/rules/import-csv`

**Content-Type**: `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 规则 CSV 文件 |

导入成功后会生成草稿规则版本，需激活后才参与新任务审查。导入失败时返回行号、字段和失败原因。

**响应** (200 OK):
```json
{
  "success": true,
  "version_id": "version-uuid",
  "version_no": 2,
  "imported_count": 59,
  "errors": []
}
```

### 8.4 规则版本

```http
GET /api/v1/rule-versions
POST /api/v1/rule-versions
POST /api/v1/rule-versions/{version_id}/activate
```

说明：

- 同一时间只有一个激活规则版本。
- 审查和比对任务会记录当时使用的 `rule_version_id` 和规则快照。
- 规则修改不影响历史审查结果。
- 启用 Coze 且没有激活规则版本时，审查/比对接口会返回明确错误。

**版本列表响应** (`GET /api/v1/rule-versions`):
```json
[
  {
    "id": "version-uuid",
    "version_no": 2,
    "name": "CSV导入规则版本",
    "description": "CSV导入",
    "status": "active",
    "activated_at": "2026-05-07T12:00:00",
    "created_at": "2026-05-07T10:00:00",
    "updated_at": "2026-05-07T12:00:00",
    "rule_count": 59
  }
]
```

---

## 9. 优化合同版本与脱敏说明

### 9.1 采纳建议生成优化合同

**接口**: `POST /api/v1/reviews/{task_id}/suggestions/apply`

**请求体**:

```json
{
  "risk_ids": ["risk-uuid-1", "risk-uuid-2"],
  "title": "合同优化版"
}
```

后端会根据风险点中的 `replace_text` 和位置信息生成新的优化合同版本，原始合同不会被覆盖。

**响应** (200 OK):
```json
{
  "success": true,
  "version": {
    "id": "version-uuid",
    "review_task_id": "task-uuid",
    "version_no": 1,
    "title": "合同优化版",
    "text": "优化后的合同全文...",
    "accepted_risk_ids": ["risk-uuid-1", "risk-uuid-2"],
    "created_by_user_id": "user-uuid",
    "created_at": "2026-05-07T10:00:00"
  },
  "message": "优化合同版本已生成"
}
```

### 9.2 查询和导出优化合同版本

```http
GET /api/v1/reviews/{task_id}/optimized-versions
GET /api/v1/reviews/{task_id}/optimized-versions/{version_id}
POST /api/v1/reviews/{task_id}/optimized-versions/{version_id}/export
```

导出的文件只包含优化后的合同正文，不包含风险报告、批注和风险列表。
