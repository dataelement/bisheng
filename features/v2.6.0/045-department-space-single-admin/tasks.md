# Tasks: 部门知识空间唯一管理员与超级管理员前台隐藏

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0（cofco 分支 feat/cofco-818）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认 2026-08-13 |
| design.md | ✅ 已评审 | 用户确认 2026-08-13 |
| tasks.md | ✅ 已拆解 | |
| 实现 | 🟡 进行中 | 12 / 13 完成（T013 e2e 待真实环境执行,清单已就绪） |

**实现前必须拿到的产品口径**（design §5 坑 6）：空间进【待配置】时在途审批任务的处置——默认按「挂起,补配后由新管理员接手」实现,如产品另有口径在 T006 前改。

---

## 开发模式

按 Wave 组织;后端 Test-First(务实版);前端手动验证。每任务自包含,设计论证指向 design §X 不复制。

---

## Tasks

### Wave 1 — 地基（可并行）

- [x] **T001**: `admin_user_id` 列 + Alembic 迁移
  **文件**: `src/backend/bisheng/knowledge/domain/models/department_knowledge_space.py`、`src/backend/bisheng/core/database/alembic/versions/`（新 revision）
  **逻辑**: `DepartmentKnowledgeSpaceBase` 加 `admin_user_id: int | None`（nullable、index）;revision 只做 ADD COLUMN（存量归一是运维脚本,T011,不进 revision）。DAO 加 `aget_by_admin_user_id` / `aset_admin_user_id`。注意 DM8 兼容（手工复核 autogen）。
  **依赖**: 无 · **design**: 决策 1

- [x] **T002**: 错误码 ×3 + 三语文案
  **文件**: `src/backend/bisheng/common/errcode/knowledge_space.py`、`src/frontend/packages/locales`（api_errors 域,zh-Hans/en/ja 同 PR）
  **逻辑**: 180xx 段续排:未指定管理员拒绝创建 / 目标管理员用户无效(非本企业或非启用) / 空间待配置管理员操作受限。
  **依赖**: 无 · **design**: §2

- [x] **T003**: 部门管理员自动同步机制下线
  **文件**: `src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py`(删 `_grant_default_department_admins`/`_sync_added_admin`/`_sync_removed_admin`/`sync_department_admin_memberships`/`cleanup_removed_department_admins`/`_grant_department_admin_manager`/`_revoke_department_admin_manager` 中同步专用部分)、调用点 `department_service.py:1160/1274/2008`、`login_sync_service.py:700/736`
  **逻辑**: 整体删除,不留兼容开关;`membership_source="department_admin"`、`department_admin_promoted_from_role` 字段停用不删列。grep 确认无残余引用。
  **覆盖 AC**: AC-15 · **依赖**: 无 · **design**: 决策 3

### Wave 2 — 核心服务（Test-First 配对）

- [x] **T004**: 空间管理员服务单元测试
  **文件**: `src/backend/test/knowledge/test_department_space_admin.py`
  **测试**: 创建未指定管理员→拒绝(AC-01);目标用户跨企业/停用→拒绝(AC-02);创建成功→admin_user_id+ADMIN 成员行+manager tuple(AC-03);创建者无 CREATOR 行无 owner tuple(AC-04);原子更换成功/校验失败原样保留(AC-05/06);更换后原管理员回退或移出(AC-07);失效→admin_user_id 置 NULL+通知(AC-08);待配置锁 authorize 写口与审批发起(AC-09);不自动写超管(AC-10);补配恢复(AC-11)。
  **覆盖 AC**: AC-01~11 · **依赖**: T001, T002

- [x] **T005**: 创建链路改造 + 管理员配置/更换/失效服务
  **文件**: `department_knowledge_space_service.py`、`knowledge_space_service.py`(create_knowledge_space 加 `materialize_creator: bool = True` 参数,False 时跳过 `:1532` CREATOR 行与 `:1539` owner tuple)、`knowledge_space_schema.py`(batch item 加必填 `admin_user_id`)
  **逻辑**: batch_create 校验管理员(同企业+启用)→创建空间(不物化创建者)→写 admin_user_id→物化 ADMIN 成员行(`membership_source="space_admin"`)+manager tuple;`replace_admin`:校验→单列 UPDATE(带旧值条件防并发)→物化新、清理旧(回退逻辑参照原 `_sync_removed_admin` 分支);`handle_admin_invalidated(user_id)`:命中空间置 NULL+通知超管;FGA 失败重试+warning(design 坑 1)。
  **测试**: T004 全绿 · **覆盖 AC**: AC-01~08, AC-10, AC-11 · **依赖**: T003, T004 · **design**: 决策 1/2/4

