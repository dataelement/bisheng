# 合并前局部验证（2026-11-02）

本次按用户要求，将模板租户隔离与共享工作区其他修复一起提交，再合入 3.0 和 release。未运行全量测试、未部署。

- 模板、MCP schema、管理视图中间件相关后端测试：61 passed。
- 前端 10 个相关文件：57 passed、4 failed。4 项失败均在 `hostedAppMenuTrim.test.tsx`；独立 worktree 的远端基线 `0b3df5ce15` 复跑同文件，也是 4 failed / 3 passed，已确认这些失败在本次改动之前存在。
- 当前修改范围 Ruff、ESLint、架构守卫及 whitespace 检查通过；架构守卫保留助手 endpoint 的既有 ORM 导入 WARNING，无 VIOLATION。
- 修复先前记录的 `AssistantSetting.tsx:58` TS2322：明确接口原始词表类型为 `unknown[]`，转换后为 `number[]`；该文件严格语义检查通过。此结果不代表全仓 typecheck 已通过。
- 模板真实部署 E2E、页面实机、中央双库验证仍待执行，沿用 `e2e-report.md` 的限制，不把未执行或跳过项记为通过。
