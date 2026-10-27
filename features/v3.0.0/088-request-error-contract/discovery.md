# F088 需求发现记录

日期：2026-10-22。状态：方向与 spec 均已获用户确认，design 待确认。

## 1. 已确认方向

用户询问 platform 拦截器消费错误后业务层无法取得状态和消息，是否需要与 client 统一；随后接受完整错误透传、提示与失败独立、渐进改造的方向，并确认五阶段计划，要求开始执行。

目标：两端业务层均取得完整错误，失败不进入成功流程，默认提示与业务恢复可以同时成立。

顺序：现状盘点与正式需求 → platform 请求入口 → platform 调用方 → client 契约与调用方 → 回归验收。

## 2. 实际代码证据

当前基线：`feat/3.0.0`，提交 `bc6ca25ba`，包含升级 `219bb0e8a`；两端 React Query 均为 4.44.0。隔离工作区由 Codex 原生 worktree 工具创建，起初基于 `72cee6ca5`；用户提醒升级后通过快进发版线同步已提交代码，未复制其他工作区未提交文件。

| 范围 | 已核实事实 | 核实方式 |
|---|---|---|
| platform 普通业务失败 | 通常 reject 消息字符串；部分分支为专用对象 | 阅读 `src/frontend/platform/src/controllers/request.ts` 响应成功拦截分支 |
| platform HTTP 失败 | 普通路径提示后 reject null；preserveError 可保留原异常 | 阅读同文件响应失败分支及 `dshRequestCompatibility.test.ts` |
| platform 旧包装层 | catch 后返回 false/undefined；即使拦截器保留错误，上层仍可能消费失败 | 阅读同文件 `captureAndAlertRequestErrorHoc` |
| platform 迁移规模 | 111 个非测试源文件引用旧包装层，包含定义文件；不能等同 111 个独立页面或全部活跃入口 | `rg -l 'captureAndAlertRequestErrorHoc' src/frontend/platform/src --glob '*.{ts,tsx}' --glob '!*.test.*'` |
| client 普通业务失败 | 未开启 skip403Redirect 的部分响应仍 resolve；showError 只控制对应提示 | 阅读 `src/frontend/client/src/api/request.ts` |
| client 局部严格路径 | skip403Redirect 等部分路径构造 Error，附加业务码和原始响应 | 阅读同文件及 `src/frontend/client/src/api/personalToken.ts` |
| 已有显式恢复 | 许可证状态读取失败返回 null、上报采用 best effort；不能机械清除全部 catch | 阅读 `src/frontend/platform/src/controllers/API/license.ts` |
| 特殊结果 11010 | 前端请求拦截器直接返回该结果；限定后端/两端 TS/TSX 的检索未发现其他相关代码命中 | `rg -n '11010' src/backend src/frontend --glob '*.{py,ts,tsx}'`；身份证示例中的数字子串不算业务引用 |

表中为静态代码阅读和检索证据。随后对升级基线运行了 4 文件 8 测试及 4.44.0 最小行为断言，均通过，记录见 design.md §7.1；这些不代表 F088 已实现，也不代表全部调用已完成活跃入口追踪。

## 3. 实施前与设计阶段待完成的核实

- 将旧包装层引用分为活跃入口、测试辅助和不可达路径；追踪直接请求、API 层再次 catch、查询 hooks 及回调的实际消费关系。
- 固定特殊结果、非统一响应、Blob 错误、许可证/维护/会话的现有处理矩阵。
- 已核实两端查询库基线为 4.44.0；设计与回归需保留新工厂、数组 key、offlineFirst、isInitialLoading，并处理新增配置查询吞错逻辑。
- 明确旧静默开关的现有全局处理例外，避免统一过程中无意扩大或缩小其作用。

这些是设计/实施盘点任务，不影响 spec 中完整错误、页面恢复、默认提示和范围目标的确定。

## 4. 工作流状态

采用 Full SDD：本次改变跨模块失败契约，依据 `docs/SDD-Guide.md` §1。Discovery 与 spec 已获用户确认；design 须依该指南 §3 单独确认。当前已准备设计、状态与候选调用清单，未更改产品代码。
