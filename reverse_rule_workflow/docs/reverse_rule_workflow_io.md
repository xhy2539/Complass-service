# 逆向规则工作流输入输出

## 接口

- 方法：`POST`
- 路径：`/reverse-rule/extract`
- 请求体：`ContractPair[]`
- 响应体：`FinalRuleResult`

## 请求体

```json
[
  {
    "pair_id": "pair-1",
    "before_text": "甲方应在验收后90日内向乙方支付服务费。",
    "after_text": "甲方应在验收并收到合法有效发票后30日内向乙方支付服务费。",
    "contract_type": "服务合同",
    "review_role": "乙方"
  }
]
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `pair_id` | string | 否 | 合同组 ID；不传时自动生成 `pair-{序号}` |
| `before_text` | string | 是 | 修改前合同文本，不能为空 |
| `after_text` | string | 是 | 修改后合同文本，不能为空 |
| `contract_type` | string | 否 | 合同类型；不传则由工作流识别 |
| `review_role` | string | 否 | 审核角色；不传则由工作流识别 |

限制：

- 请求体数组长度：`1-5`
- `before_text`、`after_text` 会去除首尾空白
- `contract_type`、`review_role` 以入参为准，优先级高于自动识别结果

## 工作流

1. `validate_input`：校验并补齐 `pair_id`
2. `identify_base_info`：识别合同类型、审核角色、合同主题、甲乙方身份
3. `diff_pairs`：识别差异条款、变更类型、是否实质性修改
4. `process_all_pairs`：按差异构造检索 query，检索知识库案例，生成候选规则
5. `merge_rules`：按 `review_module + risk_name + trigger_condition` 合并重复规则，并合并 `traces`
6. `return_result`：返回候选规则结果

说明：`identify_base_info` 和 `diff_pairs` 是并行节点；接口最终不返回中间结果。

## 响应体

```json
{
  "summary": "共生成 1 条候选审核规则。",
  "rules": [
    {
      "contract_type": "服务合同",
      "review_module": "付款条款",
      "risk_name": "付款期限过长",
      "check_point": "检查付款期限是否过长。",
      "trigger_condition": "付款期限超过30日时触发。",
      "default_risk_level": "中",
      "suggestion_template": "建议约定30日内付款。",
      "example_clause": "甲方应在验收后90日内付款。",
      "traces": [
        {
          "pair_id": "pair-1",
          "evidence_before": "甲方应在验收后90日内向乙方支付服务费。",
          "evidence_after": "甲方应在验收并收到合法有效发票后30日内向乙方支付服务费。",
          "diff_summary": "付款条款发生实质性修改：由“...”调整为“...”。",
          "user_intent": "控制回款周期。",
          "confidence": 0.78
        }
      ]
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `summary` | string | 生成结果摘要 |
| `rules` | CandidateRuleForDB[] | 候选审核规则列表；无规则时为空数组 |

## CandidateRuleForDB

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `contract_type` | string | 合同类型 |
| `review_module` | string | 审核模块 |
| `risk_name` | string | 风险名称，最长 100 字符 |
| `check_point` | string | 审核检查点 |
| `trigger_condition` | string | 规则触发条件 |
| `default_risk_level` | `"低" \| "中" \| "高"` | 默认风险等级 |
| `suggestion_template` | string | 审核建议模板 |
| `example_clause` | string | 示例条款 |
| `traces` | RuleExtractionTrace[] | 规则来源证据 |

## RuleExtractionTrace

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pair_id` | string | 来源合同组 ID |
| `evidence_before` | string | 修改前证据文本 |
| `evidence_after` | string | 修改后证据文本 |
| `diff_summary` | string | 差异摘要 |
| `user_intent` | string | 根据修改行为推断的用户意图 |
| `confidence` | number | 置信度，范围 `0-1` |

## 异常

- 请求体数组为空或超过 5 组：抛出 `ValueError("contract_pairs 必须包含 1-5 组合同")`
- `before_text` 或 `after_text` 为空：抛出字段校验错误