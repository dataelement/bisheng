# beta2 误回退修复恢复与审计

日期：2026-11-25。基线：`f92e2c71080d846e3a704a5c223cfc3e2a6f1a16`。审计提交：`5e57d80ab2fbb0e1967f44014eebac691ccb3f4b`。

## 结论与原因证据

逐项核对该提交的 64 个文件，恢复 35 个文件中的无关回退、测试和说明，保留其余 29 个文件。三份 bs 文案文件只恢复工具测试提示，不覆盖新知识权限/溯源文案。

用户提供的操作说明为：从落后 tip 执行 `git reset --soft` 对齐 origin，索引仍停留在旧树，随后全量提交。该操作能解释本次 diff：祖先已经包含的多个独立修复在同一提交内被完整回退，测试和说明同时消失。但 Git 提交对象不记录本地 reset 命令；命令本身的归因依据是用户提供的说明，独立可验证的事实是下表中的逐文件回退。

116 运行源码曾与当时 release 的工作流路由、执行端口、准入三个文件摘要一致。问题是分支内容回退，不是仅凭 release 标签就能归因为部署遗漏。修复提交仍在祖先中也不保证修复逻辑仍在当前树。

## 确认恢复的内容

| 范围 | 被丢失的行为与恢复 |
| --- | --- |
| 免登录工作流 | 恢复端点绑定 published_only，忽略脱敏展示图，读取服务端当前版本，继续验证身份、租户及实际引用；恢复 19 个用例及设计/现场记录 |
| 自定义 API 工具 | 恢复参数放在 JSON Schema properties 下、OpenAPI 3.1/nullable/union/free-form object 兼容、空白可选参数省略；恢复相关三份测试文件 |
| 已保存工具测试 | 恢复服务端读取已保存密钥的测试路由、编辑动作与租户/归属校验、路径编码及响应凭据遮罩；前端不再把掩码当真实密钥发送，配置改变时要求重填密钥；恢复前后端测试和三语提示 |
| 授权管理 | 恢复空用户身份在所有权限模型下隐藏、历史无效身份禁止 MOVE；恢复受保护创建者与普通直接 owner 授权的边界测试/说明 |
| OnlyOffice | 恢复 open_api.public_base_url 为空时使用 bs_client.platform_public_url；原地址校验与后端生成回调 URL 保留；恢复测试和部署注释 |
| Moonshot | 恢复最大联网续调轮数、总时限/SDK 剩余预算及无进展拒绝；恢复同步、异步和取消等测试 |
| 请求作用域清单 | 恢复工作站 5 个接口、技能 auto-enabled 及已保存工具测试，共 7 条声明；由实际应用路由导出检查通过（1008 条） |
| 上传原文件名 | 仅恢复被删除的原始名称回归测试，生产实现未被此提交删除 |

## 明确保留的产品策略

- 内网/RFC1918 下载策略及原 DNS 固定、loopback/link-local 等地址保护。
- knowledge_auth/user_auth 关闭时跳过用户权限过滤，开启时按运行用户过滤；保留租户和绑定边界。
- 无原文权限的溯源项以 right=false 和提示展示、文件名空值处理与三语说明。
- 免登录界面隐藏自然人点赞/点踩控件，其他消息操作按原规则保留。
- 审计/标注的会话读取边界及异步管理员资格检查。

未将整个 `5e57d80ab2` 反向撤销。

## 验证

- 从 backend 目录运行恢复项与保留策略的组合回归：**302 passed**。仅本机 TLS 用例绑定 loopback 临时端口，模型与上游请求使用 mock。
- 原代码基线加入恢复测试后的有限子集：34 failed、7 errors、56 passed、6 deselected；失败覆盖公开执行端口、空用户 MOVE、旧平台回调、Moonshot 边界及模型参数 schema；7 个错误来自已删除的已保存工具测试实现。旧 Moonshot 的无进展用例会循环不结束，初次基线诊断已中断，有限子集排除该 6 项；修复后完整运行通过。
- 前端：EditTool/SystemPreset **11 passed**；api-client **52 passed**。全 workspace lint、typecheck、check-i18n 通过。临时工作树只补齐本地已安装依赖的符号链接，没有变更依赖清单或锁文件。
- request-scope 导出检查：**Validated 1008 declared route methods**。
- 修改的 Python 文件 Ruff 格式与 lint、git diff --check、架构守卫通过。守卫对 Office 测试合成凭据发出旧有提示，无 VIOLATION。
- 本次未部署 116、未改变远端数据库或调用真实模型；推送 beta2 不等于线上验收。

## 合入前七维复审（sdd-code-review）

| 维度 | 结果 | 核对要点 |
| --- | --- | --- |
| 边界 | PASS | 空图/篡改图/版本模式；可选空参数、nullable/复合类型；续调轮数/超时/无进展 |
| 权限认证 | PASS | 可信公开端点绑定执行策略；普通用户拒绝、跨租户/跨工具拒绝；保存密钥测试仍要求原超管入口及具体 edit |
| 并发安全 | PASS | 沿用既有来源重校验、事务与授权投影；当前版本切换回归通过，无新持久状态 |
| 信息披露 | PASS | HTTP 图继续脱敏，原密钥只留服务端，响应遮罩，错误仅复用现有业务协议 |
| 测试 | PASS | 恢复被删测试并做旧代码对照；保留策略组合回归通过 |
| 风格架构 | PASS | 无新依赖/表/迁移；请求清单由后端现存路由校验，Ruff 与架构守卫通过 |
| 文档 | PASS | 恢复既有设计和说明，下表覆盖全部 64 文件及处理决定 |

## 全部 64 文件核对清单

