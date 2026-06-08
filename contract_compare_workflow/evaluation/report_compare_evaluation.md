# 合同比对工作流评测报告模板

## 基本信息

- 模式：`stub / live`
- 重复次数：
- 生成时间：
- gold case 版本：
- 说明：若本次为 `stub` 模式，则结果只表示评测框架、样例装载、评分逻辑、报告生成和观测链路跑通，不代表真实 LLM 的准确率、召回率、稳定性或线上表现。

## 汇总指标

- schema pass rate:
- field type pass rate:
- enum pass rate:
- success/message consistency:
- internal field leak rate:
- diff recall:
- diff precision:
- change_type accuracy:
- old_quote hit rate:
- new_quote hit rate:
- quote preservation rate:
- original fact coverage:
- category accuracy:
- risk_level accuracy:
- suggestion template hit rate:
- total_risks accuracy:
- non_substantive_filter_accuracy:
- enhanced coverage rate:

## 时延

- 短合同：
- 中合同：
- 长合同：

## 稳定性

- exact_match_rate(avg):
- structure_rate(avg):
- quote_rate(avg):

## 重点失败样例

1. case_id:
   - 现象：
   - 可能原因：
   - 建议：

2. case_id:
   - 现象：
   - 可能原因：
   - 建议：

## 结论

- 当前是否满足协议要求：
- 当前是否适合扩充 gold case：
- 当前是否适合进入接口联调：
