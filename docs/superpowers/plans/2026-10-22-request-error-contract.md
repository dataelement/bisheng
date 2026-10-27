# 请求错误契约统一计划（历史草案）

> 本文保留 2026-10-22 的早期讨论，不作为当前实施计划。后续规格、实现与验证以 [F088](../../../features/v3.0.0/088-request-error-contract/) 为准；下方未勾选项为历史状态。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task after the repository's SDD confirmation gates are complete. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** platform 和 client 的请求失败均保留完整错误，业务层可以恢复状态和处理业务分支，默认提示不会重复。

**Architecture:** 分离错误标准化、全局处理、业务处理。先在 platform 提供完整错误并兼容旧包装层，逐模块迁移后收敛旧行为；client 随后对齐同一错误契约。统一契约不要求合并两端请求实现或成功响应结构。

**Tech Stack:** TypeScript、现有 Axios 请求封装、两端现有查询库、Vitest / Jest。

**Spec:** 本会话已接受的方向；正式 spec/design 尚未建立。本文是范围与顺序草案，不替代 SDD 确认。

## Global Constraints

- 这是跨模块错误契约变更，实施前按 `docs/SDD-Guide.md` Full SDD 路径完成需求、spec、design 确认；版本线和 feature 编号在实施准备时核实。
- 保留两端成功响应结构；不引入新的请求、状态或 UI 库。
- 登录失效、会话被踢、通用权限跳转、许可证和维护遮罩继续集中处理；具体业务不新增通用 403 分支。
- 默认提示与错误透传独立；取消请求不弹失败提示，静默请求仍向调用方传递错误。
- UI 改动遵守当前设计规范；触及旧中文字符串时同步完成三语言提取，不手改错误文案生成文件。
- 当前工作区有其他改动，实施需隔离，不能混入查询库迁移等其他工作。

## Review Focus

- HTTP 200 中携带业务失败时，严格契约下必须进入失败分支。
- 错误已经全局提示时，调用方仍能取得完整错误，且不再次提示。
- 旧包装层返回 false/undefined 的调用方不能在迁移时误走成功流程。
- 登录/权限/许可证/维护并发异常仍只触发既定全局处理；错误数据保持可辨认。
- 网络失败、取消、非标准响应和文件下载不能被误判为普通业务响应。

## 1. 盘点并确定验收边界

**Files:** `src/frontend/platform/src/controllers/request.ts`、`src/frontend/client/src/api/request.ts` 及实际调用方；正式 feature 文档路径待版本线核实后确定。

- [ ] 建立调用清单：直接请求、旧错误包装层、自定义提示、按错误码分支、依赖 false/undefined 的后续逻辑。
- [ ] 明确 HTTP 状态与业务错误码的区别，定义错误对象保留消息、附加数据、原始响应、原始异常及提示状态；网络错误允许没有响应。
- [ ] 明确旧特殊返回码（包括 platform 的 11010）、Blob 下载和 client 非统一响应接口的成功判据，禁止把缺少 status_code 一律当失败。
- [ ] 将上述 Review Focus 写成可检验 AC，完成 SDD 需求、spec、design 确认。

## 2. platform 保留完整错误

**Files:** `src/frontend/platform/src/controllers/request.ts`；新增同目录错误模型与拦截器测试文件，具体拆分在 design 中固定。

- [ ] 先补标准业务失败、HTTP 失败、网络异常、取消、静默请求及全局处理分支测试。
- [ ] 将普通失败标准化为错误对象并 reject，默认提示不再以丢弃错误对象为代价。
- [ ] 兼容旧错误包装层的返回值和提示方式，避免结构化对象显示为 JSON 或重复提示；新调用方走严格失败契约。
- [ ] 运行拦截器测试及现有 DSH 请求兼容测试，验证已有 preserveError/silent 场景。

## 3. platform 调用方分批迁移

**Files:** 第 1 步清单中的 API、页面和 hooks；每批在 tasks 中列出实际文件。

- [ ] 优先迁移表单提交、编辑保存、删除和业务冲突处理，再覆盖其余旧包装层调用。
- [ ] 每批先补关键失败行为测试，再将 false/undefined 判断改为明确失败处理，确保 loading 恢复、输入保留、弹窗不会错误关闭、失败不显示成功提示。
- [ ] 自定义提示的请求关闭默认提示；仅恢复状态的调用方继续使用默认提示。
- [ ] 全部相关调用迁移并验证后再清理旧包装层和冗余开关，不能提前全局改变其返回语义。

## 4. client 对齐同一契约

**Files:** `src/frontend/client/src/api/request.ts` 及第 1 步定位的 API、hooks 和页面；拦截器测试在 design 中固定文件名。

- [ ] 先覆盖当前 HTTP 200 + 业务失败仍 resolve 的场景，以及依赖返回体判断错误的调用方。
- [ ] 分批切换为同一错误模型和 reject 语义，同步迁移调用方；避免把开关全局翻转后再补页面。
- [ ] 提示开关仅决定提示行为，不能决定请求是否算失败；保留并验证维护遮罩、会话和通用权限处理的既定效果。
- [ ] 删除迁移后的重复错误构造、手工解析和重复提示，运行相关 Jest 回归。

## 5. 完整验收和收尾

**Files:** 两端受影响测试、正式 feature 的 AC / tasks / E2E 报告、适用范围内的开发约定。

- [ ] 完成 `/e2e-test`：覆盖成功、业务失败、网络失败、登录过期、权限不足、表单失败恢复、下载及并发错误提示。
- [ ] 从 `src/frontend/` 运行 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`，并运行受影响的 platform Vitest 和 client Jest 测试。
- [ ] 检查剩余吞错、失败后成功提示、未处理 rejection 和重复 toast；仅保留明确的业务恢复行为。
- [ ] 完成 `/sdd-code-review`，记录兼容边界和迁移完成情况；验收依据是运行结果及调用清单全部闭环。

**验收结果：** 两端业务层取得一致、完整的错误；请求失败进入失败流程；每个请求按配置提示且不重复；已有全局处理和成功响应保持约定行为。
