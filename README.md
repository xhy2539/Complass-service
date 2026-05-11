# 合规罗盘后端服务

合规罗盘后端提供合同上传解析、Coze 风险审查、合同版本比对、风险点人工确认和任务查询接口。

## 当前能力

- 用户注册、登录和 Bearer Token 鉴权
- 单合同上传审查：`POST /api/v1/reviews`
- 双版本合同上传比对：`POST /api/v1/comparisons`
- `docx` / `pdf` / `txt` 文本解析、段落拆分、句子拆分和位置记录
- Coze 合同审查工作流接入：先上传文件，再传 `file_id` 调用 workflow
- Coze 合同比对工作流接入：传 `old_version_text` 和 `new_version_text`
- Coze 外层 `data` 字符串 JSON 自动解析
- 风险点保存、查询、确认和忽略
- 审查任务和比对任务列表查询

## 技术栈

- Python 3.11+
- FastAPI
- SQLAlchemy
- Pydantic Settings
- MySQL / SQLite
- Coze Workflow API

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

`COZE_ACCESS_TOKEN` 只写入本地 `.env`，不要提交到 Git。

## 主要接口

### 认证

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
```

### 单合同审查

```http
POST /api/v1/reviews
GET /api/v1/reviews/{task_id}
GET /api/v1/reviews
```

### 合同版本比对

```http
POST /api/v1/comparisons
GET /api/v1/comparisons/{task_id}
GET /api/v1/comparisons
```

### 风险点人工确认

```http
PATCH /api/v1/risks/{risk_id}/status
GET /api/v1/risks/{risk_id}
```

### Coze 联调接口

```http
POST /api/v1/coze/contract/comparison
POST /api/v1/coze/contract/review
```

完整字段说明见 `API接口文档-P0.md`。
