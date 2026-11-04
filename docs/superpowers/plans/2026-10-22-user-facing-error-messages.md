# User-facing Error Messages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after user confirmation. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 原始对象、技术异常和未识别的后端错误不直接进入用户提示，保留完整诊断证据及既有业务错误分支。

**Architecture:** 在两端请求适配层收紧用户文案选择；共享包继续只保留错误结构与无 UI 的模板处理。上传异步解析失败单独收口，因为其成功轮询响应不经过请求失败出口。不靠格式猜测把任意字符串认定为安全文案，也不把全部业务失败抹平成通用错误。

**Tech Stack:** 现有 TypeScript、@bisheng/api-client、i18next、Vitest / Jest、React Testing Library；浏览器拦截接口验证，不新增依赖。

**Spec:** `features/v3.0.0/088-request-error-contract/spec.md` AC-03、AC-14、AC-19 及 design.md 的“message 是本端翻译后可读消息”约定。本计划修复既有契约的遗漏，采用维护路径；如发现必须改变产品恢复行为，停止该项并找用户判断。用户于 2026-10-22 确认开发。已在隔离分支实现，验证状态见同目录 verification 文档。

## Global Constraints

- 实施前拉取最新 `feat/3.0.0`，在 `codex/user-facing-error-messages` 开发；不混入其他任务，不自动合并、推送或同步 release。
- 保留 `cause`、`response`、`status_message`、`data`、错误种类、对象身份和 presentation 去重语义；不为友好文案吞掉异常或修改成功响应。
- 用户文案优先采用已登记错误码的本地化模板；网络/超时使用本地化提示；未知错误使用既有通用兜底。取消请求不提示，已全局处理或已展示的不重复提示。
- 只有已有明确业务契约的本地化业务文案可以保留。任意 Error.message、服务端 status_message、JSON、对象字段都不自动视为可信用户文案。先盘点依赖现有 message 的有效调用者，避免断开既有恢复流程。
- 模板参数按字段语义审计：保留业务需要的文件名、数量等；不能把 exception、堆栈或任意对象通过插值重新带回用户提示。检查已有错误翻译模板及后端实际数据，不只扫描 toast 调用。
- 不修改设计样式，不新增库；新文案补齐 zh-Hans/en/ja，错误码生成文件通过既有脚本更新，不手改。
- 2FA 的 5 个 error.message 回调未被子组件调用，只清理死接线，不计作 5 个可触发缺陷；不恢复死入口。
- 不新增自动原始异常日志，避免重复记录或引入敏感数据输出；原始证据继续随错误向调用方传播。
- 测试单 worker，两端构建串行，记录并对照现有 lint / 类型基线。

## Review Focus

1. 已知业务码仍有具体可读提示，配额/冲突等恢复分支继续工作；见任务 1。
2. 未知码、普通异常、对象、数组、循环对象及含堆栈字符串不泄露原始内容、不导致二次异常；见任务 1。
3. 已是 ApiError 的对象不会因幂等返回绕过文案收口，且身份与证据不丢失；见任务 1。
4. 上传轮询 HTTP 成功但文件解析失败，只提示一次；未知 remark 兜底，已知 ASR 等场景保持具体提示；见任务 2。
5. silent、取消、登录/权限/许可证全局处理仍按原契约执行，不新增重复 toast；见任务 1、任务 3。

## Task 1: 收紧两端统一错误出口

**Files:**
- Modify: `src/frontend/platform/src/controllers/request.ts`
- Modify: `src/frontend/client/src/api/request.ts`
- Audit / necessary modify: `src/frontend/client/src/utils/apiStatusError.ts` 及两端错误码翻译模板的有效消费链
- Test: `src/frontend/platform/src/controllers/requestErrors.test.ts`、`requestCompatibilityMatrix.test.ts`、`requestSessionFailure.test.ts`
- Test: `src/frontend/client/src/api/requestUserMessages.test.ts`（新增）及 `src/frontend/client/src/utils/apiStatusError.test.ts`
- Only if required: `src/frontend/packages/api-client/src/apiError.ts`、`apiError.test.ts`；共享层不引入翻译或 UI。

**Interfaces:** 保留 `showApiError(cause: unknown)` 的现有返回类型、调用约定和去重行为。用户显示文案由适配层决定，normalizeApiError 继续保留原始证据；不增加靠 error.message 判断的业务分支。

