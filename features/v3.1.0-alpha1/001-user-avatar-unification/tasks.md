# 实施任务 · 网页用户头像统一

| 文档 | 状态 | 依据 |
| --- | --- | --- |
| spec.md | 已确认 | 用户确认按 12 条验收标准实施。 |
| design.md | 已评审 | 用户授权继续完成设计、开发与验证。已核对 C1–C8。 |
| test-cases.md | 已编写 | 测试工程师参考用例按八列模板核对。 |
| tasks.md | 已拆解 | 需求追溯和任务依赖见下表。 |

## 任务与验收

| 任务 | 路径与工作 | 依赖 | 状态 |
| --- | --- | --- | --- |
| T-01 · 定向测试 | `test/user/test_visible_user_avatar_urls.py` 与 `test/message/test_message_sender_avatars.py` 检查租户、失效用户、历史内容、同名用户和旧消息已读。覆盖 AC: AC-01, AC-03, AC-07, AC-08, AC-12 | — | 已完成 |
| T-02 · 定向测试 | `test/permission/test_f048_resource_api.py` 和 `test/tenant/test_grant_subject_search_repository.py` 验证授权名单的目标租户与候选范围。覆盖 AC: AC-03, AC-09, AC-10, AC-12 | — | 已完成 |
| T-03 · 定向测试 | `test/user/test_upload_avatar.py` 覆盖上传和签名失败后的资料。覆盖 AC: AC-01, AC-06 | — | 已完成 |
| T-04 · 用户域 | `bisheng/user/application/avatar.py` 批量解析可见头像，复用 `runtime_identity.py` 的活动身份判定。 | T-01 | 已完成 |
| T-05 · 用户资料 | `bisheng/user/domain/services/user.py` 兼容头像资料的浏览器代理路径，上传成功后提交当前头像。 | T-03 | 已完成 |
| T-06 · 消息 | `message_service.py` 和 `message_schema.py` 输出可空 `sender_avatar`，在已授权结果上剔除历史图片元数据。 | T-04 | 已完成 |
| T-07 · 权限名单 | `permission/application/resource_api.py` 经 `tenant/domain/services/f048_permission_subject.py` 为当前页的用户主体生成可见头像。 | T-02、T-04 | 已完成 |
| T-08 · 权限候选 | `grant_subject_service.py` 为既有资源和创建态选人的分页用户返回可空 `avatar`，更新 `f048.py` 的展示 DTO。 | T-07 | 已完成 |
| T-09 · 共享前端 | `packages/ui/src/components/Avatar/` 复用已有默认样式并处理坏图。`packages/identity/src/avatarUrl.ts` 解析部署路径。 | — | 已完成 |
| T-10 · Client 账号与通知 | `AccountSection.tsx` 和设置页面复用本人资料。`UserPopMenu.tsx` 读当前用户缓存，`NotificationRow.tsx` 按发件人显示头像。 | T-05、T-06、T-09 | 已完成 |
| T-11 · Client 权限 | `client/src/components/permission/` 的名单、选人和草稿同步头像，频道与知识空间设置保留显示字段。 | T-07、T-08、T-09 | 已完成 |
| T-12 · Platform 账号 | `MainLayout.tsx` 使用共享头像。`useCurrentIdentityRefresh.ts` 和 `userContext.tsx` 在聚焦刷新后更新当前用户资料。 | T-09 | 已完成 |
| T-13 · Platform 权限 | `platform/src/components/bs-comp/permission/` 的用户名单、候选与已选摘要使用共享头像。 | T-07、T-08、T-09 | 已完成 |
| T-14 · 前端验证 | `Avatar.test.tsx`、`avatarUrl.test.ts` 和两端页面回归验证默认、失败恢复、账号更新、通知和授权显示。覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11 | T-10、T-11、T-12、T-13 | 已完成 |
| T-15 · HTTP 链路与审查 | `test/e2e/test_e2e_web_user_avatar.py` 使用隔离 ASGI 测试运行实际上传和通知路由。跨模块差异按规格和架构检查。覆盖 AC: AC-01, AC-07, AC-12 | T-06、T-14 | 已完成 |
| T-16 · 全局头像补查 | 核对两端知识、频道、人员、模型、聊天、分享、日志与标注，接入共享头像及现有授权读取。覆盖 AC: AC-02, AC-12, AC-13, AC-14 | T-09 | 已完成 |

## 实际偏差记录

- 上传链路在头像资料写入前完成 URL 生成，使签名失败时保留原头像。当前对象仍通过原 MinIO 路径上传和读取。
- 审查补齐部门知识空间已有授权名单的头像范围。用户离开绑定部门子树后，可见的历史授权行显示默认头像。

## 验证记录

- Client 11 个定向 Jest 套件通过，覆盖 76 项。Platform 8 个定向 Vitest 套件通过，覆盖 58 项。共享身份包 61 项测试通过。两端生产构建和本次变更的 ESLint、`check-i18n`、架构守卫通过。
- 后端 82 项定向回归通过，含本地 HTTP 联测。隔离 ASGI 应用运行真实上传及通知路由，使用测试身份、存储和消息数据。实际部署的浏览器、MinIO、OpenFGA 和数据库联调待验收，QA 页面用例见 [test-cases.md](./test-cases.md)。
- 全量类型检查报告现有知识组件 `VersionHistoryTable.tsx` 的 TS2345，以及 Platform `sidebarSpaceActions.test.tsx` 的两处 TS2349。后端扩大回归中，部门权限、旧 DSH 启动和应用通知套件的共 21 项失败在 `ed1687aee8` 基线复现。

## 代码审查

审查基线为 `ed1687aee8`，结论为 `PASS_WITH_WARNINGS`。范围为 F001 源码、测试和 SDD 文档。对照验收标准复核边界条件、权限认证、并发一致性、数据可见性、测试覆盖、代码规范和设计同步。审查发现的部门子树问题已修复并通过回归。保留上述基线检查结果及部署联调边界。

## 全局补查验证

- Client 的知识卡片及预览、频道创建者、共享头像、聊天作者归属、历史分享和通知的联合回归为 11 个套件、94 项通过。保留的频道成员组件另外检查了新旧接口字段、显式空值和部署路径。
- Platform 的组织选人、租户、模型、日志、标注、会话隔离与通用权限的回归为 10 个套件、71 项通过。应用卡片署名补测另有 3 个套件、16 项通过。
- 后端知识及频道联合回归 161 项通过，2 项失败在基线复现。组织、租户、模型、审计与端到端用例 125 项通过，另有组织角色数据库夹具失败在基线复现。DSH 策略仓储扩大回归的 2 项错误也在基线复现。
- 两端最终生产构建、ESLint、`check-i18n` 和本次变更行 Ruff 检查通过。整体 Typecheck 仍报告上述基线问题。真实部署的浏览器联调以 QA 用例为准。
