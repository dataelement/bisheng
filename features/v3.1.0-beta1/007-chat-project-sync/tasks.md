# 项目跨端同步：阶段状态

设计已确认，26 条八列 QA 参考用例已生成并检查。以下后端路径相对 src/backend；前端路径相对 Bisheng 仓库；Desktop 路径相对 BishengWork。保持现有分支及无关 WIP，不推送。

| 文档 | 状态 | 依据 |
| --- | --- | --- |
| request.md | ✅ 需求发现已确认 | 用户选择“由你完成三端改造”，随后要求继续 |
| spec.md | ✅ 已评审、用户已确认 | spec-review.md 为 LGTM；用户选择“确认规格，继续设计” |
| design.md | ✅ 已评审 | 用户选择“确认设计，进入实现” |
| test-cases.md | ✅ 已生成并检查 | 26 条八列用例，覆盖 13 项 AC |
| tasks.md | ✅ 已拆解 | tasks-review.md 为 LGTM |

## 执行任务

| ID | 分类 | 文件与自包含任务 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| T001 | 基础设施 | `bisheng/chat_session/domain/models/project.py`、`bisheng/core/database/tenant_filter.py`：四表、唯一约束、JsonType、租户发现；只新增表，回退保留表与旧数据 | — | ✅ 实现完成；L1 审查及相关回归通过 |
| T002 | 基础设施 | `bisheng/common/errcode/chat.py`、`bisheng/chat_session/domain/schemas/projects.py`：13011–13018 与严格动作联合，拒绝 owner 参数，限制名称和批次 | T001 | ✅ 实现完成；L1 审查及相关回归通过 |
| T003 | 基础设施 | `src/frontend/packages/locales/src/api_errors/zh-Hans.json`、`en.json`：中英文错误文案 | T002 | ✅ 实现完成；L1 审查及相关回归通过 |
| T004 | 基础设施 | `src/frontend/packages/locales/src/api_errors/ja.json`、`features/v3.1.0-beta1/release-contract.md`：日文及错误码登记；生成物走现有脚本 | T003 | ✅ 实现完成；L1 审查及相关回归通过 |
| T005 | 后端 Domain 测试 | `test/chat_session/test_projects_repository.py`：真实 SQL 验证回滚、唯一归属、并发、分页、幂等、导入与越界。覆盖 AC: AC-01, AC-04, AC-05, AC-06, AC-07, AC-10, AC-11 | T002 | ✅ 实现完成；L1 审查及相关回归通过 |
| T006 | 后端 Domain | `bisheng/chat_session/domain/repositories/project_repository.py`：消费 T002 DTO；账号锁→项目→会话，动作/快照/分页/回执，不在事务内发布 | T005 | ✅ 实现完成；L1 审查及相关回归通过 |
| T007 | 后端 Domain 测试 | `test/chat_session/test_projects_events.py`：订阅屏障、心跳补漏、通知失败及身份失效。覆盖 AC: AC-02, AC-07, AC-08, AC-09 | T006 | ✅ 实现完成；L1 审查及相关回归通过 |
| T008 | 后端 Domain | `bisheng/chat_session/domain/services/project_events.py`、`project_service.py`：严格 actor scope，提交后 Redis 发布，15 秒版本修复与重新认证 | T007 | ✅ 实现完成；L1 审查及相关回归通过 |
| T009 | 后端 API 测试 | `test/chat_session/test_projects_api.py`：四端点、envelope、边界及具体错误码。覆盖 AC: AC-01, AC-08, AC-10, AC-11, AC-12 | T008 | ✅ 实现完成；L1 审查及相关回归通过 |
| T010 | 后端 API | `bisheng/chat_session/api/endpoints/projects.py`、`bisheng/chat_session/api/router.py`：固定请求到服务，SSE 认证及头 | T009 | ✅ 实现完成；L1 审查及相关回归通过 |
| T011 | 后端 Domain 测试 | `test/chat_session/test_project_session_lifecycle.py`：原子创建、重放停止生成、改名删除通知。覆盖 AC: AC-03, AC-05, AC-07 | T010 | ✅ 实现完成；L1 审查及相关回归通过 |
| T012 | 后端 Domain | `bisheng/chat_session/domain/chat.py`、`bisheng/chat_session/domain/repositories/project_session_repository.py`：Owner 事务，保持组/组织快照，通知先于附件清理 | T011 | ✅ 实现完成；L1 审查及相关回归通过 |
| T013 | 后端 API | `bisheng/chat_session/api/endpoints/chat.py`：改名传 login_user 并验证所属身份，保留响应契约 | T012 | ✅ 实现完成；L1 审查及相关回归通过 |
| T014 | 后端 Domain | `bisheng/workstation/domain/schemas/chat.py`、`bisheng/workstation/domain/services/chat_service.py`：两个普通创建点传首条项目意图到 Owner，重放不运行模型 | T012 | ✅ 实现完成；L1 审查及相关回归通过 |
| T015 | 后端 Domain | `bisheng/workstation/domain/services/task_submit_service.py`、`bisheng/linsight/domain/services/workbench_impl.py`：显式传自然人意图，保持任务语义，Open API 不取得此能力 | T014 | ✅ 实现完成；L1 审查及相关回归通过 |
| T016 | 后端 Domain | `bisheng/workstation/domain/services/chat_helpers.py`、`bisheng/linsight/domain/services/workbench_impl.py`：async/sync 自动标题走 Owner，保留 only_if_default | T015 | ✅ 实现完成；L1 审查及相关回归通过 |
| T017 | 基础设施 | `docker/nginx/conf.d/default.conf`：精确 SSE 代理位于普通正则之前，关闭缓冲，保持路径与认证 | T010 | ✅ 实现完成；L1 审查及相关回归通过 |
| T018 | 前端 Client 测试 | `src/frontend/client/src/api/chatProjects.test.ts`、`src/frontend/client/src/layouts/WorkbenchSidebar/projectChatCreation.test.ts`：高水位、取消、失败、不可变意图。覆盖 AC: AC-02, AC-03, AC-06, AC-07, AC-08, AC-09 | T010 | ✅ 实现完成；L1 审查及相关回归通过 |
| T019 | 前端 Client | `src/frontend/client/src/api/chatProjects.ts`、`src/frontend/client/src/hooks/useChatProjects.ts`：request 包装，React Query v4，身份 key，SSE/host 失效与恢复 | T018 | ✅ 实现完成；L1 审查及相关回归通过 |
| T020 | 前端 Client | `src/frontend/client/src/layouts/MainLayout.tsx`、`DesktopShellBridge.tsx`：已认证 shell 中组装同步，保留原有 WIP | T019 | ✅ 实现完成；L1 审查及相关回归通过 |
| T021 | 前端 Client | `src/frontend/client/src/layouts/WorkbenchSidebar/projectsStore.ts`、`useSidebarProjects.ts`：删除 mock 权威源，旧键只供迁移，DEV 演示不上传 | T020 | ✅ 实现完成；L1 审查及相关回归通过 |
| T022 | 前端 Client | `src/frontend/client/src/layouts/WorkbenchSidebar/SidebarProjects.tsx`、`ProjectConversations.tsx`、`ProjectNameDialog.tsx`、`SidebarConversationList.tsx` 及 `components/Conversations/ConvoOptions/ConvoOptions.tsx`：异步 CRUD、独立分页、默认去重、搜索、失败保稿 | T021 | ✅ 实现完成；L1 审查及相关回归通过 |
| T023 | 前端 Client | `src/frontend/client/src/layouts/WorkbenchSidebar/projectChatCreation.ts`、`src/frontend/client/src/components/Chat/useDesktopNavigation.ts`：发送前固定意图及 request ID，精确草稿 URL | T022 | ✅ 实现完成；L1 审查及相关回归通过 |
| T024 | 前端 Client | `src/frontend/client/src/hooks/useAiChatSSE.ts`、实际 APIChatCompletion 类型入口：发送项目意图；重放打开已有会话，不重发 | T023 | ✅ 实现完成；L1 审查及相关回归通过 |
| T025 | 前端 Client | `src/frontend/client/src/layouts/WorkbenchSidebar/ProjectSyncStatus.tsx`、`src/frontend/client/src/hooks/useProjectMigration.ts`：自动迁移、来源账号绑定、分批幂等与逐项结果，保留原键 | T024 | ✅ 实现完成；L1 审查及相关回归通过 |
| T026 | 基础设施 | `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`：项目同步三语 key 同批维护，无关文案不改 | T025 | ✅ 实现完成；L1 审查及相关回归通过 |
| T027 | Desktop 测试 | `test/chat-project-sync.test.ts`：协议、epoch、Cookie、SSE 与分页。覆盖 AC: AC-01, AC-02, AC-06, AC-07, AC-08, AC-09, AC-10 | T010 | ✅ 实现完成；L1 审查及相关回归通过 |
| T028 | Desktop | `src/shared/chat-projects.ts`、`src/shared/enterprise-chat-view.ts`：可序列化 DTO、unknown 校验、固定动作，不接收 URL | T027 | ✅ 实现完成；L1 审查及相关回归通过 |
| T029 | Desktop | `src/main/enterprise/chat-projects.ts`、`src/main/enterprise/chat-view.ts`：认证 Session 传输，续期，reader/timer/epoch 清理 | T028 | ✅ 实现完成；L1 审查及相关回归通过 |
| T030 | Desktop | `src/main/index.ts`、`src/preload/index.ts`：可信窗口/主 frame/epoch 窄 IPC 与 presentation 只读失效接缝 | T029 | ✅ 实现完成；L1 审查及相关回归通过 |
| T031 | Desktop 测试 | `test/chat-projects.test.mjs`、`test/enterprise-chat-view.test.ts`：异步 CRUD、保稿、迁移与原侧栏。覆盖 AC: AC-03, AC-04, AC-05, AC-08, AC-11, AC-12, AC-13 | T030 | ✅ 实现完成；L1 审查及相关回归通过 |
| T032 | Desktop | `packages/dsh-desktop-client-ui/client.js`：服务端投影替换本机权威源，删除晚归属，保留 slots/primitives/locale | T031 | ✅ 实现完成；L1 审查及相关回归通过 |
| T033 | Desktop | `scripts/verify-chat-project-sync.mjs`、`test/helpers/session-search-fixture.mjs`：隔离 Profile 双客户端，自动同步、重连、身份和旧历史 | T032 | ✅ 真实 Electron 隔离联调通过 |
| T034 | 后端 API 测试 | `test/e2e/test_e2e_chat_project_sync.py`：接口 E2E 读回、专用测试数据及 cleanup。覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13 | T026, T033 | ✅ 隔离 ASGI/SQL 回归通过；目标环境验收见 verification.md |
| T035 | 验证 | 本目录 `tasks.md`、`design.md`：相关/完整回归、arch-guard、双端实测；MySQL/DM8/Gateway/Windows 各自记录，未运行不称通过 | T034 | 本地检查完成；完整回归存在独立 PPT 超时且复测通过，目标环境余项明确列出 |
| T036 | 用户修订 | 自动迁移替代手动确认：Web shell 生命周期、旧来源账号绑定、两端退避重试、移除入口；补充自动/中断/切换账号回归 | T025, T032 | ✅ 实现完成，相关回归通过；3006 新构建已载入并核验无入口，真实双向同步读回通过 |
| T037 | 用户反馈修复 | Web新草稿生命周期/不可变首条项目意图；Desktop重复同项目新建、设置保稿和按更新时间合并标题；补首条生产入口与异步迟到回归，统一119服务 | T036 | ✅ Web102、Backend120、最终Desktop155相关回归；类型/构建通过；119双向真实普通项目对话与SQL归属已核验，正式安装包未发布 |

## 实际偏差记录

用户最新要求覆盖原确认式迁移：Web 与 Desktop 登录后自动迁移，移除入口和确认弹窗。Web 旧来源绑定首次当前账号；失败自动重试。无新增 Worker，原任务队列租户上下文保持。补充测试 useProjectMigration.test.tsx、Desktop 自动迁移重试用例，并将 SidebarConversationList/ProjectConversations 等实际消费文件纳入 T022。源码、构建与实际加载分别记载于 verification.md。
