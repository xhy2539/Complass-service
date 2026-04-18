# Complass-service

「合规罗盘」后端服务仓库（当前为初始化阶段），已内置 Jenkins Pipeline 配置，支持接入 Gerrit 触发持续集成。

## 仓库与 CI 地址

- Gerrit 仓库：`ssh://<你的工号>@gerrit.lilingkun.com:29418/Complass-service`
- Jenkins Job：`https://jenkins.lilingkun.com/job/Complass-service/`

## 已提供的流水线能力

仓库根目录已提供 `Jenkinsfile`，流水线默认包含以下阶段：

1. `Checkout`：拉取当前提交代码。
2. `Detect Build Tool`：自动识别 Maven/Gradle（`pom.xml` 或 `build.gradle*`）。
3. `Code Style Check`：执行代码风格/规范检查。
4. `Unit Test`：执行单元测试。
5. `Integration Test`：执行集成测试。
6. `Package`：执行打包（跳过重复测试）。
7. `Archive`：归档 `jar/war` 构建产物。
8. `Smoke Check`：当仓库尚未引入 Maven/Gradle 构建文件时，执行基础连通性验证并保持流水线成功。
9. `Checkout Fallback`：当任务以 `Pipeline script`（非 `from SCM`）方式运行导致 `checkout scm` 不可用时，自动降级到引导模式并走 `Smoke Check`。

流水线在构建结束后会尝试回投 Gerrit `Verified`：

- 成功：`Verified +1`
- 失败：`Verified -1`

> 说明：如果仓库暂时没有 `pom.xml` 或 `build.gradle*`，流水线会执行 `Smoke Check` 并保持成功，用于项目初始化阶段先打通 Gerrit + Jenkins 门禁。

## Jenkins 侧配置步骤（对接 Gerrit）

以下步骤针对现有 Job：`Complass-service`。

### 1) 凭据准备

在 Jenkins `Manage Jenkins -> Credentials` 中添加：

- 类型：`SSH Username with private key`
- 用户名：Gerrit 用户名（例如工号）
- 私钥：对应 Gerrit 账号已登记的私钥

同时确认 Jenkins 已安装并启用以下插件：

- `Gerrit Trigger`
- `Pipeline`
- `Git`

### 2) Job 配置（Pipeline from SCM）

在 `https://jenkins.lilingkun.com/job/Complass-service/configure` 中：

1. `Definition` 选择 `Pipeline script from SCM`
2. `SCM` 选择 `Git`
3. `Repository URL` 填：`ssh://<你的工号>@gerrit.lilingkun.com:29418/Complass-service`
4. `Credentials` 选择上一步新增的 SSH 凭据
5. `Branches to build` 推荐先填：`refs/heads/dev`
6. `Script Path` 填：`Jenkinsfile`

### 3) 触发器配置（Gerrit Trigger）

在 `Build Triggers` 启用 `Gerrit event`，建议最小配置：

- Gerrit Project：`Complass-service`
- Branch Pattern：`^refs/heads/dev$`
- 事件：
1. `Patchset Created`
2. `Change Merged`

### 4) 首次连通性验证

1. 向 `dev` 分支推送一次提交（或提交一个 patchset）。
2. 确认 Jenkins Job 自动触发。
3. 查看控制台日志是否完成 `Style -> Unit -> Integration` 检查链路。
4. 在 Gerrit 对应 Change 页面确认 `Verified` 已被 Jenkins 正确投票。

## Gerrit 合并门禁建议

根据你们课件要求，建议在 Gerrit 项目中设置以下合并条件：

1. `Code-Review` 至少有一个 `+2`，且没有 `-2`
2. `Verified` 必须为 `+1`

## 后续接入建议

1. 补齐后端工程脚手架（如 Spring Boot + Maven），让流水线从 `NOT_BUILT` 进入真实构建。
2. 增加静态检查（Checkstyle/SpotBugs）与代码覆盖率（JaCoCo）上报。
3. 根据部署环境增加 `Deploy` 阶段（测试环境/预发环境）。
