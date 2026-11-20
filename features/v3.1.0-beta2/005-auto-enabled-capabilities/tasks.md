# Tasks: 工作台工具与技能「自动启用」

**关联规格**: [spec.md](./spec.md)
**版本**: v3.1.0-beta2

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-20 用户确认（含 AC-23、AC-24 补充） |
| design.md | ✅ 已评审 | 2026-11-20 用户确认；决策 5 的细化（复制而非硬链接）记在修订历史 |
| tasks.md | ✅ 已拆解 | |
| 实现 | 🔲 未开始 | 0 / 12 完成 |

---

## 开发模式

按 Wave 推进，后端先写测试再实现。设计论证见 design.md，本文不复制。新测试放在 `src/backend/test/<module>/`。

---

## Tasks

### Wave 1：技能挂载不写 MinIO，直接回答总是挂载（design 决策 5）

- [ ] **T001**: 技能本地挂载与 `skills/` 读取的测试
  **文件**: `src/backend/test/linsight/test_skill_local_mount.py`
  **逻辑**: 断言：
  - `materialize_session_skills(user_id=...)` 不调用 `backend.upload_files`，技能文件出现在 `file_dir/skills/<name>/`。
  - 快照里已有的条目在 `file_dir` 为空时会按快照的 content_hash 重新复制。
  - `WorkspaceBackend.read("/skills/x/SKILL.md")` 在本地没有文件时按 `skill_snapshot` 从技能存储读出。
  - `ls("/skills")`、`glob("skills/**/*.md")`、`grep(..., path="/skills")` 返回快照里的文件；`secrets/` 仍然被拒绝。
  - 复制出来的文件被修改后，节点缓存不变。
  **覆盖 AC**: AC-24（挂载方式）
  **依赖**: 无

- [ ] **T002**: 实现本地挂载与 `skills/` 路由
  **文件**: `src/backend/bisheng/linsight/domain/services/skill_provisioning.py`、`workspace_backend.py`
  **逻辑**: `_copy_one` 改为 `SkillStore.materialize` + `shutil.copytree`（目标已存在先删除）。`_materialize_candidates` 对 `prior` 条目也做本地复制。`WorkspaceBackend` 增加 `skills/` 路径的读取与列表分支，数据源是 `skill_snapshot` + `SkillStore`。`_materialize_selected`（无 user_id 的旧调用）同样改为本地复制。
  **覆盖 AC**: AC-24
  **依赖**: T001

- [ ] **T003**: 直接回答总是挂载全部可用技能
  **文件**: `src/backend/bisheng/workstation/domain/services/direct_run.py`、`src/backend/test/workstation/test_direct_run_skills.py`
  **逻辑**: `_mount_skills` 去掉 `if not ctx.skills: return False`；失败事件只报用户选中的技能（逻辑不变）。测试：不选技能时仍调用 provision，并且 `selected` 为空列表。
  **覆盖 AC**: AC-15, AC-16, AC-24
  **依赖**: T002

### Wave 2：自动启用（后端）

- [ ] **T004**: 技能 `auto_enabled` 列、DAO、接口
  **文件**: alembic 新 revision `f005_linsight_skill_auto_enabled`、`linsight_skill.py`、`skill_schema.py`、`skill_service.py`、`linsight/api/endpoints/skill.py`、测试 `test/linsight/test_skill_auto_enabled.py`
  **逻辑**: 列 `Integer NOT NULL DEFAULT 0`，`column_exists` 守卫；`down_revision` 用 `alembic heads` 的输出。`LinsightSkillDao.set_auto_enabled` 照 `set_default_checked` 写，带 tenant 条件。`PATCH /{name}/auto-enabled` 需要租户管理员。管理列表 `SkillBrief` 带 `auto_enabled`。测试：设置后读回；内置技能重新同步不改这一列；单 head。
  **覆盖 AC**: AC-06, AC-08, AC-09
  **依赖**: 无

