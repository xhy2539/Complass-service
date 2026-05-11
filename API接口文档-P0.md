# 合规罗盘 API 接口文档


## 目录

1. [用户认证](#1-用户认证)
2. [单合同审查](#2-单合同审查)
3. [合同版本比对](#3-合同版本比对)
4. [风险点人工确认](#4-风险点人工确认)
5. [Coze AI 接口（后端与 Coze 联调）](#5-coze-ai-接口后端与-coze-联调)
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
| use_coze | boolean | 否 | 是否启用 Coze 分析（默认 true，前端正常调用不需要传） |

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
      "passed": 1
    },
    "suggest_deep_review": false,
    "status": "completed",
    "created_at": "2026-05-07T10:00:00",
    "updated_at": "2026-05-07T10:00:05",
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
      "replace_text": "甲方应在合同签订后向乙方支付合同总价的【比例】作为预付款...",
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
      "created_at": "2026-05-07T10:00:05",
      "updated_at": "2026-05-07T10:00:05"
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
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "file_name": "合同.docx",
    "file_type": "docx",
    "char_count": 5000,
    "page_count": 5,
    "paragraph_count": 50,
    "sentence_count": 120,
    "overall_conclusion": "合同审查完成，通过 1 项，高风险 0 项，低风险 2 项。",
    "risk_summary": {
      "high": 0,
      "medium": 0,
      "low": 2,
      "passed": 1
    },
    "suggest_deep_review": false,
    "status": "completed",
    "created_at": "2026-05-07T10:00:00",
    "updated_at": "2026-05-07T10:00:05",
    "completed_at": "2026-05-07T10:00:05",
    "risk_count": 3,
    "risk_stats": {
      "total": 3,
      "confirmed": 0,
      "ignored": 0,
      "pending": 3
    },
    "paragraphs": [],
    "sentences": [],
    "paragraphs_json": []
  }
]
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
| enhance | boolean | 否 | 是否启用 Coze 增强（默认 true，前端正常调用不需要传） |

**流程**: 上传两个文件 → 创建任务 → 解析文档 → 文本 diff → Coze 增强 → 保存结果

**响应** (200 OK):
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
      "similarity": 0.75,
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
| ignore_reason | string | 否 | 忽略原因（当 status=`ignored` 时建议填写） |
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
  "replace_text": "甲方应在合同签订后向乙方支付合同总价的【比例】作为预付款...",
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

## 5. Coze AI 接口（后端与 Coze 联调）

> 本章用于前端和 Coze 联调参考。前端正常业务优先调用第 2、3、4 章的业务接口；本章接口主要用于直接验证后端与 Coze 工作流是否连通。

### 5.1 通用 Coze 调用方式

后端统一调用 Coze 官方接口：

```http
POST https://api.coze.cn/v1/workflow/run
Authorization: Bearer <COZE_ACCESS_TOKEN>
Content-Type: application/json
```

通用请求体：

```json
{
  "workflow_id": "<工作流ID>",
  "parameters": {
    "参数名": "参数值"
  }
}
```

Coze 外层响应可能是：

```json
{
  "code": 0,
  "msg": "Success",
  "data": "{\"output\":{...}}"
}
```

后端会自动处理：

- `data` 是字符串时，先按 JSON 解析。
- `data` 是对象时，直接使用。
- 之后再读取业务字段。

---

### 5.2 合同版本比对工作流

#### 5.2.1 后端联调接口

**接口**: `POST /api/v1/coze/contract/comparison`

**认证**: 当前未加 Bearer 鉴权，建议仅用于本地或受控环境联调。

**Content-Type**: `application/json`

**请求体**:

```json
{
  "old_version_text": "旧版合同文本",
  "new_version_text": "新版合同文本"
}
```

**响应** (200 OK):

```json
{
  "output": {
    "diff_list": [
      {
        "rule_id": "COM-FIN-001",
        "type": "修改",
        "old": "旧版合同原文",
        "new": "新版合同原文",
        "analysis": "差异分析",
        "risk_level": "高风险",
        "advice": "修改建议"
      }
    ],
    "stats": {
      "addCount": 0,
      "deleteCount": 0,
      "modifyCount": 1
    },
    "summary": "新版合同相较旧版合同的主要变化摘要"
  }
}
```

#### 5.2.2 Coze 工作流信息

**workflow_id**: `7634842444869861416`

后端实际调用 Coze 的请求体：

```json
{
  "workflow_id": "7634842444869861416",
  "parameters": {
    "old_version_text": "旧版合同文本",
    "new_version_text": "新版合同文本"
  }
}
```

#### 5.2.3 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| old_version_text | string | 是 | 旧版合同全文文本 |
| new_version_text | string | 是 | 新版合同全文文本 |
| output.diff_list | array | 是 | 差异明细列表 |
| output.stats | object | 是 | 差异统计 |
| output.summary | string | 是 | 比对摘要 |

**diff_list 明细字段**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rule_id | string | 否 | 命中的规则 ID |
| type | string | 是 | 差异类型：`新增` / `删除` / `修改` |
| old | string | 否 | 旧版合同原文 |
| new | string | 否 | 新版合同原文 |
| analysis | string | 否 | 差异分析 |
| risk_level | string | 否 | 风险等级：`高风险` / `中风险` / `低风险` |
| advice | string | 否 | 修改建议 |

---

### 5.3 合同审查工作流

#### 5.3.1 后端联调接口

**接口**: `POST /api/v1/coze/contract/review`

**认证**: 当前未加 Bearer 鉴权，建议仅用于本地或受控环境联调。

**Content-Type**: `multipart/form-data`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 合同文件（docx/pdf/txt） |

**响应** (200 OK):

```json
{
  "agreeCount": "1",
  "highlevelriskCount": "2",
  "lowlevelriskCount": "5",
  "output": [
    {
      "risk": "高风险",
      "key": "预付款风险过高",
      "tip": "合同约定预付款比例为 80%，比例较高，且未约定履约保证金、担保或退款机制，存在资金安全风险。",
      "content": "甲方应在合同签订后向乙方支付合同总价的 80% 作为预付款，剩余款项在乙方交付货物后支付。",
      "advice": "建议降低预付款比例，或增加履约保证、分批付款和退款条款。",
      "replace_text": "甲方应在合同签订后向乙方支付合同总价的【比例】作为预付款，剩余款项在乙方交付货物并经甲方验收合格后支付。乙方应在收到预付款前向甲方提供【金额】的履约保证金或银行保函。"
    }
  ]
}
```

#### 5.3.2 Coze 工作流信息

**workflow_id**: `7636289402251198473`

后端调用审查工作流前会先上传合同文件：

```http
POST https://api.coze.cn/v1/files/upload
Authorization: Bearer <COZE_ACCESS_TOKEN>
Content-Type: multipart/form-data
```

上传成功后取：

```json
{
  "data": {
    "id": "file_xxxxx"
  }
}
```

然后调用工作流。后端优先使用字符串格式：

```json
{
  "workflow_id": "7636289402251198473",
  "parameters": {
    "input": "{\"file_id\":\"file_xxxxx\"}"
  }
}
```

如果字符串格式调用失败，后端会自动重试对象格式：

```json
{
  "workflow_id": "7636289402251198473",
  "parameters": {
    "input": {
      "file_id": "file_xxxxx"
    }
  }
}
```

#### 5.3.3 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agreeCount | string | 是 | 通过项数量，Coze 当前返回字符串 |
| highlevelriskCount | string | 是 | 高风险数量，Coze 当前返回字符串 |
| lowlevelriskCount | string | 是 | 低风险数量，Coze 当前返回字符串 |
| output | array | 是 | 审查明细列表 |

**output 明细字段**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| risk | string | 是 | 风险等级：`高风险` / `低风险` / `通过` |
| key | string | 是 | 风险标题或审查项名称 |
| tip | string | 否 | 风险说明 |
| content | string | 否 | 命中的合同原文 |
| advice | string | 否 | 修改建议 |
| replace_text | string | 否 | 可替换的正式条款文本 |

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
| 400 | 请求参数错误、文件为空、文件过大、不支持的文件格式 |
| 401 | 未认证或 Token 无效 |
| 403 | 无权访问该资源 |
| 404 | 资源不存在 |
| 422 | 请求体验证失败或文档解析失败 |
| 502 | Coze 服务调用失败 |

### 错误响应格式

```json
{
  "detail": "错误详情描述"
}
```

---
