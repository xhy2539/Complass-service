# 合规罗盘 (Complass) — 后端服务

AI 辅助合同审查工作台。提供单合同风险审查、版本比对、和从修改行为中反向提炼审核规则的
逆向解析引擎，内置 RAG 语义检索和敏感信息脱敏。

## 功能模块

| 模块 | 说明 |
| ------ | ------ |
| 合同审查 | 上传合同 → AI 分析 → 风险点列表 → 人工确认 |
| 版本比对 | 上传新旧合同 → diff 识别 → Coze 语义增强 |
| 规则逆向 | 修改前后合同对 → LLM + KB → 候选审核规则 → 纳入入库 |
| 脱敏服务 | 公司名/电话/邮箱/身份证等 7 类敏感信息过滤+还原 |
| RAG 检索 | bge-base-zh + FAISS + BM25 + MiniMax re-rank 混合检索 |
| DOCX 导出 | 原始模板文本替换，保留全部格式 |

详细使用说明见 [docs/USER_MANUAL.md](docs/USER_MANUAL.md)

## 部署

```bash
cp .env.example .env
# 编辑 .env 填入 COZE_ACCESS_TOKEN / MINIMAX_API_KEY 等
docker compose up -d

# 首次构建 RAG 索引
curl -X POST http://localhost:8000/rebuild
```

服务端口：

| 服务 | 端口 | 说明 |
| ------ | ------ | ------ |
| 前端 Nginx | 80 | SPA + API 代理 |
| 后端 FastAPI | 8080 | 业务逻辑 |
| RAG 服务 | 8000 | 语义检索（仅本地） |
| MySQL | 3306 | 业务数据 |
| Redis | 6379 | 会话缓存 |

## 技术栈

Python 3.12 / FastAPI / SQLAlchemy / MySQL 8.0 / Redis 7 / Coze / MiniMax M3
/ bge-base-zh-v1.5 / FAISS / BM25 / Docker / Jenkins / Gerrit

## CI/CD

每次推送自动触发 Jenkins 流水线：Lint → Format → Type Check → Test (28 cases) → Syntax → Import。
合并后自动部署。
