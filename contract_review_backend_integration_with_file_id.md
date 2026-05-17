# Coze 合同审查工作流后端接入文档

## 1. 输入

### 1.1 前置步骤：上传合同文件获取 file_id

合同审查工作流的开始节点只有一个业务输入参数：`input`，类型为 `Doc`。

因此后端调用工作流前，建议先调用 Coze 文件上传接口上传合同文件，获取 `file_id`，再将 `file_id` 传入合同审查工作流。

### 文件上传请求地址

```text
POST https://api.coze.cn/v1/files/upload
```

### 文件上传请求头

```http
Authorization: Bearer {COZE_ACCESS_TOKEN}
Content-Type: multipart/form-data
```

### 文件上传请求示例

```bash
curl -X POST "https://api.coze.cn/v1/files/upload" \
  -H "Authorization: Bearer {COZE_ACCESS_TOKEN}" \
  --form "file=@/path/to/contract.docx"
```

### 文件上传响应示例

```json
{
  "code": 0,
  "msg": "",
  "data": {
    "id": "file_xxxxx"
  }
}
```

说明：

- `data.id` 即为后续调用合同审查工作流时需要传入的 `file_id`。
- 推荐上传 `.docx` 格式合同文档。

---

### 1.2 调用合同审查工作流

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
  "workflow_id": "7634842444869861416",
  "parameters": {
    "input": "{\"file_id\":\"file_xxxxx\"}"
  }
}
```

说明：

- `input` 是合同审查工作流唯一的业务输入参数。
- 由于开始节点 `input` 类型为 `Doc`，后端调用时建议传入文件上传后得到的 `file_id`。
- `parameters.input` 建议使用 JSON 序列化字符串格式，例如：`"{\"file_id\":\"file_xxxxx\"}"`。
- `workflow_id` 是 Coze 接口调用字段，不属于工作流开始节点的业务输入参数。

### 输入字段描述

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `workflow_id` | string | 是 | Coze 接口调用字段，用于指定合同审查工作流，固定传 `7634842444869861416` |
| `parameters.input` | string | 是 | 合同审查工作流唯一业务输入参数。由于开始节点 `input` 类型为 `Doc`，后端调用时建议传入文件上传后得到的 `file_id`，格式为 JSON 序列化字符串 |
| `file_id` | string | 是 | 通过 Coze 文件上传接口上传合同文件后返回的文件 ID |

---

## 2. 输出

### Coze 外层响应

```json
{
  "code": 0,
  "msg": "",
  "data": "{\"agreeCount\":\"15\",\"highlevelriskCount\":\"2\",\"mediumlevelriskCount\":\"3\",\"lowlevelriskCount\":\"1\",\"output\":[...]}",
  "debug_url": "https://www.coze.cn/work_flow?...",
  "execute_id": "763xxxxxxxxxxxx"
}
```

说明：

- 后端需要对 `data` 再做一次 JSON 解析。
- 实际业务结果在 `data` 里。

### 业务层输出

```json
{
  "agreeCount": "15",
  "highlevelriskCount": "2",
  "mediumlevelriskCount": "3",
  "lowlevelriskCount": "1",
  "output": [
    {
      "risk": "中风险",
      "key": "付款前提缺失",
      "tip": "付款条款未明确验收合格和收到合规发票作为付款前提，可能导致付款保障不足。",
      "content": "甲方应在乙方提交付款申请后十个工作日内付款。",
      "advice": "建议明确付款前提，例如验收合格且收到合规发票后若干日内付款。",
      "replace_text": "甲方应在乙方交付成果经甲方验收合格，且甲方收到乙方开具的合法有效发票后【期限】内支付相应款项。"
    }
  ]
}
```

### 输出字段描述

| 字段 | 类型 | 说明 |
|---|---|---|
| `agreeCount` | string | 审查结果为 `通过` 的审核项数量 |
| `highlevelriskCount` | string | 审查结果为 `高风险` 的审核项数量 |
| `mediumlevelriskCount` | string | 审查结果为 `中风险` 的审核项数量 |
| `lowlevelriskCount` | string | 审查结果为 `低风险` 的审核项数量 |
| `output` | array | 合同审查结果主数组 |

说明：

当前计数字段是字符串类型，例如：

```json
{
  "agreeCount": "15",
  "highlevelriskCount": "2",
  "mediumlevelriskCount": "3",
  "lowlevelriskCount": "1"
}
```

如果后端需要用于统计卡片、图表或排序，可以在解析后转换为 number。

---

### `output[]` 字段描述

| 字段 | 类型 | 说明 |
|---|---|---|
| `risk` | string | 当前审核项的风险等级 |
| `key` | string | 审核项名称或风险点名称 |
| `tip` | string | 风险提示，说明该条款为什么存在风险；无风险时为 `无` |
| `content` | string | 风险对应的合同原文；无风险时为 `无` |
| `advice` | string | 修改建议，用于说明应该怎么改、补充什么、明确什么 |
| `replace_text` | string | 可替换修改文本，提供可参考放入合同的正式条款文本；无风险时为 `无` |

---

## 3. 枚举值

### `output[].risk`

```text
通过
高风险
中风险
低风险
```

| 取值 | 含义 |
|---|---|
| `通过` | 当前审核项未发现明显风险 |
| `高风险` | 当前条款存在较高合同风险，需要重点关注 |
| `中风险` | 当前条款存在一定合同风险，需要人工复核或补充完善 |
| `低风险` | 当前条款存在轻微不完善之处，建议优化 |

---

## 4. 字段说明

### `output[].risk`

用于表示当前审核项的风险等级。

示例：

```json
{
  "risk": "中风险"
}
```

---

### `output[].key`

用于展示风险点或审核项名称，通常来自规则库中的风险名称或检查点概括。

示例：

```text
付款前提缺失
逾期付款责任缺失
提前终止结算不明确
验收标准缺失
知识产权归属不明确
```

---

### `output[].tip`

用于说明风险原因，回答：

```text
为什么这个条款存在风险？
可能导致什么问题？
```

示例：

```text
付款条款未明确验收合格和收到合规发票作为付款前提，可能导致付款保障不足。
```

无风险时固定为：

```text
无
```

---

### `output[].content`

用于引用合同中存在风险的原文片段。

| 场景 | 输出规则 |
|---|---|
| 无风险 | 输出 `无` |
| 有风险且合同中存在对应原文 | 尽量完整引用合同中的风险条款原文 |
| 有风险但合同原文缺失 | 输出 `未发现明确原文，但相关内容缺失` |

后端可以基于 `content` 在合同全文中进行关键词查找和位置定位。

---

### `output[].advice`

用于描述修改方向，回答：

```text
应该怎么改？
应该补充什么？
应该明确哪些内容？
```

示例：

```text
建议明确付款前提，例如验收合格且收到合规发票后若干日内付款。
```

---

### `output[].replace_text`

用于提供可参考替换或补充到合同中的正式条款文本，回答：

```text
具体可以替换成什么？
可以补充哪段合同条款？
```

`replace_text` 和 `advice` 的区别如下：

| 字段 | 作用 | 表达方式 |
|---|---|---|
| `advice` | 描述修改方向 | 可以写“建议……” |
| `replace_text` | 给出可参考写入合同的正式文本 | 尽量使用合同条款式表述，不建议以“建议……”开头 |

示例：

```text
甲方付款应以乙方交付成果经甲方验收合格，且甲方收到乙方开具的合法有效增值税专用发票为前提。甲方应在上述条件全部满足后【期限】内支付相应款项。
```

---

## 5. 完整输出示例

```json
{
  "agreeCount": "15",
  "highlevelriskCount": "2",
  "mediumlevelriskCount": "3",
  "lowlevelriskCount": "1",
  "output": [
    {
      "risk": "高风险",
      "key": "预付款风险过高",
      "tip": "合同约定预付款比例较高，且未约定履约保证金、担保或退款机制，存在资金安全风险。",
      "content": "甲方应在合同签订后向乙方支付合同总价的 80% 作为预付款。",
      "advice": "建议降低预付款比例，或增加履约保证、分批付款和退款条款。",
      "replace_text": "甲方应在合同签订后向乙方支付合同总价的【比例】作为预付款，剩余款项在乙方交付成果经甲方验收合格后支付。乙方应在收到预付款前向甲方提供【金额】的履约保证金或银行保函。"
    },
    {
      "risk": "中风险",
      "key": "付款前提缺失",
      "tip": "付款条款未明确验收合格和收到合规发票作为付款前提，可能导致付款保障不足。",
      "content": "甲方应在乙方提交付款申请后十个工作日内付款。",
      "advice": "建议明确付款前提，例如验收合格且收到合规发票后若干日内付款。",
      "replace_text": "甲方应在乙方交付成果经甲方验收合格，且甲方收到乙方开具的合法有效发票后【期限】内支付相应款项。"
    },
    {
      "risk": "低风险",
      "key": "履行地点不明确",
      "tip": "合同涉及系统开发、部署实施及交付，但未明确写明履行地点、开发地点或交付地点。",
      "content": "乙方应负责完成系统部署环境配置、接口联调、试运行问题修复以及上线后六十日内的基础运维支持。",
      "advice": "建议明确履行地点、收货地址或服务地点。",
      "replace_text": "乙方应在【服务地点】完成系统设计与开发，并负责将系统部署至【甲方指定的服务器环境/云环境】。"
    },
    {
      "risk": "通过",
      "key": "合同金额不明确",
      "tip": "无",
      "content": "无",
      "advice": "无",
      "replace_text": "无"
    }
  ]
}
```

---

## 6. 空结果返回约定

当前合同审查工作流要求每条审核规则都对应一条审核结果，因此即使没有风险，也不会返回空数组，而是返回若干个 `risk = 通过` 的审核项。

示例：

```json
{
  "agreeCount": "8",
  "highlevelriskCount": "0",
  "mediumlevelriskCount": "0",
  "lowlevelriskCount": "0",
  "output": [
    {
      "risk": "通过",
      "key": "合同金额明确性",
      "tip": "无",
      "content": "无",
      "advice": "无",
      "replace_text": "无"
    }
  ]
}
```

---

## 7. 后端解析建议

Coze 外层响应中的 `data` 通常是字符串，因此后端建议这样处理：

```ts
const cozeResp = await callCozeWorkflow();

if (cozeResp.code !== 0) {
  throw new Error(cozeResp.msg || "Coze workflow failed");
}

const businessData = typeof cozeResp.data === "string"
  ? JSON.parse(cozeResp.data)
  : cozeResp.data;

const output = businessData.output || [];

const agreeCount = Number(businessData.agreeCount || 0);
const highCount = Number(businessData.highlevelriskCount || 0);
const mediumCount = Number(businessData.mediumlevelriskCount || 0);
const lowCount = Number(businessData.lowlevelriskCount || 0);
```

---

## 8. 最终确认版

```text
合同审查 workflow_id：
7634842444869861416

业务输入参数：
input

input 调用方式：
后端先上传合同文件获取 file_id，再将 file_id 以 JSON 序列化字符串形式传入 parameters.input。

输出字段：
agreeCount
highlevelriskCount
mediumlevelriskCount
lowlevelriskCount
output

output 每项字段：
risk
key
tip
content
advice
replace_text

risk 枚举：
通过
高风险
中风险
低风险
```
