# Verification: 知识库置顶偏好统一

**Feature ID**: `053-knowledge-space-pin-unification`  
**Date**: 2026-07-14  
**结论**: 代码实现、特性自动化测试、架构守卫和前端生产构建通过；真实 MySQL/DM8 迁移演练与浏览器人工 E2E 尚未执行。

## 1. 自动化验证

| 验证项 | 状态 | 证据 |
|--------|------|------|
| 后端特性、公共列表、频道回归 | PASS | `uv run pytest test/knowledge/test_knowledge_space_pin_*.py test/knowledge/test_public_space_level_list.py test/channel/test_channel_pin_regression.py -q` → `27 passed` |
| 新增后端文件格式 | PASS | `uv run ruff format --check ...` → `12 files already formatted` |
| 新增后端文件静态检查 | PASS | `uv run ruff check ...` → `All checks passed` |
| 架构守卫 | PASS | `bash scripts/arch-guard.sh` → exit code 0 |
| Alembic head | PASS | `uv run alembic heads` → `f057_knowledge_space_user_link_pin (head)` |
| 前端聚焦测试 | PASS | `npm run test:ci -- --runInBand useSpaceActions.test.tsx SpaceSidebar.test.tsx KnowledgeSpaceItem.test.tsx` → `3 suites / 11 tests passed` |
| 前端生产构建 | PASS | `npm run build` → Vite 构建完成，exit code 0；仅有既有资源、chunk 与 eval 警告 |
| PortalKnowledgeWorkbench 全文件测试 | FAIL（既有） | 全文件运行 `109` 项中 `40` 项失败，失败包含创建审批、活动空间初始化等既有场景；本特性使用独立 `SpaceSidebar` 与 `useSpaceActions` 测试覆盖 |
| 全历史文件 Ruff | FAIL（既有） | 扫描完整 `knowledge_space_service.py` 等历史文件发现 `108` 个既有 lint 问题；新增文件单独检查全绿 |

## 2. Acceptance Criteria

| AC | 状态 | 证据与说明 |
|----|------|------------|
| AC-01 | PASS | 公共库列表叠加 `user_link`；未订阅但可见公共库的置顶 Service 测试通过 |
| AC-02 | PASS | `_format_accessible_spaces`、`_format_member_spaces` 均停止读取成员置顶并统一批量装饰 |
| AC-03 | PASS | 后端第 6 个置顶拒绝、已有记录幂等、用户行 `FOR UPDATE` 锁测试通过 |
| AC-04 | PASS | 门户内嵌侧边栏和普通侧边栏均验证普通个人库及“我的收藏”无置顶操作 |
| AC-05 | PASS | 个人库置顶和取消置顶均抛出 `SpacePersonalPinForbiddenError`，且不调用写 Repository |
| AC-06 | PASS | 置顶集合与当前可见 ID 求交；不可见部门库拒绝，偏好记录本身不删除 |
| AC-07 | MANUAL_REQUIRED | SQLite 单元测试已覆盖去重、幂等回填、个人/频道排除和唯一约束；真实 MySQL/DM8 升降级未执行 |
| AC-08 | PASS | 频道仍使用 `SpaceChannelMember.is_pinned` 写入与排序，频道回归测试通过 |
| AC-09 | PASS | Repository 按空间清理仅删除 `knowledge_space_pin`；删除主记录后才调用清理 |
| AC-10 | PASS | 缓存命中时重新叠加最新 pin，并重置旧缓存中的 `is_pinned=true` |
| AC-11 | PASS | Endpoint 保留 `/set-pin` 与请求字段 `is_pined`，契约测试通过 |
| AC-12 | PASS | 重复新增/删除 Repository 测试与 Service 幂等测试通过，ORM 唯一约束已声明 |

## 3. 未执行项

- `MANUAL_REQUIRED`：在可回滚 MySQL 测试库执行 F057 upgrade → downgrade → upgrade，并核对 T001 的 6 条预期回填。
- `MANUAL_REQUIRED`：Linux DM8 CI 执行迁移与特性后端测试。
- `NOT_RUN`：在 `/workspace/knowledge-portal?portal_embed=1` 完成人工 E2E，包括三类置顶、个人库隐藏、第 6 个限制、缓存即时性及频道回归。
- 未在当前配置数据库运行 `alembic upgrade head`，以避免对现有环境产生未经单独确认的数据和约束变更。

## 4. 工作树边界

- 已保留用户原有修改：`shougang_portal_config/domain/services/portal_config_service.py`、`celerybeat-schedule.db`。
- 本特性未修改 `shougang-group-knowledge-portal` 宿主项目生产代码。