- [ ] **T005**: 工具配置字段 `auto_enabled` 透传
  **文件**: `api/v1/schemas.py`（`ToolConfig`）、`workstation_service.py`、测试 `test/workstation/test_tool_auto_enabled_config.py`
  **逻辑**: 新字段 + validator（自动启用时 `default_checked=False`）。`_group_tool_rows`、`_ahydrate_tools_from_source_tenant`、`_aproject_tools_for_current_tenant`、`parse_config` 的旧数据迁移、`_abuild_default_daily_config` 透传。测试：保存后读回；子租户继承投影后字段仍在；缺字段的旧配置读出为 False。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05
  **依赖**: 无

- [ ] **T006**: 发送入口补入自动启用的工具
  **文件**: `workstation_service.py`（`auto_enabled_tool_keys` 同步/异步、`awith_auto_enabled_tools`）、`workstation/api/endpoints/chat.py`、测试 `test/workstation/test_auto_enabled_tool_injection.py`
  **逻辑**: 读取当前租户的配置（含继承投影），用 `afilter_tools_by_use_permission` 过滤，把自动启用组的子工具按 id 去重后并入 `data.tools`，并打一条 info 日志。只在登录态入口调用。测试：补入；去重；无权限不补；开放 API 入口不补。
  **覆盖 AC**: AC-14, AC-17, AC-19, AC-21, AC-12（去重）
  **依赖**: T005

- [ ] **T007**: 个人停用对自动启用项无效
  **文件**: `tool/domain/services/user_availability.py`、`linsight/domain/services/user_skills.py`、测试 `test/tool/test_user_availability_auto_enabled.py`、`test/linsight/test_user_skills_auto_enabled.py`
  **逻辑**: 工具：`disabled_ids` 和 `is_enabled_sync` 剔除 `auto_enabled_tool_keys()` 对应的工具（按 tool_key）。技能：`records` 中 `auto_enabled and enabled` 的行视为启用。
  **覆盖 AC**: AC-18, AC-23
  **依赖**: T004, T006

- [ ] **T008**: 用户端列表过滤
  **文件**: `dsh/domain/services/capability_catalog.py`（`picker_tools`、`list`）、`linsight/domain/services/skill_service.py`（`get_selectable`）、`linsight/api/endpoints/personal_skill.py`（`skill_center`）、测试 `test/dsh/test_capability_catalog_auto_enabled.py`、`test/linsight/test_skill_lists_auto_enabled.py`
  **逻辑**: 去掉自动启用的工具组和技能。`candidates`、`runtime/catalog`、开放 API 日常配置不过滤。
  **覆盖 AC**: AC-10, AC-11, AC-13, AC-22
  **依赖**: T004, T005

### Wave 3：前端

- [ ] **T009**: 平台：已选工具的「使用方式」
  **文件**: `platform/src/components/LinSight/ToolSelector.tsx`、`ToolSelectorContainer.tsx`、`pages/BuildPage/bench/ToolsConfig.tsx`、`public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 见 design 决策 7。Select（small、描边、宽 112px、`useSelectLabels()`），选项带一行说明；点击阻止冒泡。保存时写 `default_checked` 与 `auto_enabled`。
  **手动验证**: TC-AE-001
  **依赖**: T005

- [ ] **T010**: 平台：技能管理「自动启用」列
  **文件**: `platform/src/components/LinSight/skill/SkillManagement.tsx`、`controllers/API/linsight.ts`、locales
  **逻辑**: 见 design 决策 7。Switch，乐观更新加回滚；技能停用时置灰并显示 Tooltip；列头 Tooltip。
  **手动验证**: TC-AE-009, TC-AE-010
  **依赖**: T004

- [ ] **T011**: 客户端：旧选择清理
  **文件**: `client/src/components/Chat/Input/agentToolDefaults.ts` 及技能选择处（核实后确定）
  **逻辑**: 恢复的工具选择和技能选择与当前可用列表求交集。如果已经求交集，只补测试。
  **手动验证**: TC-AE-008
  **依赖**: T008

### Wave 4：验证

- [ ] **T012**: 114 部署与端到端验证
  **逻辑**: 推到 114 部署；用非管理员账号执行 TC-AE-003/004/005/006/011/012/013；重跑挂载耗时测量，记入 design §7.1；`/e2e-test`；`/sdd-code-review --base feat/3.1.0-beta2`。
  **依赖**: T001–T011

---

## 实际偏差记录

| 日期 | 任务 | 偏差 | 处理 |
|---|---|---|---|
