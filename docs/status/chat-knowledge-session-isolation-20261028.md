# 普通 Chat 知识空间按会话保存

日期：2026-10-28。状态：源码修复与定向自动化验证完成，等待部署及 Windows 真实账号验收。

## 问题与修复

普通 Chat 原先共用 `selectedOrgKbs` 全局状态，`ChatView` 将最后一次选择写入账号级 `bs:{uid}:selectedOrgKbs`。会话切换保持该状态；发送与重新生成读取该状态。因此 C2 的 K2 会同时成为 C1 的展示值和后续请求范围。

现在 `useAiChat` 持有会话知识选择，输入框直接使用同一份状态。`useConversationKnowledge` 按账号与会话 ID 保存选择；主 Chat 与订阅面板的初始草稿分别保存。选择操作同步保存，空列表也是有效选择。路由切换时，会话 ID、消息桶和知识选择在同一次提交中生效。首条消息收到正式 ID 时，保存该轮捕获的选择；后台响应保持前台正在查看的会话。

持久化键：`bs-conversation:{uid}:knowledge:{conversationId}`；草稿 ID 为 `new:chat` 或 `new:subscription`。该数据属于会话上下文，使用独立于登录时清理的 `bs:*` 偏好键的命名空间。账号隔离由 key 中的 uid 保证，读取范围受浏览器 origin 隔离。记录保存在当前设备的浏览器／桌面 WebView 本地存储，跨设备同步需要服务端会话存储支持。

历史账号级记录只有最后一次选择，无法还原各历史会话的选择。已有会话缺少独立记录时使用空范围，用户重新选择后独立保存。新会话按管理员配置应用组织知识库默认值；知识空间初始为空。管理员关闭组织知识库后，知识空间选择继续生效。

发送和重新生成沿用现有 API 字段 `use_knowledge_base.organization_knowledge_ids` 与 `knowledge_space_ids`，从当前会话选择生成整数 ID 列表。后端现有 `_resolve_user_kb_selection` 与 `_build_knowledge_search_tool` 根据本次请求构建检索白名单；本次检查确认该代码路径，真实检索与引用验证留在验收阶段。

## 基线与验证

- 仓库：`dataelement/bisheng`，目标 `feat/bisheng-work-120-main`，远端核对 SHA `2a726f5c97be74670d99718cdc475cb1f7331b62`。
- 工作目录：`.worktrees/bisheng-chat-knowledge-session-isolation`；分支 `codex/chat-knowledge-session-isolation`。
- 本次修改属于桌面嵌入的 Web Chat。桌面参考目录 `.worktrees/dsh-desktop-v090-integration` 检查时干净；已安装参考 Harness `0.2.1-rc.2`。DSH 旧仓库的远端 `v0.9.0` 分支查询返回空，Web 修复采用上述毕昇目标分支。
- 定向 Jest：4 个文件、31 项通过，覆盖 C1/K1 与 C2/K2 往返、组件重挂载、发送、重新生成、清空、首条消息 ID 迁移、迟到响应、账号隔离、主 Chat 与订阅草稿隔离、默认值、组织库开关及存储异常。
- 客户端生产构建通过。依赖使用现有安装目录；测试通过本地启动辅助文件提供 jsdom 的 TextEncoder/TextDecoder，Babel runtime 通过 NODE_PATH 定位。依赖版本与锁文件保持。
- 扩展输入框回归：17 项中 13 项通过，4 项工具／技能显示预期失败。对同一 SHA 的原始源码独立运行后，4 项失败名称与断言相同，记录为基线失败。相关组件与这些测试保持原有内容。
- 架构检查与差异空白检查通过。客户端、管理端、共享 UI 和文件预览库 ESLint 通过；客户端、管理端和文件预览库类型检查通过。
- 本地证据：`outputs/chat-knowledge-session-20261028/`。

## Windows 验收清单

使用可访问 K1、K2 的同一普通账号，给两个空间准备互相可区分的资料和答案。

- [ ] C1 选择 K1；C2 选择 K2；往返切换至少三次，选择标签分别显示 K1、K2。
- [ ] 关闭窗口并重开、重启客户端后分别进入 C1、C2，选择分别恢复。
- [ ] C1、C2 各发送后续问题，检查请求中的空间 ID 与实际检索来源、引用来源分别属于各自空间。
- [ ] 分别重新生成回复，检查检索范围和引用来源。
- [ ] 清空 C1 后重开，C1 保持空范围，C2 保持 K2。
- [ ] 新 Chat 选 K1 并发送，正式 ID 生成后重开，保持 K1。
- [ ] 首条消息仍在生成时切换 C2，返回的响应保存在原会话，前台 C2 保持 K2。
- [ ] 旧会话缺少独立选择记录时显示空选择，重新选定后再执行上述流程。

## 审查

按仓库 code-review 技能完成边界、权限、并发、信息泄漏、测试、代码风格和文档七项复核。修复直接替换普通 Chat 的共享选择读取和账号级持久化；请求协议与后端权限链沿用现有实现。Windows 原生、真实提供方、真实知识检索与引用、跨设备同步分别按上述证据边界记录。
