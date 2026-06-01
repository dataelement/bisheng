# org_sync provider-pull 移除范围清单（含缺失模块 DepartmentSyncRBACService）

> 背景：用户/部门同步已改为 gateway 推送接口（`sso_sync` 模块）。旧的 provider-pull 同步
> （`org_sync` 模块）中 `org_sync_service.py` 依赖一个**从未提交的** `department_sync_rbac_service.py`
> （commit `68c50bac4` 漏 `git add`）。本清单给出可移除/必须保留的精确边界。

---

## 核心结论

1. **缺失模块 `DepartmentSyncRBACService` 的唯一引用者就是 `org_sync_service.py`**（`OrgSyncService`）。
2. `OrgSyncService` 仅被 `worker/org_sync/tasks.py` 一处惰性 import → 移除它**只影响 provider-pull「主动全量/增量同步」这一条路径**。
3. **但 `org_sync` 模块不能整体删**：其 `models` / `ts_guard` / `reconcile` 链路 / `providers` / `relink` 仍被
   **gateway（sso_sync）** 和 **仍在运行的 reconcile beat 任务**复用。
4. 所以「消除坏 import」是个**小而干净**的动作（Tier A）；「整体退役 provider-pull」则**纠缠较深**（Tier C 需产品决策）。

---

## Tier A — 可安全移除（消除坏 import，旧 provider-pull 主动同步路径）

移除后坏 import 彻底消失，且经核实无其他模块依赖：

| 文件 / 位置 | 说明 |
|------|------|
| [org_sync_service.py](src/backend/bisheng/org_sync/domain/services/org_sync_service.py) | `OrgSyncService` 全类。**唯一**引用缺失 `DepartmentSyncRBACService` 者；仅被 worker task 引用 |
| [worker/org_sync/tasks.py](src/backend/bisheng/worker/org_sync/tasks.py) 中 `execute_org_sync` / `_execute_org_sync_async` / `check_org_sync_schedules` | 主动同步 Celery 任务 + 60s cron 调度器（派发 `execute_org_sync`） |
| [sync_exec.py](src/backend/bisheng/org_sync/api/endpoints/sync_exec.py) | 手动触发主动同步的端点（`execute_org_sync.apply_async`） |
| [settings.py:205-207](src/backend/bisheng/core/config/settings.py#L205) | beat 注册 `check_org_sync_schedules`（删任务则删注册） |
| [worker/__init__.py:15](src/backend/bisheng/worker/__init__.py#L15) | `from ...org_sync.tasks import check_org_sync_schedules, execute_org_sync` |
| [test/test_org_sync_service.py](src/backend/test/test_org_sync_service.py) | 该测试随 `OrgSyncService` 一并删除 |

> ⚠️ 前置确认：`worker/org_sync/tasks.py` 若**仅**含这两个任务，可整文件删；若还有他用任务则只删函数。
> 语义影响：provider-pull 的「拉取并创建成员 + 按部门分配默认角色」能力消失——而这正是 gateway 现在负责的，符合迁移现状。

---

## Tier B — 必须保留（被 gateway / live reconcile 复用）

| 文件 | 被谁复用 |
|------|---------|
| [domain/models/org_sync.py](src/backend/bisheng/org_sync/domain/models/org_sync.py)（OrgSyncConfig + 日志 DAO） | gateway 的 [org_sync_log_writer.py:30](src/backend/bisheng/sso_sync/domain/services/org_sync_log_writer.py#L30)、reconcile、sync_gateway_logs |
| [domain/services/ts_guard.py](src/backend/bisheng/org_sync/domain/services/ts_guard.py) | gateway 的 [departments_sync_service.py:30](src/backend/bisheng/sso_sync/domain/services/departments_sync_service.py#L30) + reconcile_service |
| reconcile_service.py / [worker/org_sync/reconcile_tasks.py](src/backend/bisheng/worker/org_sync/reconcile_tasks.py) | beat `reconcile_all_organizations`（6h，[settings.py:226](src/backend/bisheng/core/config/settings.py#L226)）；**不依赖缺失模块** |
| reconciler.py / remote_dept_differ.py / ts_conflict_reporter.py | reconcile 链路内部依赖 |
| domain/providers/*（wecom/dingtalk/feishu/generic_api/base） | reconcile_service 通过 `get_provider` 使用 |
| relink_service.py / relink_conflict_store.py / [api/endpoints/relink.py](src/backend/bisheng/org_sync/api/endpoints/relink.py) | gateway HMAC relink（`sso_sync.hmac_auth`） |
| [api/endpoints/sync_gateway_logs.py](src/backend/bisheng/org_sync/api/endpoints/sync_gateway_logs.py) | 同步日志查看（仅用 OrgSyncLogDao） |
| domain/schemas/* / constants.py / errcode | 上述路径共用 |

---

## Tier C — 取决于产品决策（provider-pull 是否整体退役）

这些只在「provider-pull 完全不要了」时才可删，但目前仍被 live reconcile 牵连：

| 项 | 牵连点 |
|----|--------|
| [sync_config.py](src/backend/bisheng/org_sync/api/endpoints/sync_config.py)（OrgSyncConfig CRUD 端点） | `reconcile_all_organizations` 仍迭代 OrgSyncConfig；只要 reconcile 在，配置管理就得留 |
| domain/providers/* | 同上，reconcile_service 仍 `get_provider` 拉取 |
| reconcile 整条链路 + `reconcile_all_organizations` beat | 若 gateway 已能完全替代「6h 兜底对账」，可一并退役；否则保留 |

**关键待确认问题 ★**：gateway 推送是否已**完全替代** provider-pull 的「6h 强制 reconcile 兜底」（`reconcile_all_organizations`）？
- 若是 → Tier C 也可删，provider-pull 整体退役，连 `providers/` 都能清掉；
- 若否（reconcile 作为 gateway 漏推的安全网保留）→ 只做 Tier A，其余保留。

---

## 推荐执行

- **第一步（无争议，建议先做）**：执行 **Tier A**，消除坏 import、修复 Celery 主动同步崩溃风险与测试收集失败。语义上与「同步已迁移到 gateway」一致。
- **第二步（需你确认 ★）**：回答上面的 reconcile 关键问题，再决定是否推进 Tier C。
- **备选**：若出于稳妥想保留 provider-pull 主动同步，则不删 Tier A，改为找作者 RUCYancy 补回 `department_sync_rbac_service.py`。
