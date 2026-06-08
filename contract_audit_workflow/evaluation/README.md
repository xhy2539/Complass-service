# 合同审查工作流评测

本目录只用于 `contract_audit_workflow/` 的评测设计与脚本执行，不修改工作流核心逻辑，也不接入 `app/` 层路由。

## 目录说明

```text
evaluation/
  README.md
  run_dataset_eval.py
  schema_checks.py
  metrics.py
  cases/
    index.json
    *.json
  gold/
    *.json
```

## 运行方式

本地快速协议校验：

```powershell
python -B contract_audit_workflow\validate_audit_workflow.py
```

样例集评测：

```powershell
python -B contract_audit_workflow\evaluation\run_dataset_eval.py
```

可选环境变量：

```powershell
$env:AUDIT_EVAL_CASE_LIMIT="2"
$env:AUDIT_EVAL_CASE_TIMEOUT_SECONDS="300"
python -B contract_audit_workflow\evaluation\run_dataset_eval.py
```

语法检查：

```powershell
python -B -m compileall -q contract_audit_workflow
```

## 依赖说明

当前评测脚本只依赖 Python 标准库和现有 `contract_audit_workflow/` 模块。

真实评测会调用：

- 根目录 `.env` 中的 `MINIMAX_API_KEY`
- `AUDIT_RULES_API_URL`
- 当前工作流真实 LLM 与规则接口

如果后续需要更丰富的报表或表格展示，可考虑补充依赖说明，但当前不直接修改依赖文件。

## 样例格式

`cases/*.json`：

```json
{
  "case_id": "purchase_short_standard",
  "title": "采购合同-短-规范",
  "contract_type_expected": "采购合同",
  "length_bucket": "short",
  "quality_bucket": "standard",
  "input_text": "脱敏后的合同全文",
  "tags": ["purchase", "standard", "short"]
}
```

`gold/*.json`：

```json
{
  "case_id": "purchase_short_standard",
  "expected_contract_type": "采购合同",
  "expected_total_rules_optional": null,
  "expected_counts": {
    "agreeCount": null,
    "highlevelriskCount": null,
    "mediumlevelriskCount": null,
    "lowlevelriskCount": null
  },
  "rule_expectations": []
}
```

`rule_expectations` 每项建议包含：

- `rule_code`
- `expected_present`
- `risk_gold`
- `risk_label_gold`
- `action_type_gold`
- `key_aliases`
- `content_mode_gold`
- `content_anchor_optional`
- `must_not_invent_numbers`
- `advice_expectation`
- `replace_text_expectation`

## 当前评测覆盖

首批样例集共 12 个样例：

- 采购合同：短 / 中 / 长
- 服务合同：短 / 中 / 长
- 合作协议：短 / 中 / 长
- 其他：短 / 中 / 长

质量分布：

- 每类 1 个规范合同
- 每类 1 个问题合同
- 每类 1 个故意缺陷合同

故意缺陷覆盖：

- 付款
- 发票
- 验收
- 违约责任
- 争议解决
- 保密
- 知识产权
- 履约期限
- 交付地点
- 解除终止

## 指标说明

脚本当前会输出：

- 每个 case 的基础结果：
  - `case_id`
  - `contract_type_expected`
  - `predicted_contract_type`
  - `output_length`
  - `count_sum`
  - `schema_pass`
  - `latency_ms`

- 汇总指标：
  - `schema_pass_rate`
  - `count_alignment_rate`
  - `risk_label_consistency_rate`
  - `action_type_accuracy`
  - `false_positive_rate`
  - `false_negative_rate`
  - `avg_latency_ms`
  - `max_latency_ms`
  - `stable_rule_presence_rate`
  - `stable_risk_rate`
  - `stable_count_rate`

## 稳定性说明

默认不做高成本多轮稳定性评测。

如需重复运行同一合同，可在运行前设置：

```powershell
$env:AUDIT_EVAL_STABILITY_RUNS="3"
python -B contract_audit_workflow\evaluation\run_dataset_eval.py
```

未设置时默认只跑 1 次。
