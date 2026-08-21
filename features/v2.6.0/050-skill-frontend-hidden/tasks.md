# Tasks: 预置 Skill 前端隐藏

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec / design | ✅ 已评审 | 用户确认 2026-08-17 |
| 实现 | 🟡 待 e2e | 5 / 5 代码完成;105 走查 + 中粮环境三技能配置待办 |

## Tasks

- [x] **T001**: 模型列 + 迁移 + DAO
  `linsight_skill.frontend_hidden`(default 0)+ `f050_skill_frontend_hidden` revision(链 f049);DAO:`set_frontend_hidden`(显式 tenant 条件,hidden=1 时同语句 enabled=1)、`list_enabled(include_hidden)` 或等价查询。
  **覆盖 AC**: AC-02/04/11 · design 决策 1/2

- [x] **T002**: 服务 + API
  `SkillService.set_frontend_hidden`、`get_selectable` 过滤 hidden、`SkillBrief.frontend_hidden`;`PATCH /skill/{name}/frontend-hidden`(tenant_admin)。
  **覆盖 AC**: AC-01/03/05/07 · design 决策 2/4

- [x] **T003**: 任务模式强制并入
  `materialize_session_skills`:`(selected ∪ hidden_enabled) ∩ enabled`,selected 空不早退;注释口径更新。
  **覆盖 AC**: AC-08/09/10 · design 决策 3

- [x] **T004**: 单测
  `test/linsight/test_skill_frontend_hidden.py`:自动启用原子性、关隐藏不动 enabled、selectable 过滤、强制并入(含空选)、hidden+disabled 禁止下发、跨租户不串写。
  **覆盖 AC**: AC-02~05, AC-08~11

- [x] **T005**: platform 技能管理 UI
  `SkillManagement.tsx` 加【前端隐藏】toggle 列 + API controller + i18n 三语;开启时 toast 提示已自动启用。
  **覆盖 AC**: AC-01(前端面) · 手动验证:105 走查

## 实际偏差记录

- T004 补坑 → 本地全量跑时早期套件泄漏全局租户监听器,跨租户 insert 会打真库;测试改为「上下文内建行 + rowcount=0 断言」等价验证租户隔离
- 2026-08-20 AC-03 修订(shanghang 提出)→ 停用时同一条 UPDATE 顺带清掉 `frontend_hidden`,使「隐藏 ⇒ 启用」在两个方向都成立;`LinsightSkillDao.set_enabled` + `SkillManagement.handleToggle` 乐观更新,测试 `test_skill_frontend_hidden.py::TestDao` 三例