| 文件 | 决定 | 原因 |
| --- | --- | --- |
| `docker/bisheng/config/config.yaml` | 恢复 | OnlyOffice 旧平台地址兼容与测试/说明 |
| `docs/reviews/public-workflow-saved-execution-20261124.md` | 恢复 | 免登录工作流仅运行服务端当前版本及回归/说明 |
| `features/v3.1.0-beta2/006-reference-hints/design.md` | 恢复 | 免登录工作流仅运行服务端当前版本及回归/说明 |
| `features/v3.1.0-beta2/007-preset-tool-edit/design.md` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `features/v3.1.0-beta2/007-preset-tool-edit/e2e-checklist.md` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `features/v3.1.0-beta2/007-preset-tool-edit/review.md` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `features/v3.1.0-beta2/007-preset-tool-edit/spec.md` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `src/backend/bisheng/api/services/assistant_agent.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/bisheng/api/services/report_editor_security.py` | 恢复 | OnlyOffice 旧平台地址兼容与测试/说明 |
| `src/backend/bisheng/api/v1/mark_task.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/bisheng/chat_session/domain/chat.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/bisheng/chat_session/domain/services/mark_read_authorization.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/bisheng/chat_session/domain/services/session_read_authorization.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/bisheng/core/ai/llm/chat_moonshot.py` | 恢复 | 联网续调轮数、总时限及无进展拒绝 |
| `src/backend/bisheng/core/external/safe_download.py` | 保留 | 明确的内网下载策略及其测试 |
| `src/backend/bisheng/knowledge/domain/services/qa_recall_service.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/bisheng/knowledge/domain/services/space_flow_retrieval.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/bisheng/knowledge/domain/services/workflow_knowledge_authorization.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/bisheng/permission/domain/services/grant_service.py` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `src/backend/bisheng/public_endpoints/api/endpoints/workflow.py` | 恢复 | 免登录工作流仅运行服务端当前版本及回归/说明 |
| `src/backend/bisheng/tool/api/tool.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/bisheng/tool/domain/services/test_openapi.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/bisheng/workflow/application/execution_admission.py` | 恢复 | 免登录工作流仅运行服务端当前版本及回归/说明 |
| `src/backend/bisheng/workflow/application/execution_port.py` | 恢复 | 免登录工作流仅运行服务端当前版本及回归/说明 |
| `src/backend/bisheng/workflow/common/knowledge.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/bisheng/workflow/nodes/agent/agent.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/bisheng_langchain/gpts/tools/api_tools/openapi.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/bisheng_langchain/utils/openapi.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/test/api/test_assistant_knowledge_auth_gate.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/test/api/test_office_editor_sources.py` | 恢复 | OnlyOffice 旧平台地址兼容与测试/说明 |
| `src/backend/test/audit/test_audit_session_detail_scope.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/test/chat_session/test_session_read_security.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/test/core/test_generic_download_ssrf.py` | 保留 | 明确的内网下载策略及其测试 |
| `src/backend/test/core/test_safe_download.py` | 保留 | 明确的内网下载策略及其测试 |
| `src/backend/test/knowledge/test_preview_upload_space_compat.py` | 恢复 | 上传原始文件名测试被删除；业务实现仍在 |
| `src/backend/test/knowledge/test_qa_recall_authorization.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/test/knowledge_unification/test_wf_public_saved_execution.py` | 恢复 | 免登录工作流仅运行服务端当前版本及回归/说明 |
| `src/backend/test/mark/test_mark_read_security.py` | 保留 | 审计/标注读取边界及对应测试 |
| `src/backend/test/permission/test_f048_grant_policy.py` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `src/backend/test/security/test_polling_bounds.py` | 恢复 | 联网续调轮数、总时限及无进展拒绝 |
| `src/backend/test/tool/test_openapi_args_schema_wire.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/test/tool/test_openapi_blank_optional_params.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/test/tool/test_openapi_schema_type_forms.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/test/tool/test_tool_ssrf_entry_guards.py` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/backend/test/workflow/test_agent_knowledge_boundary.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/backend/test/workflow/test_knowledge_authorization_boundary.py` | 保留 | 知识权限开关 OFF/ON 的明确产品策略及对应测试 |
| `src/frontend/client/src/api/apps.ts` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/client/src/pages/appChat/ChatMessages.tsx` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/client/src/pages/appChat/components/ClientMessageFooter.tsx` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/client/src/pages/appChat/components/MessageButtons.tsx` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/packages/api-client/src/requestScopeRoutes.json` | 恢复 | 7 个仍存在的接口作用域声明 |
| `src/frontend/platform/public/locales/en-US/bs.json` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/frontend/platform/public/locales/en-US/flow.json` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/platform/public/locales/ja/bs.json` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/frontend/platform/public/locales/ja/flow.json` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/platform/public/locales/zh-Hans/bs.json` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/frontend/platform/public/locales/zh-Hans/flow.json` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/platform/src/components/bs-comp/permission/PermissionListTab.tsx` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `src/frontend/platform/src/components/bs-comp/permission/SystemPreset.test.tsx` | 恢复 | 空用户身份过滤、禁止 MOVE、所有者边界测试及说明 |
| `src/frontend/platform/src/controllers/API/index.ts` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
| `src/frontend/platform/src/controllers/API/tools.ts` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/frontend/platform/src/pages/BuildPage/tools/EditTool.test.tsx` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/frontend/platform/src/pages/BuildPage/tools/EditTool.tsx` | 恢复 | OpenAPI 参数 schema/类型/空值、保存密钥测试链路及三语提示 |
| `src/frontend/platform/src/pages/ChatAppPage/components/ResouceModal.tsx` | 保留 | 知识权限、溯源提示或免登录反馈展示的产品调整 |
