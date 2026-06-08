# 工作流接口文档

本文档描述当前仓库内两个独立工作流模块的模块级接口，以及建议的 HTTP 封装格式，方便前端、后端和 Coze 工作流接入时统一理解。

当前文档描述的是：

1. 模块级 Python 调用接口
2. 建议 HTTP 封装格式

当前不代表已经完成 `app/` 层的 HTTP 路由接入。是否可直接通过 HTTP 调用，取决于后续是否在 `app/` 层补充对应路由。

当前包含两个独立工作流模块：

1. 合同审查工作流：`contract_audit_workflow/`
2. 合同比对工作流：`contract_compare_workflow/`

## 1. 合同审查工作流

### 1.1 模块入口

实际入口函数：

```python
async def audit_contract(input: str) -> dict:
    ...
```

导入示例：

```python
from contract_audit_workflow import audit_contract
```

### 1.2 输入说明

输入字段：

- `input`：合同全文字符串

说明：

- 审查工作流当前只需要传入合同全文
- `task_type` 不是必填字段，也不是当前模块入口参数

### 1.3 输出顶层字段

审查工作流最终输出严格为 5 个顶层字段：

```json
{
  "agreeCount": "11",
  "highlevelriskCount": "9",
  "mediumlevelriskCount": "19",
  "lowlevelriskCount": "1",
  "output": []
}
```

字段说明：

- `agreeCount`：通过规则数量
- `highlevelriskCount`：高风险数量
- `mediumlevelriskCount`：中风险数量
- `lowlevelriskCount`：低风险数量
- `output`：每条规则的审查明细数组

注意：

- `agreeCount`、`highlevelriskCount`、`mediumlevelriskCount`、`lowlevelriskCount` 当前都是字符串，不是数字
- `output` 是数组
- 不要新增 `message` 等其他顶层字段

### 1.4 output 每项字段

每条 `output` 必须严格包含：

```json
{
  "rule_code": "COM-FIN-003",
  "risk": "medium",
  "risk_label": "中风险",
  "action_type": "manual",
  "key": "付款前提缺失",
  "tip": "风险说明",
  "content": "命中的合同原文",
  "advice": "修改建议",
  "replace_text": "建议替换文本"
}
```

字段说明：

- `rule_code`：规则编号
- `risk`：英文风险枚举，供程序判断
- `risk_label`：中文风险标签，供前端展示
- `action_type`：前端处理动作类型
- `key`：风险名称 / 审核项
- `tip`：风险说明
- `content`：对应合同原文
- `advice`：修改建议
- `replace_text`：建议替换文本

### 1.5 risk 枚举

- `pass`：通过
- `high`：高风险
- `medium`：中风险
- `low`：低风险

说明：程序判断时优先使用 `risk`，不要使用 `risk_label` 做逻辑判断。

### 1.6 risk_label 对应关系

- `pass` -> `通过`
- `high` -> `高风险`
- `medium` -> `中风险`
- `low` -> `低风险`

### 1.7 action_type 枚举

- `manual`：人工处理
- `append`：追加内容
- `insert`：插入内容
- `replace`：替换原文

### 1.8 无风险规则输出示例

```json
{
  "rule_code": "COM-LEGAL-001",
  "risk": "pass",
  "risk_label": "通过",
  "action_type": "manual",
  "key": "争议解决条款",
  "tip": "无",
  "content": "无",
  "advice": "无",
  "replace_text": "无"
}
```

### 1.9 统计一致性要求

必须满足：

```text
int(agreeCount) + int(highlevelriskCount) + int(mediumlevelriskCount) + int(lowlevelriskCount) == len(output)
```

说明：

- 每条实际参与审查的规则必须保留一条 `output`
- 不允许因为多条规则结果相同而合并 `output`

### 1.10 本地验证命令

```powershell
python -B contract_audit_workflow\validate_audit_workflow.py
```

该脚本已覆盖：

- `all_pass`
- `mixed_risks`
- `duplicated_results_preserved`
- `three_modules`
- `pass_defaults`
- `action_types`
- `empty_rules`
- `empty_input`

## 2. 合同比对工作流

### 2.1 模块入口

实际入口函数：

```python
async def compare_contracts(
    old_text: str,
    new_text: str,
    task_type: str = "compare"
) -> dict:
    ...
```

导入示例：

```python
from contract_compare_workflow import compare_contracts
```

### 2.2 输入说明

输入字段：

- `old_text`：旧合同全文字符串
- `new_text`：新合同全文字符串
- `task_type`：可选，默认值为 `"compare"`

说明：

- 不要把 `contract_type`、`diff_list`、`stats` 等字段写成必填输入
- `old_text` 和 `new_text` 为空时会返回失败响应

### 2.3 输出顶层字段

合同比对工作流最终输出严格为 4 个顶层字段：

```json
{
  "success": true,
  "enhanced": [],
  "total_risks": 0,
  "message": ""
}
```

字段说明：

- `success`：布尔值，表示工作流是否成功执行
- `enhanced`：数组，存放每一条合同差异的风险分析结果
- `total_risks`：数字，表示计入风险或需要人工重点关注的差异数量
- `message`：字符串，成功时为空，失败时放错误信息

说明：

- 成功结果中 `total_risks` 必须等于 `len(enhanced)`
- 不要暴露 `diff_list`、`stats`、`addCount`、`deleteCount`、`modifyCount`、`contract_type` 等内部字段

