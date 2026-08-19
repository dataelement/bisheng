# Design: 预置 Skill 前端隐藏

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0(cofco 分支)
**最后更新**: 2026-08-17

---

## 1. 目标与非目标

- **目标**:`LinsightSkill` 加租户级【前端隐藏】开关;隐藏=选择器不可见,任务运行由服务端强制并入并下发;开启隐藏同保存自动启用;停用优先。
- **非目标**:不动 F035 的技能生命周期(创建/编辑/删除/启停语义)与门控架构;不做种子数据。

## 2. 关键约束

- 遵循 constitution C1–C7;`linsight_skill` 归 F035,本次仅字段级扩展(release-contract 已登记)。
- `set_enabled` 的坑要继承:bulk UPDATE 不被租户过滤器改写,写操作必须显式带 tenant_id 条件。

## 3. 方案对比与选定

### 决策 1:隐藏状态放哪

- **选定**:`linsight_skill.frontend_hidden`(bool,default 0)+ Alembic `f050_skill_frontend_hidden`。租户行天然隔离(AC-11 免费)。
- **备选**(否):独立配置表/租户配置项——技能本来就是行级租户数据,加表是第二真相源。

### 决策 2:「开启隐藏即启用」的原子性

- **选定**:同一条 UPDATE 里写 `frontend_hidden=1, enabled=1`(单语句原子,AC-02);关闭隐藏只写 `frontend_hidden=0`,不动 enabled(AC-04)。API 为独立 `PATCH /skill/{name}/frontend-hidden`,与 `/status` 平行(截图两列独立开关)。
- **停用优先**:隐藏后仍可 `/status` 停用(AC-03);强制下发集合定义为 `hidden ∩ enabled`,停用自动退出集合(AC-09),无需额外状态机。

### 决策 3:强制下发的落点

- **选定**:唯一白名单门 `materialize_session_skills`:`wanted = (selected ∪ hidden_enabled) ∩ enabled`,且 selected 为空时不再早退(hidden 仍须物化)。运行期 middleware 不传 active_skills(复制即门,F035 现状),hidden 已在 enabled 集合内,零改动。
- **不泄漏**:强制并入不写回用户选择,前台回显(会话技能 chips/回放)看不到隐藏技能(AC-06)。

### 决策 4:前台隐藏的实现面

- **选定**:仅 `/skill/selectable` 过滤 `frontend_hidden=1`(client 选择器唯一数据源);详情/文件接口本就是租户管理员权限,无业务用户入口。client 零改动。
- 管理列表(`SkillBrief`)加 `frontend_hidden` 字段照常返回(AC-07)。

## 4. 系统现状 → 目标态

`PATCH /skill/{name}/frontend-hidden`(新,tenant_admin)→ `SkillService.set_frontend_hidden` → `LinsightSkillDao.set_frontend_hidden`(带 tenant 条件的单条 UPDATE)。
选择器:`SkillService.get_selectable` → `LinsightSkillDao.list_enabled(include_hidden=False)`。
任务运行:`task_exec` → `materialize_session_skills(selected)` → 查 `list_enabled()` 时同步拿 hidden 集合强制并入 → 复制进工作区 → 模型可见。
platform:`SkillManagement.tsx` 表格加【前端隐藏】toggle 列(bench 截图样式)+ i18n 三语;开启时按钮即保存(与状态列一致交互)。

## 5. 已知坑

| # | 事实 | 处理 |
|---|---|---|
| 1 | `set_enabled` 式 bulk UPDATE 无租户注入 | `set_frontend_hidden` 同样显式 `tenant_id` 条件 |
| 2 | `materialize_session_skills` 有 `if not selected: return` 早退 | 改为 hidden 集合非空时继续;"skills 严格 opt-in"的注释口径更新为"opt-in + 服务端强制项" |
| 3 | 队友 F049(job_grade)未附迁移,alembic head 仍是 f049_dks_admin_user_id | f050 直接链 f049;若对方补迁移出现双头,按惯例 merge revision |

## 6. 契约

- 对外:`SkillBrief.frontend_hidden`(管理列表)、`PATCH /skill/{name}/frontend-hidden`(platform 专用);`/skill/selectable` 行为收窄(隐藏项不再返回——业务前台无感知)。
- 依赖:F035 的「复制即门」不变量——若未来改为 active_skills 运行期门控,强制并入要同步进 config。

## 7. 测试

- 单测:开隐藏自动启用(单语句)、关隐藏不动 enabled、selectable 过滤、materialize 强制并入(含 selected 空)、hidden+disabled 不下发、跨租户不串写。
- e2e:105 中粮环境给三个 Office skill 点上隐藏 → client 选择器不可见 → 任务运行文档能力照常。

---

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-17 | 初版 | spec 确认 |
