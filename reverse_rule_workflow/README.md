# 逆向解析规则案例知识库

这是合同审核规则逆向解析 MVP 的 few-shot 案例知识库。它只保存“修改前条款、修改后条款、修改差异、用户修改意图、可入库审核规则字段”的案例，不保存用户合同，不提供法律依据，也不生成最终审核规则。

## 构建知识库

```bash
python scripts/build_reverse_rule_kb.py
```

构建产物位于：

```text
storage/reverse_rule_kb/index.json
```

构建脚本可重复执行，会根据 `data/reverse_rule_cases.jsonl` 覆盖本地索引。

## 检索示例

```python
from app.kb.retriever import retrieve_reverse_rule_cases

cases = retrieve_reverse_rule_cases(
    "用户把付款期限从90日改成30日，并要求收到合法有效发票后付款",
    review_module="付款条款",
    contract_type="服务合同",
    review_role="乙方",
    k=3,
)
```

也可以获取 LangChain Retriever：

```python
from app.kb.retriever import get_reverse_rule_retriever

retriever = get_reverse_rule_retriever(k=3)
documents = retriever.invoke("知识产权归属和既有技术保留")
```

## 测试

```bash
pytest tests/test_reverse_rule_kb.py -v
```

本 MVP 使用确定性的中文字符 n-gram/hash embedding，不调用真实收费模型，也不依赖 FAISS 或 Chroma。