### 2.4 enhanced 每项字段

每条 `enhanced` 必须严格包含：

```json
{
  "category": "付款条款",
  "change_type": "modified",
  "evidence": "风险判断证据",
  "impact": "可能造成的影响",
  "new_quote": "新合同中的原文定位片段",
  "old_quote": "旧合同中的原文定位片段",
  "original": "客观变化描述",
  "risk_level": "medium",
  "suggestion": "处理建议",
  "summary": "语义摘要"
}
```

字段说明：

- `category`：风险分类，例如合同金额、付款条款、发票条款、验收条款等
- `change_type`：差异类型
- `old_quote`：旧合同中的原文定位片段
- `new_quote`：新合同中的原文定位片段
- `original`：差异识别节点给出的客观变化描述
- `risk_level`：风险等级
- `summary`：对差异的语义摘要
- `evidence`：风险判断证据
- `impact`：可能造成的影响
- `suggestion`：处理建议，命中规则时优先使用规则库 `suggestion_template`

### 2.5 change_type 枚举

- `added`
- `deleted`
- `modified`
- `moved`

### 2.6 risk_level 枚举

- `high`
- `medium`
- `low`

### 2.7 成功响应示例

```json
{
  "success": true,
  "enhanced": [
    {
      "category": "付款条款",
      "change_type": "modified",
      "evidence": "旧合同付款前提为乙方交付全部设备并经甲方验收合格，付款期限30个工作日；新合同付款前提仅为交付设备，付款期限15个工作日",
      "impact": "甲方可能面临设备未全部交付、质量不合格的情况下仍需提前付款的风险，增加资金压力和履约风险。",
      "new_quote": "甲方应在乙方交付设备后15个工作日内付款。",
      "old_quote": "甲方应在乙方交付全部设备并经甲方验收合格后30个工作日内付款。",
      "original": "付款条款变更：删除交付全部设备及甲方验收合格的付款前提，付款期限从30个工作日缩短为15个工作日。",
      "risk_level": "medium",
      "suggestion": "建议明确付款前提，例如验收合格且收到合规发票后若干日内付款",
      "summary": "付款前提减少且付款期限缩短，存在提前付款风险。"
    }
  ],
  "total_risks": 1,
  "message": ""
}
```

### 2.8 空差异响应示例

`old_text == new_text` 时：

```json
{
  "success": true,
  "enhanced": [],
  "total_risks": 0,
  "message": ""
}
```

### 2.9 失败响应示例

例如 `old_text` 为空：

```json
{
  "success": false,
  "enhanced": [],
  "total_risks": 0,
  "message": "old_text 不能为空"
}
```

`new_text` 为空：

```json
{
  "success": false,
  "enhanced": [],
  "total_risks": 0,
  "message": "new_text 不能为空"
}
```

### 2.10 本地验证命令

```powershell
python -B contract_compare_workflow\validate_compare_workflow.py
```

该脚本已覆盖：

- 正常修改场景
- 新增条款场景
- 删除条款场景
- 移动条款场景
- 低风险场景
- 空差异场景
- `old_text` 为空
- `new_text` 为空

## 3. 建议 HTTP 封装格式

以下只是建议封装格式，当前是否可直接调用取决于 `app/` 层是否已经接入对应路由。

### 3.1 建议审查接口

```http
POST /api/workflows/audit
```

请求示例：

```json
{
  "input": "合同全文"
}
```

响应：使用合同审查工作流输出结构。

### 3.2 建议比对接口

```http
POST /api/workflows/compare
```

请求示例：

```json
{
  "old_text": "旧合同全文",
  "new_text": "新合同全文"
}
```

响应：使用合同比对工作流输出结构。

## 4. 环境变量说明

当前两个模块实际使用到的环境变量包括：

- `LLM_PROVIDER`
- `LLM_MODEL_NAME`
- `MINIMAX_API_KEY`
- `MINIMAX_BASE_URL`
- `AUDIT_RULES_API_URL`
- `AUDIT_RULES_TIMEOUT_SECONDS`

说明：

- `AUDIT_RULES_TIMEOUT_SECONDS` 当前用于合同审查工作流
- `contract_compare_workflow/` 当前没有单独使用 `COMPARE_RULES_API_URL`
- 如果某个部署环境没有单独启用合同审查工作流的超时配置，可不额外设置 `AUDIT_RULES_TIMEOUT_SECONDS`

## 5. 验证命令汇总

```powershell
python -B contract_compare_workflow\validate_compare_workflow.py
python -B contract_audit_workflow\validate_audit_workflow.py
python -B -m compileall -q contract_compare_workflow contract_audit_workflow
```

## 6. 注意事项

1. 当前验证主要是本地桩验证和语法编译检查。
2. 真实 LLM 调用、真实规则接口调用、完整项目依赖环境仍需在部署或集成环境中验证。
3. 不要提交 `.env`、API Key、`__pycache__`、临时文件。
4. 不要把审查工作流字段混入比对工作流。
5. 不要把比对工作流字段混入审查工作流。
6. 比对工作流最终不要暴露 `diff_list`、`stats`、`addCount`、`deleteCount`、`modifyCount`、`contract_type` 等内部字段。
7. 审查工作流四个统计字段当前保持字符串。
