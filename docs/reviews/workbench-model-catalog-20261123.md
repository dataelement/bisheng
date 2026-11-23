# Code Review Report

**Feature**: 工作台候选模型与超管跨租户模型调用一致
**Review scope**: 用户已确认的两项缺陷修复：候选不受 DSH 开关影响；超管切换后能使用目标租户的合法模型
**Base branch**: origin/feat/3.1.0-beta2（23c82f7769）
**Work branch**: codex/beta2-workbench-model-catalog-20261123

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## Behavior and boundaries

- 候选统一枚举目标租户自有和 Root 实际共享的在线对话模型；工作台配置中的 models 仅提供展示元数据。缺省可见范围为全员可见，与 DSH 开关无关。
- 超管展示和执行均可使用上述合法模型；执行通过已有当前资格入口重新核验，不把管理租户标记、客户端布尔值或普通角色当作超管授权。HTTP 已准入身份复用请求快照；Worker 重新读取当前资格。
- model_access.require_model_operator 同时验证用户、主属成员关系和目标租户有效性。普通用户仍须实际属于执行租户；超管无需新增子租户成员记录。撤销资格、禁用用户/主属租户/目标租户后，目录和计费调用均拒绝。
- DSH 超管调用重新验证模型在线、所有权和实际共享；兄弟租户、未共享 Root、已下线模型被拒绝。普通用户仍按原可见范围、个人策略和额度处理。
- 管理调用沿现有 unmetered 路径记录目标租户、真实操作人、模型、价格和用量；不消费子租户成员个人额度。round probe 不写调用，付费模型不被改成免费。
- 首次调用/恢复账本只读目标租户的账本世代。外租户操作人的恢复快照不加载不存在的个人角色，返回模型授权为空、额度为零的元数据；该快照不是调用授权。个人政策查询 effective 保持原行为。
- DSH 桌面身份与票据继续使用原严格成员查询，不能借浏览器管理调用资格取得跨租户凭据。
- 未修改 Lua、结算状态机、表结构、迁移、发布脚本或供应商配置。没有为知识空间/频道图片配置的独立 10996 问题声明修复。

## Validation

在本开发工作区使用 Python 3.11 虚拟环境和 beta2 临时配置引导运行：

```sh
env -u config PYTHONPATH="$PWD" /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  test/dsh/test_super_model_execution.py \
  test/dsh/test_model_display_catalog.py \
  test/dsh/test_model_visibility_without_dsh.py \
  test/llm/test_user_model_visibility_execution.py \
  test/llm/test_workbench_model_providers.py \
  test/dsh/test_chat_credits.py \
  test/dsh/test_usage_repository.py \
  test/dsh/test_identity_records.py \
  test/dsh/test_identity.py \
  -k 'not real_redis_ticket and not ticket_does_not_outlive' \
  -q --disable-warnings --tb=short
```

结果：**67 passed，2 skipped，2 deselected**。跳过项为需外部隔离数据库的用例、新增真实 Redis 首次调用/恢复集成用例；两个票据用例需专用 Redis，未纳入本地命令。

新增回归使用实际 SQLite 用户/成员/租户/模型/可见范围/账本记录，覆盖日常会话初始化、发送时模型检查、任务模式解析、DSH 开关、同名模型、兄弟租户及未共享/下线模型拒绝、共享撤销、身份撤销、用户/租户禁用、资格服务不可用、实际价格及用量结算参数、目标账本恢复。资格服务与供应商/Redis 传输使用替身，不把模拟结果视为现场验收。

另复跑既有临时排查脚本中的四项检查（真实模型 SQL、工作流 run_once 的 DSH 两种模式、助手模型初始化），**4 passed**，没有发现回归；这些检查不是新增持久测试覆盖。

Ruff format/check、变更文件的 arch-guard 和 git diff --check 通过。测试密码使用随机夹具值。

## Baseline and infrastructure limitations

- 扩展运行 test_unified_policy_repository.py 时，两项原有测试失败：部门祖先匹配的旧预期、切到不存在的租户时的旧空目录预期。使用提交前 HEAD 的 UnifiedPolicyRepository 源码重新运行两项，均复现同样失败；未通过改普通用户政策掩盖它们。
- test_new_model_visibility.py 的提供商更新测试夹具缺少 knowledge_operation_plan 表，在既有 F118 删除预检查路径失败；本次没有修改该路径。
- 真实 Redis 的票据/共享额度恢复集成未配置；没有执行真实供应商请求、MySQL/DM8 集成或 116 部署验收。

## Overall: PASS

本次已验证的 Chat/Work 模型资格和超管计费身份阻断已修复；正式交付仍需在目标环境部署后验证真实对话与 Redis 账本。
