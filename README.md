# 合规罗盘后端服务

合规罗盘后端是基于 FastAPI 的合同审查服务，提供用户认证、合同上传解析、Coze 风险审查、合同版本比对、风险点人工复核、任务查询和审查结果导出能力。

## 当前能力

- 用户注册、登录和 Bearer Token 鉴权
- 单合同上传审查：解析 `docx` / `pdf` / `txt`，保存段落、句子和风险定位信息
- 双版本合同上传比对：生成句子级 diff，并可调用 Coze 进行语义增强
- Coze 合同审查工作流接入：先上传文件获取 `file_id`，再调用审查 workflow
- Coze 合同比对工作流接入：基于 `old_text`、`new_text`、`diff_stats`、`diff_texts` 生成增强结果
- Coze 外层 `data` 字符串 JSON 自动解析和结果归一化
- 风险点保存、查询、确认、忽略和人工复核备注
- 审查任务、比对任务、任务风险点列表查询
- 基于用户编辑后的最终合同文本导出清洁版 `docx`
- Jenkins Verify 流水线检查：依赖安装、语法检查、应用导入检查

## 技术栈

- Python 3.11+
- FastAPI
- SQLAlchemy
- Pydantic Settings
- MySQL / SQLite
- Coze Workflow API
- Jenkins / Gerrit Trigger

## 项目结构

```text
app/
  api/v1/                 # API 路由
  core/                   # 配置和安全能力
  models/                 # SQLAlchemy 数据模型和数据库连接
  schemas/                # 请求和响应模型
  services/               # 文档解析、Coze 调用、diff 和导出服务
alembic/                  # 数据库迁移目录
requirements.txt          # Python 依赖
Jenkinsfile               # Jenkins Verify 检查流水线
```

## 本地启动

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

启动后访问：

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 环境变量

`.env.example` 提供配置模板：

```env
APP_ENV=local
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/complass?charset=utf8mb4
COZE_API_BASE_URL=https://api.coze.cn
COZE_ACCESS_TOKEN=
COZE_COMPARISON_WORKFLOW_ID=7634842444869861416
COZE_REVIEW_WORKFLOW_ID=7636289402251198473
COZE_WORKFLOW_TIMEOUT_SECONDS=120
COZE_UPLOAD_TIMEOUT_SECONDS=120
MAX_UPLOAD_SIZE_MB=20
JWT_SECRET_KEY=your-super-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080
```

`COZE_ACCESS_TOKEN` 和生产环境 `JWT_SECRET_KEY` 只写入本地或服务器 `.env`，不要提交到 Git。

## 主要接口

所有业务接口统一挂载在 `/api/v1` 下。除注册、登录和 Coze 联调预留接口外，业务任务接口需要携带 Bearer Token。

### 认证

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
```

### 单合同审查

```http
POST /api/v1/reviews
GET /api/v1/reviews
GET /api/v1/reviews/{task_id}
GET /api/v1/reviews/{task_id}/risks
POST /api/v1/reviews/{task_id}/export
```

说明：

- `POST /reviews` 上传单份合同文件，支持 `docx`、`pdf`、`txt`
- `use_coze=true` 时会调用 Coze 审查工作流并保存风险点
- `POST /reviews/{task_id}/export` 根据前端提交的最终合同文本导出 `docx`

### 合同版本比对

```http
POST /api/v1/comparisons
GET /api/v1/comparisons
GET /api/v1/comparisons/{task_id}
GET /api/v1/comparisons/{task_id}/risks
```

说明：

- `POST /comparisons` 上传旧版和新版合同文件
- `enhance=true` 时会调用 Coze 比对增强工作流
- 返回内容包含 diff 统计、差异明细、合同文档信息和比对风险点

### 风险点人工确认

```http
PATCH /api/v1/risks/{risk_id}/status
GET /api/v1/risks/{risk_id}
```

支持的风险状态：

```text
pending
confirmed
ignored
```

### Coze 联调预留接口

```http
POST /api/v1/coze/contract/comparison
POST /api/v1/coze/contract/review
```

这些接口用于单独联调 Coze 工作流。正式业务流程优先使用 `/reviews` 和 `/comparisons`。

## CI / Gerrit Verify

项目包含 `Jenkinsfile`，用于 Gerrit Patch Set 的 Verify 检查：

1. 创建 Python 虚拟环境
2. 安装 `requirements.txt`
3. 执行 `python -m compileall -q app`
4. 执行 `python -c "from app.main import app; print(app.title)"`

提交到 Gerrit 测试流水线：

```bash
git push origin HEAD:refs/for/dev
```

Jenkins 由 Gerrit Trigger 触发后，应在 Gerrit Change 页面回写 `Verified +1` 或 `Verified -1`。

完整字段说明见 `API接口文档-P0.md`。
