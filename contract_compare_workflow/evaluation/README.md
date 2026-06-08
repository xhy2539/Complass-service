# 合同比对工作流评测

这个目录用于评测 `contract_compare_workflow/`，不修改工作流核心逻辑，只通过非侵入式包装和 monkeypatch 做观测与打分。

## 目录结构

```text
evaluation/
  README.md
  case_schema.md
  gold_cases.json
  instrumentation.py
  run_compare_evaluation.py
  scoring.py
  report_compare_evaluation.md
  results/
```

## 运行方式

### 1. stub 模式

用于验证评测框架本身、样例结构、评分逻辑、报告输出和观测链路是否跑通。
它不代表真实 LLM 的准确率、召回率、稳定性或线上表现。

```powershell
python -B contract_compare_workflow\evaluation\run_compare_evaluation.py --mode stub
```

可选参数：

```powershell
python -B contract_compare_workflow\evaluation\run_compare_evaluation.py --mode stub --repeat 3
python -B contract_compare_workflow\evaluation\run_compare_evaluation.py --mode stub --case-id purchase_short_amount_001
```

### 2. live 模式

直接调用真实 `compare_contracts()`，使用仓库根目录 `.env` 中已有的 LLM 和规则接口配置。

```powershell
python -B contract_compare_workflow\evaluation\run_compare_evaluation.py --mode live
```

稳定性评测建议：

```powershell
python -B contract_compare_workflow\evaluation\run_compare_evaluation.py --mode live --repeat 5
```

## 输出内容

脚本会：

1. 在控制台打印关键指标摘要；
2. 在 `evaluation/results/` 下生成一份 JSON 结果文件。

结果文件至少包含：

- 每个 case 的运行输入摘要
- 原始响应
- 内部 trace
- 各项评分与中间计数
- 汇总指标

## 当前内置 gold case

当前最小可执行集为 13 个 case：

- 5 个协议/边界 case
  - 空差异
  - `old_text` 为空
  - `new_text` 为空
  - 纯格式变化
  - 低风险 retained moved
- 4 个核心单点 case
  - 采购合同短：金额变化
  - 服务合同中：付款前提 + 付款期限变化
  - 合作协议短：新增保密条款
  - 其他中：删除争议解决条款
- 4 个组合 case
  - 采购合同长：付款前提 + 验收 + 违约责任
  - 服务合同长：知识产权 + 保密 + 交付期限
  - 合作协议长：税费承担 + 解除终止 + 争议解决
  - 其他长：moved + formatting + adjacent merge

## 指标覆盖

当前脚本会输出这些核心指标：

- `schema_pass_rate`
- `field_type_pass_rate`
- `enum_pass_rate`
- `success_message_consistency`
- `internal_field_leak_rate`
- `diff_recall`
- `diff_precision`
- `change_type_accuracy`
- `old_quote_hit_rate`
- `new_quote_hit_rate`
- `quote_preservation_rate`
- `original_fact_coverage`
- `category_accuracy`
- `risk_level_accuracy`
- `suggestion_template_hit_rate`
- `total_risks_accuracy`
- `non_substantive_filter_accuracy`
- `enhanced_coverage_rate`
- `latency`（按短/中/长合同分桶）
- `stability`（当 `--repeat > 1` 时输出）

## 依赖说明

当前评测实现只使用标准库，不新增硬依赖。

如果后续想要更好的表格或进度条，可选依赖建议写法如下，但现在不需要改根目录依赖文件：

```text
tabulate
tqdm
```

## 说明

1. `validate_compare_workflow.py` 仍然保留为协议与边界的回归验证脚本。
2. `evaluation/` 更偏向正式评测体系，负责 gold case、评分和报告输出。
3. live 模式会直接访问真实 LLM 与规则接口，因此耗时、结果稳定性与网络状态相关。
4. stub 模式指标全通过，只能说明评测器和样例设计在当前 stub 输出下自洽，不能外推为真实模型效果。
