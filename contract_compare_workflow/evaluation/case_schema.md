# gold_cases.json 字段约定

`gold_cases.json` 用于描述评测样例、gold label 和 stub 模式下的期望输出。

## 顶层结构

```json
{
  "version": "v1",
  "cases": []
}
```

## case 字段

每个 case 推荐包含：

```json
{
  "case_id": "purchase_short_payment_001",
  "suite": "semantic_gold",
  "contract_type": "采购合同",
  "length_bucket": "短合同",
  "task_type": "compare",
  "scenario_tags": ["付款期限变化", "modified"],
  "old_text": "旧合同全文",
  "new_text": "新合同全文",
  "expected_success": true,
  "expected_message": "",
  "expected_total_risks": 1,
  "expected_diff_count": 1,
  "non_substantive_expectation": "filtered",
  "notes": "用于说明样例意图",
  "diff_items": []
}
```

说明：

- `suite` 当前建议值：
  - `protocol_boundary`
  - `semantic_gold`
- `length_bucket` 当前建议值：
  - `短合同`
  - `中合同`
  - `长合同`
- `non_substantive_expectation` 可选值：
  - `filtered`
  - `low_retained`

## diff_items 字段

每条 gold diff 建议包含：

```json
{
  "diff_id": "d1",
  "substantive": true,
  "must_count_in_total_risks": true,
  "change_type": "modified",
  "old_quote": "旧合同中的原文片段",
  "new_quote": "新合同中的原文片段",
  "original_required_facts": ["付款前提删除", ["30个工作日变更为15个工作日", "30个工作日缩短为15个工作日"]],
  "acceptable_categories": ["付款条款", "付款前提"],
  "acceptable_risk_levels": ["medium"],
  "suggestion_mode": "rule_template",
  "expected_suggestion_template": "建议明确付款前提，例如验收合格且收到合规发票后若干日内付款",
  "stub_output": {}
}
```

说明：

- `diff_id` 只用于评测匹配，不属于工作流输出。
- `original_required_facts` 用于评估 `original` 是否覆盖客观差异事实，不强制做整句全等。
- 其中单个字符串表示必须命中的锚点；字符串数组表示等价锚点组，命中其中任一即可。
- `acceptable_categories` 与 `acceptable_risk_levels` 支持有限容差。
- `suggestion_mode` 当前支持：
  - `rule_template`
  - `default_review`
  - `default_format`

## stub_output 字段

`stub_output` 用于 stub 模式生成稳定的 `enhanced`，建议包含：

```json
{
  "category": "付款条款",
  "summary": "付款前提减少且付款期限缩短。",
  "evidence": "旧合同与新合同的客观对比。",
  "impact": "可能造成的影响。",
  "original": "客观变化描述。",
  "risk_level": "medium",
  "suggestion": "建议明确付款前提，例如验收合格且收到合规发票后若干日内付款"
}
```

runner 会自动把以下字段从 gold diff 本身回填到最终 `enhanced`：

- `change_type`
- `old_quote`
- `new_quote`

## 自动匹配规则

自动评分时，gold diff 与预测 diff 的匹配规则如下：

1. 优先使用 `(old_quote, new_quote, change_type)` 精确匹配。
2. 对 `added`，使用 `(new_quote, change_type)` 匹配，且要求 `old_quote == ""`。
3. 对 `deleted`，使用 `(old_quote, change_type)` 匹配，且要求 `new_quote == ""`。
4. 若 quote 精确匹配失败，则该 diff 进入未匹配列表，建议人工复核。
