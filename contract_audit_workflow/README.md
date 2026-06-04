# 合同审查工作流

该目录是独立的合同审查工作流模块，只实现单份合同审查，不实现合同比对工作流，也不接入现有后端路由。

## 调用方式

```python
import asyncio
from contract_audit_workflow import audit_contract


async def main():
    result = await audit_contract("这里放一份脱敏后的采购合同全文")
    print(result)


asyncio.run(main())
```

主入口函数：

```python
async def audit_contract(input: str) -> dict:
    ...
```

`input` 只接收合同全文字符串。内部会执行：

```text
input
→ 合同类型识别
→ GET /api/audit-rules?contract_type=识别出的合同类型
→ 规则来源适配
→ 拆分 finance_rules / legal_rules / performance_rules / other_rules
→ 财务、法务、履约并行审查
→ 分模块合并
→ 总合并
→ 最终标准化输出
```

## 环境变量

在仓库根目录 `.env` 中配置：

```env
LLM_PROVIDER=minimax
LLM_MODEL_NAME=MiniMax-M2.7
MINIMAX_API_KEY=your_api_key
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
AUDIT_RULES_API_URL=http://82.156.132.43:8080/api/audit-rules
```

可选：

```env
AUDIT_RULES_TIMEOUT_SECONDS=600
```

代码不会写入或内置真实 API Key。

## 规则接口

默认规则接口：

```http
GET http://82.156.132.43:8080/api/audit-rules?contract_type=采购合同
```

兼容直接返回：

```json
{
  "finance_rules": [],
  "legal_rules": [],
  "performance_rules": [],
  "other_rules": []
}
```

也兼容统一包裹：

```json
{
  "code": 200,
  "data": {
    "finance_rules": [],
    "legal_rules": [],
    "performance_rules": [],
    "other_rules": []
  }
}
```

## 输出结构

最终返回只包含：

```json
{
  "agreeCount": "0",
  "highlevelriskCount": "0",
  "mediumlevelriskCount": "0",
  "lowlevelriskCount": "0",
  "output": []
}
```

`output` 每项只包含：

```json
{
  "rule_code": "",
  "risk": "high/medium/low/pass",
  "risk_label": "高风险/中风险/低风险/通过",
  "action_type": "manual/replace/insert/append",
  "key": "",
  "tip": "",
  "content": "",
  "advice": "",
  "replace_text": ""
}
```

顶层统计字段始终是字符串，并会根据 `output[].risk` 重新统计。

## 测试示例

```python
import asyncio
from contract_audit_workflow import audit_contract


contract_text = """
采购合同
甲方向乙方采购设备一批，双方约定货物名称、数量、价款及交付方式。
付款、验收、质保及违约责任按合同约定执行。
"""


async def main():
    result = await audit_contract(contract_text)
    assert isinstance(result["output"], list)
    for key in (
        "agreeCount",
        "highlevelriskCount",
        "mediumlevelriskCount",
        "lowlevelriskCount",
    ):
        assert isinstance(result[key], str)
    print(result)


asyncio.run(main())
```

该示例需要 `.env` 中已配置可用的 MiniMax 模型和规则接口。

本地最小验证脚本：

```powershell
python -B contract_audit_workflow\validate_audit_workflow.py
```

该脚本会构造 3 条不同 `rule_code` 的规则，并让它们返回完全相同的审查内容，用于验证：

- 相同结果不会被合并；
- `output.length == 3`；
- 每条结果保留自己的 `rule_code`；
- 统计字段求和等于 `output.length`；
- `risk`、`risk_label`、`action_type` 和字段完整性满足当前输出协议。

当前脚本还覆盖：

- 全部通过场景；
- 高/中/低/通过混合场景；
- 财务、法务、履约三模块汇总场景；
- 通过项默认字段场景；
- `manual/append/insert/replace` 四类 `action_type` 场景；
- 空规则场景；
- 空字符串输入场景。

## 依赖建议

当前实现仅使用 Python 标准库，无强制新增依赖。

后续如果希望增强可维护性，可以考虑新增：

```text
python-dotenv：读取 .env
httpx：异步 HTTP 请求
langchain：统一模型编排
```

如需引入，请先更新项目依赖文件。

## 当前限制

1. 只实现合同审查工作流，未实现合同比对工作流。
2. 未接入 FastAPI、Flask 或其他后端路由。
3. `clean_contract_text` 暂时等于原始 `input`，未做额外清洗。
4. `other_rules` 不单独进入 LLM 审查，只用于最终 `rule_code` 匹配或预留扩展。
5. 规则接口失败时会抛出可排查错误，不会伪造审查结果。
6. LLM 审查结果数量必须与输入规则数量一致，否则会抛出错误，避免用默认结果冒充真实审查。
