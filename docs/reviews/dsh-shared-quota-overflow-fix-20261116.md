# DSH 共享额度累加越界修复与验证

日期：2026-11-16。目标分支：`feat/3.1.0-beta1`。验证基线：`69d0d51ec4`。

## 问题与实现

未命中启用积分规则时，个人额度为表示不限额的 int64 上限。`UnifiedPolicyRepository.effective` 将同一份个人额度附在各可见模型行上；自动恢复却把这些行相加，两个模型就会将 Redis `gate.limit` 写成 `18446744073709551614`。读取 Lua 拒绝该值并返回 `bad_counter`。有限额度也会被错误放大。

- 自动恢复直接使用 SQL 策略快照的 `shared_token_limit`，每个模型引用同一额度。
- 恢复后的 gate 标记 `quota_limit_schema=shared`。健康检查识别旧格式、总额度格式/范围错误及模型额度不一致，按已有租约和冻结机制执行恢复。
- 共享格式读取不再校验“模型额度之和等于个人额度”，改为校验每个模型引用个人额度；已用量仍须与各模型消耗之和一致。
- 共享格式剩余量为 `max(limit - used, 0)`；无自动恢复的受控旧格式仍保留原读取协议。
- 恢复复用 SQL 与存活 Redis 请求的证据合并，并保留已有模型消耗。不会重置已用量，也不改变不限额、显式零额度或月度总消耗准入语义。

不涉及数据库表结构、对外接口字段、用户认证、可见性权限或供应商调用参数。

## 已知坑与发布边界

旧格式即使数字尚未越界，也需要恢复一次，才能消除有限额度重复累加。不能仅把越界数值截断到 int64 上限，否则有限额度仍不正确。

后端与 worker 应使用同一修复版本；旧读取 Lua 仍要求模型额度相加，不能将新共享账本视为旧协议运行。升级后按用户首次访问触发已有恢复流程，不另加 SQL 数据回填或删除 Redis 账本操作。仍需 SQL 权威快照与存活证据一致；证据冲突按现有机制拒绝恢复，不虚构已用量。

本次只推送源码，没有部署到 109 或客户环境。客户任务截图缺少底部原始异常，本修复针对已复现的 `bad_counter`，不宣称已完成该任务故障的现场验收。

## 验证

本机独立 Redis 7.2 容器（AOF、noeviction）执行真实 Lua；SQL 恢复使用 SQLite 与真实 Repository。没有连接业务 Redis。

专项命令（另设 `DSH_TEST_REDIS_ISOLATED=1` 和专用 `DSH_TEST_REDIS_URL`）：

```bash
python -m pytest \
  test/dsh/test_shared_quota_recovery.py \
  test/dsh/test_quota_admission.py \
  test/dsh/test_quota_settlement.py \
  test/dsh/test_quota_maintenance.py \
  test/dsh/test_quota_safety_review.py \
  test/dsh/test_unified_credit_ledger.py \
  test/dsh/test_chat_credits.py -q
```

结果：**71 passed**，含新增 **27** 项回归。覆盖 0/1/2/6 个模型、有限/零/不限额、旧格式和越界格式迁移、已结算消耗保留、RUNNING/USAGE_UNKNOWN 请求保留、非法额度和模型额度不一致、真实 SQL 策略与持久化消耗恢复，以及共享额度耗尽拒绝。

扩大选择另含 `test_model_quota.py`、`test_model_policy_rows.py`、`test_unified_policy_repository.py`，对前 24 个新增用例进行相同代码基线/环境/选择比较：

| 结果 | 修复前 | 修复后 |
| --- | ---: | ---: |
| passed | 56 | 74 |
| failed | 26 | 8 |
| error | 3 | 3 |
| skipped | 1 | 1 |

18 个本缺陷用例由失败转为通过，逐项比较无新增失败。8 个已有失败涉及旧按模型额度语义、SQL 测试缺少 user 表及租户/角色测试基线；3 个已有 error 是外部数据库测试未配置专用 MySQL。扩大选择不是全绿，不能据此宣称全量回归通过。

Ruff format/check、`git diff --check` 和修改文件的 arch-guard 通过。未执行 MySQL/DM8 全量及真实客户业务 UI 验收。

## 范围审查

按 `sdd-code-review` 七维清单执行小修复审查：边界、权限认证、并发恢复、信息泄漏、测试覆盖、代码风格、文档同步均未发现本次新增的阻断问题。复用原租约、CAS 和租户范围；新增数字范围检查与 Lua 一致。验证范围限制见上表，结论为 **PASS_WITH_WARNINGS**。
