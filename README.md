# 合规罗盘后端服务

合规罗盘是一个轻量级合同 AI 风险初筛与审查工具。
当前仓库只完成后端工程初始化和 FastAPI 脚手架搭建，业务功能后续再逐步开发。

## 当前进度

当前阶段只做基础后端骨架，不进入合同审查业务实现。
当前 CI 先校验依赖安装和 Python 语法，业务测试在接口实现后补充。

已包含：

- FastAPI 应用入口和健康检查
- 版本化 API 聚合入口
- 合同审查、版本比对、人工确认路由模块占位
- 环境变量配置入口
- requirements.txt 依赖清单
- Python 常见缓存和测试产物忽略规则

后续再开发：

- 单合同上传和审查接口
- 双版本合同上传和比对接口
- txt/docx/pdf 文本解析
- 后端脱敏网关
- Coze workflow 接入
- 风险点人工确认/忽略状态
- PostgreSQL 持久化表结构
- IM Bot 接入
- 私有规则库和历史合同逆向建模
- 企业背景自动注入
- 多模型智能路由
- 自动改文或一键回写合同

## 技术栈

- Python 3.11+
- FastAPI
- Pydantic Settings
- Uvicorn

数据库建议：

- 本地开发：先不强制连接数据库，后续可用 SQLite 降低启动成本。
- 生产方向：推荐 PostgreSQL，适合存储 AI JSON 结果、规则参数、审查记录、状态流转和后续全文检索。

## 目录结构

```text
app/
  api/v1/
    contract_review_routes.py          # 单合同审查路由占位
    contract_comparison_routes.py      # 双版本比对路由占位
    risk_manual_decision_routes.py     # 风险点人工确认路由占位
    contract_review_api.py             # 合同审查 API 聚合入口
  core/
    complass_service_settings.py       # 合规罗盘服务配置
  schemas/
    __init__.py                        # 后续放合同审查请求/响应结构
  services/
    __init__.py                        # 后续放解析、脱敏、AI、比对等服务
```

## 本地启动

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

启动后访问：

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 环境变量

`.env.example` 提供了当前需要的配置模板：

```env
APP_ENV=local
DATABASE_URL=sqlite:///./complass.db
COZE_API_BASE_URL=https://api.coze.cn
COZE_API_TOKEN=
COZE_WORKFLOW_ID=
COZE_MOCK_ENABLED=true
MAX_UPLOAD_SIZE_MB=20
```

当前代码未接入 Coze。后续接入真实 Coze 时，后端只应发送脱敏后的结构化合同内容，不发送原始合同文件。

## 当前 API

### 健康检查

```http
GET /health
```

## 后续规划 API

以下接口只作为 PRD 后续开发方向，当前脚手架尚未实现。

### 创建单合同审查

```http
POST /api/v1/reviews
Content-Type: multipart/form-data
file=<contract.txt|contract.docx>
```

### 创建双版本比对

```http
POST /api/v1/comparisons
Content-Type: multipart/form-data
old_file=<old_contract.txt|old_contract.docx>
new_file=<new_contract.txt|new_contract.docx>
```

### 查询审查结果

```http
GET /api/v1/reviews/{task_id}
```

### 人工更新风险状态

```http
PATCH /api/v1/risks/{risk_id}/status
Content-Type: application/json

{
  "status": "confirmed"
}
```

合法状态：

- `pending`：待处理
- `confirmed`：已确认
- `ignored`：已忽略

所有 AI 风险点默认都应是 `pending`，必须由人工操作后才能变更状态。

## 后续按 PRD 推进

1. 接入真实 Coze workflow，并校验返回 JSON 结构。
2. 增加 PostgreSQL 持久化和迁移脚本。
3. 完善版本比对定位与 Web 高亮所需坐标。
4. 接入 IM Bot，复用现有审查任务服务。
5. 建设私有规则库和历史合同逆向建模能力。