- [x] 盘点两端消息构造、已存在 ApiError 的创建者及 message 消费者；区分业务提示、诊断、错误分支。记录应保留的具体错误提示和业务恢复分支，核实错误模板是否插入技术异常。
- [x] 补失败测试：普通 Error('SQL / stack / URL')、未知错误码、原始字符串/对象/数组、循环对象、已存在 ApiError 和含技术 exception 的模板参数，最终提示必须为本地化兜底或已登记的安全业务文案；已知码和必要业务参数保持正确。
- [x] 运行新增及现有请求测试，确认新测试因文案透出而失败，记录 RED；不能因测试配置故障认定 RED。
- [x] 统一请求标准化、兼容包装层及 showApiError 的文案选择，移除把原始消息/JSON作为用户兜底的路径；处理已存在 ApiError 的显示路径，保持对象身份与原始证据。先改创建者，再确认旧对象显示也不会漏出。
- [x] 运行同组测试确认 GREEN，断言原始证据引用、业务码、重试分类、取消/静默及 presentation 去重没有变化；运行 `pnpm check-i18n`。
- [x] 单独提交统一出口与回归测试。

## Task 2: 收口上传与异步解析失败提示

**Files:**
- Modify: `src/frontend/platform/src/pages/KnowledgePage/knowledgeParseFailureMessage.ts`
- Modify: `src/frontend/platform/src/pages/KnowledgePage/components/FileUploadStep4.tsx`
- Modify: `src/frontend/platform/src/components/bs-ui/upload/simple.tsx`
- Audit / necessary modify: `src/frontend/client/src/api/knowledgeParseFailureMessage.ts`、`src/frontend/client/src/pages/knowledge/hooks/useFileUpload.ts`；复用任务 1 的请求出口，不重复写转换器。
- Test: platform `FileUploadStep4.errors.test.tsx`、`simple.errors.test.tsx`；client `uploadFailureContract.test.ts`、`uploadTerminalErrors.test.tsx`；根据解析器可测性补同目录纯函数测试。

**Interfaces:** 保持上传回调、文件状态及轮询次数；known parse failure → 既有本地化文案，unknown parse failure → 既有解析失败提示。文件对象中的原始失败证据不被用户展示字符串覆盖；若目前没有独立字段，先核对有效消费者再做最小调整。

- [x] 追踪上传接口失败、preCheck、异步解析 remark 到 toast/行内提示的所有有效路径；审计客户端同类逻辑，已安全的路径只补回归，不机械改写。
- [x] 补失败测试：未知 remark 字符串/JSON/对象使用解析失败兜底；已知 ASR 和业务码仍正确；重复轮询同一失败文件只提示一次；preCheck 抛技术异常不直出，既有本地校验提示保持。
- [x] 运行并确认 RED，移除解析器及调用者的原始串兜底，preCheck 的任意异常交给统一出口；明确 preCheck 本地用户文案的产生者，不凭对象里有 message 就信任。
- [x] 同组测试 GREEN；验证单次上传、失败状态、文件重试与 loading 恢复不变。
- [x] 单独提交上传修复。

## Task 3: 清理无效 2FA 回调并完成验收

**Files:** `src/frontend/client/src/components/Nav/SettingsTabs/Account/TwoFactorAuthentication.tsx`、`TwoFactorPhases/{SetupPhase,QRPhase,VerifyPhase,BackupPhase,DisablePhase}.tsx`；本计划同目录 verification 文档（实施时新增）。

- [x] 再次确认 5 个阶段组件未调用 onError，删除父组件传参和对应未使用 Props；保留实际 mutation 的本地化失败提示。不为清理死接线新增一套 2FA 实现。
- [x] 跑相关测试及类型检查，搜索确认没有遗留失效回调；执行两端请求、上传与共享错误包测试。修改触及的旧中文文案按仓库规则提取。
- [x] 运行 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`，与实施前基线比较；不增加 suppression。串行构建两端，必要时生产启动检查。
- [x] 浏览器已使用真实 ApprovalPage 新增弹窗、FileUploadStep4 及两端错误出口，模拟失败接口验证；段落仅验证真实删除 API 与测试表单的错误出口，完整段落页面未联调，列入业务验收。
- [x] 静态确认 2FA 的既有错误提示不变；没有可用后端时不宣称真实认证流程验收通过。
- [x] 独立 review 并输出验证/业务验收清单，分别列明已测、未测和基线问题；提交清理和交付文档。用户明确要求后再合并推送。

## 暂不实施

- 不把所有异常都变成同一句话；保留已登记的业务原因。
- 不全面重做后端错误码；未知错误码单列后续，不能以展示原始异常替代登记。
- 不重复迁移已经改好的 Paragraphs 和审批 catch，也不把旧行号当当前缺陷依据。
- 不扩展到模型生成正文、工具输出、诊断控制台等非失败 toast 场景。
