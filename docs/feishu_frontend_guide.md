# 飞书机器人 — 前端对接文档

## 背景

飞书用户在机器人中发送合同文件，机器人处理后返回前端工作台链接。用户点击链接后前端需根据 URL 参数跳转到对应任务详情。

## URL 格式

```
审查任务：{FRONTEND_BASE_URL}/?task_id={id}&view=review
比对任务：{FRONTEND_BASE_URL}/?task_id={id}&view=comparison

> `FRONTEND_BASE_URL` 通过 `.env` 的 `FRONTEND_BASE_URL` 配置，默认为 `http://82.156.132.43`
```

## 前端需要做的

在 `App.tsx` 初始化时（`useEffect` / `onMount`）读取 URL 参数：

```
1. 从 window.location.search 解析 task_id 和 view
2. 如果 view === "review" → 调用 openReview(task_id)
3. 如果 view === "comparison" → 调用 openComparison(task_id)
4. 调用时 navigate=true，自动切换到对应视图
```

## 接口

前端已有的接口，不需要新增：

```
GET /api/v1/reviews/{task_id}      → openReview()
GET /api/v1/comparisons/{task_id}  → openComparison()
```

## 注意事项

- 任务创建后可能是 PENDING 状态，Coze 分析需要时间，前端已支持轮询就行
- URL 参数只触发一次跳转，不要反复刷新
- 未登录用户点链接 → 跳登录页 → 登录后再跳回任务详情
