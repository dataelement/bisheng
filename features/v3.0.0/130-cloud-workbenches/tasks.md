# 企业云端工作台集成任务

依据：[spec.md](./spec.md) · [design.md](./design.md)。本文件记录 2026-11-09 的修复和集成，不补造历史批准记录。

- [x] T1：检查 PR #2595 `b45d8258d3` 的目录、访问、源码导出、发布和 SDK 实现，补记 spec/design。覆盖 AC-01 至 AC-08。
- [x] T2：补齐 QA 八列参考用例和真实环境验收清单；实际执行结果另记。覆盖 AC-01 至 AC-08。
- [x] T3：runtime-manager 锁定环境全套 1861 passed / 90 skipped；代理全套 279 passed；SDK 全套 218 passed。后端工作台/发布/dev_toolkit 专项 156 passed；最终组合前端结果继续补记。
- [ ] T4：两个 PR 修复后复审，验证组合提交，合并到用户指定 work-130 分支。
- [ ] T5：跟进 Drone 对合并提交构建的镜像，备份并定向部署 109:13001，检查 API、页面、迁移和服务健康。

## 实际偏差记录

- 本轮补记已实现设计，不新增产品决策；部署范围由用户明确指定 work-130 / 109:13001。

## 验证记录

上一轮评审的后端专项 45 项、代理 6 项、SDK 6 项通过。本轮修复与集成后以新结果替换，不能将此前结果当成新组合提交验收。

### CI 基线修复

runtime-manager 测试替身缺少 authorize_step/preflight、Pod 日志读取错误地再次执行维护、v1 对账循环/路由图断言过时，已按当前协议修正，保留撤销和清理断言。另补齐实际 image-check 容器的日志白名单，之前会抛 k8s_log_container_invalid；test_k8s_client 使用真实 PodPlan 覆盖该容器，完整回归通过。
