# Beta2：全局角色可见性与组织成员自身编辑修复

日期：2026-11-25。目标发版线：`feat/3.1.0-beta2`。按已确认的两项修复要求走 hotfix 流程；不部署生产、不修改生产数据。

## 修复结果

- 子租户管理员和部门管理员的角色管理列表均包含全局角色；全局角色返回 `is_readonly=true`，更新、删除、菜单修改仍由既有服务端权限校验拒绝。系统管理员角色 ID 1 继续不出现在列表中。部门管理员的本租户角色范围保持原有部门范围。
- 移除子租户管理员专用的全局角色隐藏条件，以及因此产生的“仅分配角色时包含全局角色”内部参数；列表、计数、旧角色分配入口共用同一查询规则，无数据库迁移。
- 组织成员列表移除“登录用户等于目标成员时禁用编辑”的前端条件。自己的行点击和更多菜单编辑均能进入现有编辑弹窗，继续使用既有服务端组织范围和字段校验。禁用账号、归档部门、系统超管目标的编辑保护保留。
- 修正同一角色列表分支中的异常变量赋值笔误，避免租户管理员查询异常时引用未赋值变量。

## 自身编辑限制的来源

`git log -S 'user.user_id === m.user_id'` 和原始补丁确认，组织成员页面的限制首次出现在：

- 提交：[`89649ffd792bb623edfb21cdd69c72783e0d6332`](https://github.com/dataelement/bisheng/commit/89649ffd792bb623edfb21cdd69c72783e0d6332)。
- Git 作者：`30388 <30388@users.noreply.github.com>`；只能确认 Git 署名，未推断真实姓名。
- 作者时间：2026-04-16 21:57:11 +08:00；提交时间：2026-04-16 21:59:15 +08:00。
- 标题：`feat(perm-2.5): org member edit, primary dept, delete guard, router order`。
- 当时文件：`src/frontend/platform/src/pages/DepartmentPage/components/MemberTable.tsx`，原提交第 251 行：`disabled={user.user_id === m.user_id}`。

该提交随组织成员编辑功能新增此判断，提交说明没有解释禁止编辑自己的原因。后续拆分至 `MemberTableView.tsx` 并提取 `canEditMember` 时沿用，不能将 UI 重构提交认作最初引入者。

## 验证与审查

- 新增 SQLite 回归贯穿 `RoleService.list_roles`、实际 DAO 查询和实际计数，覆盖子租户管理员及兼任部门管理员、全局只读、外租户排除、部门范围、分页和总数一致。
- 新增组件交互回归覆盖两种管理员身份从自身行和编辑菜单进入；同时覆盖禁用账号、归档部门、超管目标继续禁用。
- 后端角色列表、服务和接口相关测试 55 项通过；前端成员列表、分页、定位和编辑表单相关测试 19 项通过。
- 前端 workspace 的 `pnpm lint`、`pnpm typecheck` 全部通过；修改的 Python 文件通过 Ruff，`git diff --check` 通过。
- 架构守卫无 VIOLATION；旧 `api/v1/usergroup.py` 仍存在原有 RULE-3 WARNING，本次只删除失效的内部参数，未新增跨层导入。
- 全角色模块检查为 84 项通过、1 项失败：`test_management_view_catalog.py::test_catalog_and_custom_roles_follow_the_view[True-expected1]`；临时恢复基线 `role.py` 后相同用例仍失败，确认为既有基线问题，未纳入本次修复。
- 旧接口测试中依赖引号样式的断言改为定位错误文案，避免源码格式化导致误报。

按 `sdd-code-review` 七个维度审查：边界条件、权限认证、并发安全、信息泄漏、测试覆盖、代码风格、文档同步均无本次新增的阻断问题。变更只影响读取规则与编辑入口，无新接口、表结构、跨租户写入或新依赖。生产完整链路验收待部署后执行。
