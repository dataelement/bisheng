# 后台相似文档 UI 对齐及删除阻断说明

依据：用户 2026-11-17 要求后台相似文档照搬前台 UI 逻辑，并明确提示失败任务为何阻止空间删除。基线 ed1062e82a；独立工作区处理，主工作区保持。此修复只使用已有业务接口，没有实现 F024 的新任务处置契约。

## 已实现与验收口径

| AC | 行为 | 覆盖 |
| --- | --- | --- |
| UI-01 | 相似入口打开独立双栏弹窗：左侧待处理文件，右侧当前文件、推荐卡片、搜索和保持独立四部分；不嵌套版本 Sheet | spaceSimilarDocumentDialog、f118SpaceVersionOperations |
| UI-02 | 推荐显示相似度、主版本、编号及可用上传信息；当前选择保持，文件处理成功后移出列表并选择下一项 | spaceSimilarDocumentDialog |
| UI-03 | 300ms 防抖、Enter/搜索按钮、清空关键词和切换文件退役旧搜索；维持当前有权限的分页接口及更多加载 | spaceSimilarDocumentDialog、knowledgeVersionsContract |
| UI-04 | 关联方向为当前文件成为候选文档的新版本，明确确认才写；保持独立调用原 dismiss；失败保留，未知结果禁止重复写和切换 | spaceSimilarDocumentDialog、f118SpaceVersionOperations |
| UI-05 | 身份/租户/空间/文件/开关变化隔离打开和请求；旧确认不得写新目标，读失败有重试且不伪装为空列表 | spaceSimilarDocumentDialog、f118SpaceVersionHistory、f118SpaceVersionOperations |
| UI-06 | 10999 的源输入占用 reason 明确解释复制/移动失败仍需要源文件，因此阻止删除；指向目标空间处理任务及权限不足时联系发起人/管理员；不泄露目标信息 | useKnowledgeDeletion、KnowledgeDeletionDialog |

参照 Client `SimilarDocumentDialog` 的业务交互与布局；Platform 使用自己的 scope、@tanstack/react-query v4、wrapped request、bs-ui Dialog 和 @bisheng/ui。没有引入 Client Recoil、Provider 或 API 模块，也没有复制前台的无界搜索和过期搜索词行为。既有版本合并、上传和主版本操作保持原方向。

## 验证

- 6 个相关 Vitest 文件：58 passed（pending 双栏、成功推进、搜索切换、迟到确认、未知结果、读错误、直接入口单弹窗、版本/删除既有回归及 API 契约）。
- frontend `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`、Platform 构建通过；三语文案齐全。i18n 的 85 个既有 frontend-only 错误码提示和构建的大 chunk 提示保持。
- 增量架构守卫及 git diff --check 无违规。
- 本地测试覆盖新 UI 业务行为，未将构建部署到 116，未宣称真实浏览器/MySQL/DM8/worker 环境验收通过。

## 七维自审

| 维度 | 结果 | 依据 |
| --- | --- | --- |
| 边界条件 | PASS | 非法范围不读、空态/错误分离、游标不前进报错、已有不可见项不补造 |
| 权限与认证 | PASS | 原动作入口及服务端权限过滤不变，使用现有相似/搜索/关联接口 |
| 并发安全 | PASS | AbortController、本次打开缓存、范围 key、单飞写、确认退役、未知结果冻结 |
| 信息泄露 | PASS | 删除说明使用已有 reason，不拼内部任务/目标链接，不展示堆栈 |
| 测试覆盖 | PASS_WITH_WARNINGS | 自动化通过；真实浏览器联调及部署验收待进行 |
| 风格 | PASS | Platform 组件、严格 TS、三语，无新增忽略或依赖 |
| 设计同步 | PASS | design.md 已同步；F024 根因及新契约候选分开记录 |

## 任务处置另行确认

F024 的 [现场根因报告](../024-knowledge-task-resolution/116-task-failures.md)、[需求规格](../024-knowledge-task-resolution/spec.md)和[候选设计](../024-knowledge-task-resolution/design.md)已整理。进度、放弃、整体回退涉及新契约，尚待用户确认；本次 UI 提交不声称这些能力已存在，也不恢复 116 现场任务。
