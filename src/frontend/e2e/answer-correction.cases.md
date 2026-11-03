# F119 浏览器验收

| 编号 | 前置条件 | 步骤 | 预期 |
|---|---|---|---|
| UI-119-01 | 隔离环境已准备可纠错的历史回答、应用负责人和可受派的知识库维护人员。三者拥有对应页面入口。 | 用户提交原句及依据，负责人分派，维护人员记录结果，负责人回复，用户打开我的反馈。 | 每个角色从对应入口完成操作，用户看到该次回复。 |
| UI-119-02 | 用户有权打开一条来自未关联知识库应用的历史回答。 | 打开对话，等待纠错资格检查。 | 回答正常展示，逐句纠错入口隐藏。 |

使用后端功能用例同一份 `BISHENG_CORRECTION_SCENARIO`，另设置 `BISHENG_CORRECTION_CHAT_URL` 为工作台对话页，`BISHENG_CORRECTION_QUEUE_URL` 为管理端反馈队列。UI-119-02 另需 `BISHENG_CORRECTION_UNSUPPORTED_CHAT_URL`。通过 `pnpm exec playwright test -c e2e/playwright.config.ts e2e/answer-correction.spec.ts` 运行。
