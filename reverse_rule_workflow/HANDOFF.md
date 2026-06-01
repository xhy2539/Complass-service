# Reverse Rule Workflow Handoff

这份目录是给后端仓库使用的工作流交接包。它从当前工作目录整理而来，只包含建议提交到后端仓库的源码、测试、知识库数据、接口入口和接入说明。

## 建议提交的目录结构

```text
reverse_rule_workflow/
  app/
    api/
    chains/
    kb/
    models/
    services/
    main.py
    prompts.py
  data/
  docs/
  scripts/
  storage/
    reverse_rule_kb/
      index.json
  tests/
  .env.example
  .gitignore
  HANDOFF.md
  README.md
  pytest.ini
  requirements.txt
```

建议把本目录整体复制到后端仓库中的 `reverse_rule_workflow/` 目录下。第一版先作为独立子模块提交，等后端仓库合并后，再根据后端现有包结构决定是否重命名包路径。

## 不要提交的内容

以下内容不应该进入后端仓库：

```text
.env
__pycache__/
*.pyc
.pytest_cache/
.pytest-tmp/
pytest-cache-files-*/
test-tmp/
storage/test_*/
storage/reverse_rule_kb/*.tmp
storage/reverse_rule_kb/write_probe.txt
```

本交接包已经跳过了这些缓存和临时文件。

## 工作流入口

核心 Python 调用入口：

```python
from app.chains.reverse_rule_graph import run_reverse_rule_extraction

result = run_reverse_rule_extraction(
    [
        {
            "pair_id": "pair-1",
            "before_text": "修改前条款",
            "after_text": "修改后条款",
            "contract_type": "服务合同",
            "review_role": "乙方",
        }
    ]
)
```

FastAPI 入口：

```python
from app.main import app
```

当前已暴露接口：

```http
POST /reverse-rule/extract
```

请求体是 `ContractPair[]`，响应体是 `FinalRuleResult`。更详细的输入输出见：

```text
docs/reverse_rule_workflow_io.md
```

## 在后端仓库中的接入方式

### 方式一：先作为独立子项目提交

这是风险最低的方式。把本目录复制到后端仓库：

```text
backend/
  reverse_rule_workflow/
    app/
    tests/
    ...
```

验证时进入该目录运行：

```powershell
cd reverse_rule_workflow
python -m pytest -q
```

如需单独启动接口：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 方式二：挂到现有 FastAPI 后端

如果后端也是 FastAPI，可以先在后端启动代码中挂载这个 router：

```python
from reverse_rule_workflow.app.api.reverse_rule import router as reverse_rule_router

app.include_router(reverse_rule_router)
```

如果后端已有顶层 `app` 包，直接提交本目录里的 `app/` 可能和后端已有包名冲突。遇到这种情况，建议后续再统一重命名为类似：

```text
reverse_rule_workflow/reverse_rule/
```

并把源码里的 import 从 `app.xxx` 调整为 `reverse_rule.xxx`。第一版交接包先不做这个重构，以减少行为变化。

## 环境变量

复制 `.env.example` 为 `.env` 后填入真实配置。`.env` 不要提交。

```text
LLM_PROVIDER=minimax
MINIMAX_API_KEY=replace-with-your-minimax-key
LLM_MODEL_NAME=MiniMax-M2.7
MINIMAX_BASE_URL=https://api.minimax.io/v1
```

如果不配置真实 LLM，工作流会走 fallback/stub 逻辑，测试仍可运行。

## 知识库数据

源数据：

```text
data/reverse_rule_cases.jsonl
```

构建脚本：

```powershell
python scripts/build_reverse_rule_kb.py
```

默认构建产物：

```text
storage/reverse_rule_kb/index.json
```

本交接包包含了当前的 `index.json`，这样搬到后端后可以先直接运行。后续如果不想提交生成物，可以只保留 `data/` 和 `scripts/`，由部署流程构建。

## 推仓库建议

在后端仓库中使用新分支：

```powershell
git checkout -b feature/reverse-rule-workflow
```

复制本目录内容到：

```text
backend/reverse_rule_workflow/
```

提交前检查：

```powershell
git status
```

确认没有 `.env`、`__pycache__`、`*.pyc`、测试缓存和临时目录后再提交：

```powershell
git add reverse_rule_workflow
git commit -m "Add reverse rule workflow"
git push -u origin feature/reverse-rule-workflow
```

然后创建 PR/MR，不建议直接推主分支。

## 当前已验证

在原工作目录中已验证：

```text
python -m pytest -q
39 passed
```

并验证过接口测试：

```text
python -m pytest tests/test_reverse_rule_api.py -q
1 passed
```

