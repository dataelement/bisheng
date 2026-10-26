# F088 实施与验收记录

日期：2026-10-22。隔离工作区：`/Users/shanghang/.codex/worktrees/request-error-contract/bisheng`；分支`codex/3.0.0-088-request-error-contract`；基线`bc6ca25ba`。本节为实施验收时点记录；随后用户授权合并推送，最新发版线集成验证见integration-report.md。

## 结论

两端错误契约与已核实活跃消费链的产品修改已落地，独立代码复核限定范围通过。**整体验收未通过，不能宣称可合入**：根lint/typecheck及全量回归仍有已复现的基线失败，真实后端页面E2E未执行。实现完成与验收完成分开记录。

## 实现

- 共享ApiError保留HTTP状态、业务码、可读消息、业务data、原response/cause及transport code；取消、静默、已展示/全局接管均继续可识别失败。
- platform默认通知后继续reject；原HOC生产调用清零，兼容导出不再返回false。client保留原认证/刷新队列和成功结果，在原处理后追加规范化；WeakMap记录实际已发生的提示/全局动作。
- 两端保留React Query 4.44.0现有工厂、缓存键、offlineFirst与原重试预算；新业务失败不变成成功null或额外重试。
- 表单/确认/编辑器在成功后关闭或跳转，失败恢复锁并保留输入；列表、详情和聊天历史区分失败与空结果，可重试。清空与异步读取绑定资源/会话，防止延迟结果覆盖新内容。
- 命名恢复保留：10601重置密码、11010遗留交互、Skills未导入/重名覆盖、配额批次早停、公众号返回修改、引用过期、许可证/权限/维护/被踢处理及批量部分成功汇总。
- HTTP preview callback携带原错误；下载原始二进制/headers不改写。上传、导出/导入、语音及制品终点尊重取消/global/presentation。

## 最终验证

| 检查 | 实际结果 |
|---|---|
| 共享错误包 | 12/12测试通过；tsc与lint通过 |
| platform完整Vitest | 197文件：196通过/1失败；948测试：946通过/2失败。最后附件修复后完整重跑，剩余2项均为干净HEAD同样失败的旧断言，无unhandled汇总 |
| client完整Jest | 111 suites：80通过/31失败；707 tests：687通过/20失败。与同依赖干净HEAD完整95 suites对照，新增失败suite为0；原1个制品测试suite已修复，剩余31个均在基线失败 |
| platform生产构建 | 通过（最后附件计数修复后运行） |
| client生产构建 | 通过（最后导出/上传修改后运行） |
| platform strict类型 | 800个strict文件，仅1项已复现的clientVoiceDraft旧测试参数错误；本次新增文件无类型错误 |
| client strict类型 | 1493个strict文件全部通过 |
| 根pnpm lint/typecheck | 已执行，未通过；分别阻断于platform既有85项lint和下述旧测试类型问题 |
| platform lint:prune | 85项既有错误；与干净HEAD同5文件同85项。新增/修改链的聚焦lint通过 |
| client lint:prune | 28项错误+1项警告；HEAD同依赖101项错误+1项警告，本次缩减73项错误；最后终审修改文件聚焦lint通过 |
| 翻译检查 | check-i18n通过，无新增漂移；新键同批三语言 |
| 抑制基线 | 仅通过lint:prune收缩：platform2258→2210，client2044→1994；逐文件/规则比较无增加 |
| 架构与空白 | 修改前端源逐文件arch-guard无输出；git diff --check通过 |
| 真实后端E2E | 业务页面未执行；后续已启动两端Vite并复用主工作区已有120代理，页面及两端env探测通过。清单见e2e-checklist.md，不用连通性/单测冒充浏览器验收 |

完整Jest的31个旧失败suite含Node环境全局setup访问Element、旧权限控件缺ConfirmProvider、ESM夹具转换/旧Skills归档夹具等。完整Vitest的旧断言与类型失败见下一节。不扩大本次特性去修改这些发版线存量问题。

## 基线对照方法与剩余门禁

从`git archive bc6ca25ba src/frontend`导出干净源码至`/private/tmp/f088-baseline-frontend`，链接同一已安装依赖运行对照，没有清理/切换共享工作区，也没有手工修改抑制文件。

