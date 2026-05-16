# Coze 合同版本比对工作流后端接入文档

## 1. 输入

### 请求地址

```text
POST https://api.coze.cn/v1/workflow/run
```

### 请求头

```http
Authorization: Bearer {COZE_ACCESS_TOKEN}
Content-Type: application/json
```

### 请求体

```json
{
  "workflow_id": "7640097297989451811",
  "parameters": {
    "task_type": "contract_comparison",
    "old_text": "旧版合同全文",
    "new_text": "新版合同全文"
  }
}
```

### 输入字段描述

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `workflow_id` | string | 是 | Coze 工作流 ID，固定传 `7640097297989451811` |
| `parameters.task_type` | string | 否 | 兼容字段，建议固定传 `contract_comparison` |
| `parameters.old_text` | string | 是 | 旧版合同全文 |
| `parameters.new_text` | string | 是 | 新版合同全文 |

---

## 2. 输出

### Coze 外层响应

```json
{
  "code": 0,
  "msg": "",
  "data": "{\"success\":true,\"enhanced\":[...],\"total_risks\":1,\"message\":\"\"}",
  "debug_url": "https://www.coze.cn/work_flow?...",
  "execute_id": "7640393719325753380"
}
```

说明：

- 后端需要对 `data` 再做一次 JSON 解析
- 实际业务结果在 `data` 里

### 业务层输出

```json
{
  "success": true,
  "enhanced": [
    {
      "category": "付款条款",
      "change_type": "modified",
      "evidence": "旧版...新版...",
      "impact": "风险影响说明",
      "new_quote": "新版原文片段",
      "old_quote": "旧版原文片段",
      "original": "差异客观复述",
      "risk_level": "medium",
      "suggestion": "处理建议",
      "summary": "单条差异摘要"
    }
  ],
  "total_risks": 1,
  "message": ""
}
```

### 输出字段描述

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | boolean | 工作流是否执行成功 |
| `enhanced` | array | 风险识别结果主数组 |
| `total_risks` | integer | 风险条目数量 |
| `message` | string | 补充信息或空字符串 |

### `enhanced[]` 字段描述

| 字段 | 类型 | 说明 |
|---|---|---|
| `category` | string | 风险分类，如付款条款、违约责任、验收条款 |
| `change_type` | string | 差异类型 |
| `evidence` | string | 旧版和新版的变化证据 |
| `impact` | string | 该改动可能带来的影响 |
| `new_quote` | string | 新版原文片段，可用于定位 |
| `old_quote` | string | 旧版原文片段，可用于定位 |
| `original` | string | 差异客观复述 |
| `risk_level` | string | 风险等级 |
| `suggestion` | string | 建议处理方式 |
| `summary` | string | 单条差异摘要 |

### 枚举值

#### `change_type`

```text
added
deleted
modified
moved
```

#### `risk_level`

```text
high
medium
low
```
