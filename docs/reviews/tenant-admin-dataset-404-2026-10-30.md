# 3.0 租户管理员数据集入口 404

2026-10-30；分支 `codex/fix-3.0-tenant-admin-dataset`，基于 `feat/3.0.0`。按 hotfix 流程，业务逻辑仅增加一个已有菜单权限。

## 原因与修复

管理端侧栏按租户管理员身份展示数据集入口，但路由权限补充清单遗漏 `dataset`。角色菜单未单独授予数据集时，动态路由删除 `/dataset`，访问落入 404。数据集列表 API 已要求租户管理员身份，前端路由与现有业务资格不一致。

在租户管理员路由清单补入 `dataset`，保留普通用户、部门管理员的角色菜单检查。

## 验证

- 基线原有路由测试 17 项通过；新增真实路由注册回归后，租户管理员用例因缺少 `dataset` 失败，普通用户及部门管理员的授权/拒绝用例通过。
- 修复后，路由权限、路由过滤及身份侧栏测试共 27 项通过。
- 全前端类型检查通过；管理端全量 lint、改动文件定向 lint、架构守卫及 diff 空白检查通过。
- 全前端 lint 未通过：聊天端 `src/frontend/client/src/components/Chat/AiChatInput.tsx:375` 已有变量 `hasAttachedFiles` 未使用。该文件未修改，HEAD 中同样只有声明。

## L2 七维度审查

边界条件、权限认证、并发安全、信息泄漏、测试覆盖、代码风格、文档同步均无本次改动发现项。权限检查覆盖非管理员授权/拒绝；不改 API、数据隔离或资源动作鉴权；无新状态和依赖。此为既有功能纠错，无新 feature spec/design。

## 现场状态

用户授权系统权限后，通过 Chrome 实际登录会话完成核验：

- `192.168.106.116:3001/dashboard` 显示 gzx01，侧栏展示数据集；点击后实际跳转 `/404`，页面显示“页面不存在”。
- Network 中 `/api/v1/user/info` 返回 200：user_id=849，is_child_admin=true，is_department_admin=false，is_global_super=false，leaf_tenant_id=60，leaf_tenant_name=“测试应用审批”。web_menu 为 admin/home/linsight_task_mode/subscription/apps/workstation/knowledge_space/knowledge/build，缺少 dataset；菜单审批模式为 false。
- 116 公开前端入口引用 `index-CSW4-cjX.js`，业务脚本为 `TenantSelect-v09g3rto.js`（SHA-256：`1b2c56c4bd3687ebd0434237d6bbb8102ded0f6fcc6a650cd5943fbb2b351de9`）。只读下载核对：`/dataset` 路由要求 dataset，但租户管理员补充清单为 board/build/create_app/knowledge/model/evaluation/mark_task/log/sys/workstation，确实遗漏 dataset。
- 回归测试已使用现场用户的完整菜单及管理员标记。

现场根因已确认。尚未部署到 116，SSH 密钥认证仍未通过；需更新 116 管理端前端后再做修复后浏览器验收。未改账号角色或租户数据。
