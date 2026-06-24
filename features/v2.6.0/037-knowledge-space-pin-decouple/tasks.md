# Tasks: 知识空间置顶与成员关系解耦

**关联**: [spec.md](./spec.md) · [design.md](./design.md)
**轨道**: Small feature（SDD 轻级）

---

## 执行记录（TDD，wave 顺序）

| # | 任务 | 产物 | 状态 |
|---|---|---|---|
| T1 | 新表模型 + DAO（pin/unpin/list_pinned_space_ids，幂等 upsert） | `bisheng/knowledge/domain/models/knowledge_space_user_pin.py` | ✅ |
| T2 | `pin_space` 改造：前置 `_require_read_permission` + 写置顶表 | `knowledge_space_service.py` | ✅ |
| T3 | 列表装配 `_format_accessible_spaces` / `_format_member_spaces` 改用 `pinned_ids` | `knowledge_space_service.py` | ✅ |
| T4 | 删除死代码 `SpaceChannelMemberDao.pin_space_id` | `common/models/space_channel_member.py` | ✅ |
| T5 | alembic 建表迁移（双DB幂等，挂 `f035_linsight_status_varchar`） | `versions/v2_6_0_f044_knowledge_space_user_pin.py` | ✅ |
| T6 | 测试 fixtures 注册新表 | `test/fixtures/table_definitions.py` | ✅ |
| T7 | 数据回填脚本（老 is_pinned → 新表，dry-run/--apply，幂等） + README | `scripts/backfill_knowledge_space_user_pin.py` | ✅ |

## 测试

- 新增 4 个测试文件（DAO / service / 列表装配 / 回填脚本），覆盖 AC1–AC7，12 passed。
- 回归核对：knowledge 与 channel 套件 worktree↔基线失败集**完全一致（零回归）**；剩余失败均为预存在环境问题（连真实 MySQL 的 `NoTenantContextError`）。
- ruff：新增文件全过；改动的既有文件 lint 数与基线一致（零新增）。

## 实际偏差记录

- T3 偏差：在 `_format_accessible_spaces` 等新增了真实 DB 调用 `list_pinned_space_ids`，导致 `test_knowledge_space_service.py::TestSpaceListings` 4 个既有用例（连真实 MySQL、只 mock 部分 DAO）失败 → 给这 4 个用例补 mock `KnowledgeSpaceUserPinDao.list_pinned_space_ids`，恢复基线。属新增协作者的合理测试更新，无设计偏差。
- 既有 RULE-1（`space_channel_member.py` import `User` 领域模型）为**预存在**违规，非本次引入，未处理。

## 部署备注

升级流程：`alembic upgrade head`（建表 f044）→ 跑回填脚本 `--apply`（保住历史置顶）。旧 `space_channel_member.is_pinned` 列暂留，停止读写，后续可独立迁移 drop。