- [x] **T006**: 待配置状态操作锁
  **文件**: `permission/api/endpoints/resource_permission.py`(authorize 写口)、审批发起链路(需空间管理员审批的场景 handler)
  **逻辑**: 部门空间且 `admin_user_id IS NULL` → 新增授权与需管理员确认的操作返回待配置错误码;读/检索/问答不查状态。在途审批默认挂起待新管理员(口径见顶部)。
  **测试**: T004 对应用例 · **覆盖 AC**: AC-09 · **依赖**: T005 · **design**: 决策 6

- [x] **T007**: 用户停用/删除/移出企业钩子
  **文件**: `src/backend/bisheng/user/domain/services/user.py`(停用/删除入口)、SSO 同步移除路径(`login_sync_service.py`,原 cleanup 调用点位置换新钩子)
  **逻辑**: 各入口调 `handle_admin_invalidated`;注意用户管理页入口今天没有任何部门空间钩子(design 坑 4),逐一排查含 v2 开放接口的停用/删除路径。
  **覆盖 AC**: AC-08 · **依赖**: T005 · **design**: 决策 5

### Wave 3 — API 层

- [x] **T008**: API 集成测试 + 端点
  **文件**: `src/backend/test/knowledge/test_department_space_admin_api.py`、`knowledge/api/endpoints/knowledge_space.py`
  **逻辑**: batch-create 请求体强校验(缺 admin_user_id → 422/业务码);新增 `PUT /space/department/{department_id}/admin`(超管专用,原子更换);`/space/department/all` 响应加 `admin_user`/`pending_admin`。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-11 · **依赖**: T005

- [x] **T009**: CREATOR 分支排查(部门空间无创建者后的行为)
  **文件**: `knowledge_space_service.py:422/885/4850` 等按 CREATOR 判定的分支(全量 grep `UserRoleEnum.CREATOR`)
  **逻辑**: 逐处确认部门空间无 CREATOR 行后不出现权限误判/展示异常;空间管理员应获得原 CREATOR 档能力的,改为 ADMIN 判定或 manager relation 判定。
  **覆盖 AC**: AC-03, AC-12 · **依赖**: T005 · **design**: 坑 2

### Wave 4 — 前端 Platform

- [x] **T010**: 管理弹窗:必选负责人 + 待配置 + 更换入口
  **文件**: `src/frontend/platform/src/pages/BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog.tsx`、`controllers/API/departmentKnowledgeSpace.ts`、i18n 三语
  **逻辑**: 变更预览每项加必选「空间负责人」企业用户搜索下拉(复用既有用户搜索组件);未选齐禁用保存;列表展示当前负责人与【待配置管理员】徽标;更换负责人调新 API。文件 326 行,加功能后注意 600 行上限。
  **覆盖 AC**: AC-01, AC-03, AC-11(前端面) · **手动验证**: 平台后台→工作台配置→部门知识空间管理:不选负责人不能保存;选人创建后到 client 空间成员页验证负责人展示、超管不出现;更换负责人后旧人失管理权。
  **依赖**: T008

### Wave 5 — 存量与收尾

- [x] **T011**: 存量归一运维脚本
  **文件**: `src/backend/scripts/migrate_department_space_admin.py`
  **逻辑**: 每租户遍历部门空间:恰一名有效 ADMIN(含 department_admin 来源)→写 admin_user_id 沿用;0 或多→置 NULL(待配置);未沿用的 department_admin 来源成员按回退字段降级或移除;清除超管 CREATOR 成员行与 owner tuple(审计保留)。dry-run 模式 + 幂等 + 多租户 `bypass_tenant_filter` 枚举。
  **覆盖 AC**: AC-16, AC-17 · **依赖**: T005 · **design**: 坑 5

- [x] **T012**: FGA 对账兜底
  **文件**: `src/backend/bisheng/worker/` 既有对账任务风格新增(或并入现有 Beat 对账)
  **逻辑**: 比对 `admin_user_id` 与 `knowledge_space#manager`(space_admin 来源)tuple,差异修复+warning;顺带扫描失效管理员兜底(design 决策 5B)。
  **覆盖 AC**: AC-05(最终一致面) · **依赖**: T005

- [ ] **T013**: e2e 清单 + /e2e-test
  **文件**: `features/v2.6.0/045-department-space-single-admin/e2e-checklist.md`
  **逻辑**: design §7 手动主线全跑;补审批场景:部门空间上传审批由空间管理员审批、待配置时发起被锁。
  **覆盖 AC**: 全部回归 · **依赖**: T006~T012

---

## 实际偏差记录

> 只留一行指针,论证在 design.md。

- T005 偏离 → design 决策 3 补「实现偏差」：`department_admin_promoted_from_role` 复用于 space_admin 回退,未停用
- T006 偏离 → 上传审批老链路在本分支已废弃(测试断言不再调用),实际锁点=authorize 写口 + 空间加入审批 gate;在途审批按「挂起待新管理员」口径无需额外处置(审批人按 ADMIN 成员实时解析)
- T007 补充 → 「移出企业」入口落在 `user_tenant_sync_service.sync_user`(租户 leaf 切换),用 `except_tenant_id` 保留新租户内的管理身份