- platform旧失败：`knowledgeSpaceGrantSubjects.test.tsx`两项断言分别未包括已有部门路径/外部ID字段、仍期望旧groups pageSize200。干净HEAD同文件8测试中相同2项失败；当前保留。对应selector业务实现未因本特性改变。
- platform旧类型失败：`src/test/clientVoiceDraft.test.tsx:47`向无参回调传入true；干净HEAD独立typecheck同样失败。
- platform lint的85项集中于`useSubjectSearch.ts`、`controllers/API/index.ts`、`controllers/API/license.ts`、`f067LicenseBannerCopy.test.ts`、`sandboxEndpoint.test.ts`。本次API/index只改错误callback证据/取消，不新增any；新增/修改行聚焦检查无新违规。
- client的28项lint错误为`chatApi.ts`17项既有any及未改动CitationReferencesDrawer/skillMenuSelection/useSubjectKeyword等遗留项，另有旧unused-disable警告。抑制阈值没有放宽。
- UI/交互真实环境验证仍需现有管理员与普通用户账号及可达后端，按e2e-checklist逐项记录后再做合入验收。

## AC追溯

| AC | 自动化/静态证据 | 页面验收 |
|---|---|---|
| AC-01、AC-02、AC-03、AC-04 | packages/api-client apiError；两端requestErrors/clientRequestContract/requestCompatibilityMatrix；二进制/传输原对象引用断言 | 待真实后端抽验 |
| AC-05 | legacy helper reject、businessWrappers.errors、knowledge.errors、previewFileSplit.errors、skillCenterErrors及活跃调用链审查 | 待 |
| AC-06、AC-07、AC-08 | 默认/silent/opt-in adapter断言；showApiError幂等、exportFailureContract/importFailureContract/uploadTerminalErrors、skill专业提示 | 待 |
| AC-09、AC-10 | 模板纯函数、validation数组、三语言检查、取消矩阵与业务终点取消回归 | 待 |
| AC-11 | PromptDialog/Workbench提交刷新分离/ModelConfig详情、Finetune/EditLabel/TextInput、useConfirm、inline rename和Dashboard顺序链 | 待 |
| AC-12 | queryConfigMigration、useSystemConfigEnvelope、sidebars/source/article/picker失败重试、审批列表详情与chatHistoryErrors | 待 |
| AC-13 | member toggle、service/account状态、文件删除rollback、清空失败保留和跨资源归属、QA批量/单项状态 | 待 |
| AC-14 | Skills11053/11055、上传19403插值早停、公众号取消/过期请求、分享/引用过期、专业批量汇总 | 待 |
| AC-15、AC-16 | platform会话踢出/后续401、并发license节流与silent/showError区别；client Blob全局动作与原认证代码保留审查 | 真实账号/刷新队列并发仍待 |
| AC-17、AC-18、AC-19 | 非envelope/成功下载/headers、11010、错误Blob/无MIME HTTP失败、messageExport原对象与文件名回归 | 待 |
| AC-20、AC-21 | 两端真实统一入口已接线、生产HOC迁移及限定活跃链独立审查；不以文本扫描代替运行时全覆盖 | 整体验收未完成 |

## 独立复核与发布状态

platform-code-review.md与client-code-review.md记录限定活跃链的Spec/Quality PASS及覆盖边界。最后上传计数闭环与ModelConfig详情失败回归也纳入复核：platform两次最终聚焦分别47项、27项；client最后精准复核41项通过。审查不认证未检查旧路径，更不认证真实后端部署、权限账号或浏览器E2E。

按SDD七维，当前无已知未关闭的新增产品代码阻断；边界、并发、鉴权兼容、证据保留、风格及文档在已检查范围通过；**测试/验收维度仍为NEEDS_FIX**（基线门禁与真实页面执行未关闭）。`T006`保持未勾选，Overall：**NEEDS_FIX（验收未完成）**。

## 主要命令与证据

受控adapter/组件测试使用本地Vitest/Jest；完整命令保留于各迁移/审查报告。主要日志：`/private/tmp/f088-platform-completion-tests.log`、`f088-client-full-final.log`、`f088-client-baseline-full.log`、`f088-platform-baseline-assertions.log`、`f088-platform-completion-build.log`、`f088-client-build-final.log`、`f088-platform-completion-types.log`、`f088-client-types-latest.log`、`f088-client-regression-comparison.json`、`f088-platform-prune-latest.log`、`f088-client-prune-final.log`。

## 后续集成

用户已明确授权停止Vite、合并推送feat/3.0.0并删除开发分支。合入最新发版线的冲突处置及重新验证见integration-report.md；保留本报告原始验收限制，不将E2E改为通过。
