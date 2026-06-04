# 合同比对工作流

这是一个独立的合同比对工作流模块，只分析两版合同之间的差异，并基于规则接口返回的规则统一进行差异风险审查。

## 调用方式

主入口：

```python
from contract_compare_workflow import compare_contracts

result = await compare_contracts(
    old_text="旧合同全文",
    new_text="新合同全文",
    task_type="compare",
)
```

最终只返回：

```json
{
  "success": true,
  "enhanced": [],
  "total_risks": 0,
  "message": ""
}
```

`enhanced` 每项固定包含：

```json
{
  "original": "",
  "change_type": "added/deleted/modified/moved",
  "old_quote": "",
  "new_quote": "",
  "category": "",
  "summary": "",
  "risk_level": "high/medium/low",
  "evidence": "",
  "impact": "",
  "suggestion": ""
}
```

模块不会在最终结果中返回 `contract_type`、`diff_texts`、`common_rules`、`specific_rules`、`total_rules`、`addCount`、`deleteCount`、`modifyCount`、`rule_id`、`rule_code`。

## 环境变量

配置从仓库根目录 `.env` 读取，同时支持运行环境变量覆盖：

```env
LLM_PROVIDER=minimax
LLM_MODEL_NAME=MiniMax-M2.7
MINIMAX_API_KEY=your_api_key
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
AUDIT_RULES_API_URL=http://82.156.132.43:8080/api/audit-rules
```

当前实现仅支持 `LLM_PROVIDER=minimax`，按 OpenAI-compatible `POST /chat/completions` 方式调用。

## 工作流

```text
old_text + new_text
→ 合同类型判断和差异识别并行执行
→ GET /api/audit-rules?contract_type=识别出的合同类型
→ 解析规则响应
→ 合并 finance_rules / legal_rules / performance_rules / other_rules
→ 仅拆成 common_rules / specific_rules
→ diff_texts 为空则直接返回空结果
→ 否则调用一个统一的大模型风险审查节点
→ 标准化最终输出
```

风险审查结果会按 `diff_texts` 的顺序回填，且 `original`、`change_type`、`old_quote`、`new_quote` 永远以 `diff_texts` 为准，避免模型改写前端定位字段。

## 测试示例

```python
import asyncio
import json

from contract_compare_workflow import compare_contracts


async def main():
    result = await compare_contracts(
        old_text=(
            "采购合同\n"
            "甲方向乙方采购服务器设备，合同总价为人民币100000元。"
            "甲方应在乙方交付全部设备并经甲方验收合格后30个工作日内付款。"
            "乙方应提供13%增值税专用发票。"
        ),
        new_text=(
            "采购合同\n"
            "甲方向乙方采购服务器设备，合同总价为人民币120000元。"
            "甲方应在乙方交付设备后15个工作日内付款。"
            "乙方开具发票事宜由双方另行协商。"
        ),
        task_type="compare",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


asyncio.run(main())
```

期望识别方向：

```text
合同金额变化
付款前提和付款期限变化
发票条款变化
```

## 依赖建议

当前没有新增依赖，直接使用项目已有的 `httpx` 和标准库。

如果后续希望与全项目 LLM 框架统一，可以考虑新增：

```text
langchain
langchain-openai
python-dotenv
```

但本模块当前不依赖这些包，也未修改根目录 `requirements.txt`。

## 当前限制

1. 差异识别和风险审查依赖大模型输出质量。
2. 差异识别阶段会校验 `old_quote` / `new_quote` 是否能在原文中直接命中；无法命中时会返回“差异识别结果解析失败”。
3. 规则接口请求失败时直接返回失败结果，不进入风险审查。
4. `total_risks` 优先使用风险审查节点返回值；如果缺失或非法，后端会按 high / medium 与 low 但实质性改动的规则兜底计算。

## 最小验证

可直接运行：

```powershell
python -B contract_compare_workflow\validate_compare_workflow.py
```

这个脚本会用模块内 monkeypatch 方式模拟：

```text
合同类型判断
差异识别
规则接口返回
风险审查返回
```

并验证：

```text
最终只返回 success / enhanced / total_risks / message
enhanced 每项字段固定
old_quote / new_quote 与 diff_texts 原样一致
total_risks 是数字类型，且在 stub 场景中与样例期望一致
```

当前脚本覆盖的场景包括：

```text
正常修改场景：合同金额、付款前提/期限、验收条款、违约责任
新增条款场景：新增保密条款
删除条款场景：删除争议解决条款
移动条款场景：条款位置变化但内容不变
低风险场景：轻微措辞变化
空差异场景：old_text 与 new_text 完全一致
错误输入场景：old_text 为空、new_text 为空
```
