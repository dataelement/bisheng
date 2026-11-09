# 企业云端工作台集成任务

依据：[spec.md](./spec.md) · [design.md](./design.md)。本文件记录 2026-11-09 的修复和集成，不补造历史批准记录。

- [x] T1：检查 PR #2595 `b45d8258d3` 的目录、访问、源码导出、发布和 SDK 实现，补记 spec/design。覆盖 AC-01 至 AC-08。
- [x] T2：补齐 QA 八列参考用例和真实环境验收清单；实际执行结果另记。覆盖 AC-01 至 AC-08。
- [x] T3：runtime-manager 锁定环境全套 1861 passed / 90 skipped；代理全套 279 passed；SDK 全套 218 passed。后端工作台/发布/dev_toolkit 专项 156 passed；最终组合后端 211 项、完整前端 lint/typecheck/i18n、Platform 16 项与 Client 5 项通过。
- [x] T4：两个 PR 修复后完成组合验证，#2646 合并提交 7486f74、#2595 合并提交 014da820；#2595 最终 8 项远端检查全部通过。
- [x] T5：Drone #6044 全部成功，014da820 对应固定 digest 的后端、worker 和前端已部署至指定环境。数据库升级至 f130_cloud_workbenches，页面/API/反馈能力发现、未认证拒绝、worker ping 和 Nginx 检查通过；其他容器 ID 未变化。

## 实际偏差记录

- 本轮补记已实现设计，不新增产品决策；部署范围由用户明确指定 work-130 / 109:13001。

## 验证记录

上一轮评审的后端专项 45 项、代理 6 项、SDK 6 项通过。本轮修复与集成后以新结果替换，不能将此前结果当成新组合提交验收。

### CI 基线修复

runtime-manager 测试替身缺少 authorize_step/preflight、Pod 日志读取错误地再次执行维护、v1 对账循环/路由图断言过时，已按当前协议修正，保留撤销和清理断言。另补齐实际 image-check 容器的日志白名单，之前会抛 k8s_log_container_invalid；test_k8s_client 使用真实 PodPlan 覆盖该容器，完整回归通过。

### 部署验证范围

原环境 open_platform.enabled 与 app_runtime.enabled 均关闭，保持原配置。开发工具 HTTP 分发因此按既有合同返回 404；镜像内指南、SDK 0.1.1/0.1.2 及工作台/反馈源码摘要与最终源码一致。镜像部署和基础冒烟已完成，不代表启用了完整云端运行时或完成真实 Desktop 双用户发布、审批和协作验收。QA 参考用例保留待执行。
