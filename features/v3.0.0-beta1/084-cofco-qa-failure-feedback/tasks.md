# F084/F085 Implementation Plan

用户2026-11-05已确认Spec/Design并授权开发。工作区继续使用中粮1111分支，不合并、不推送、不部署。采用计划执行、测试驱动、按独立文件范围并行接线，最终独立审查。

**Goal:** 日常/任务模式按PRD场景保留真实失败来源，结构化透传与历史一致；任务检索步骤显示可见名称。
**Architecture:** common定义FailureInfo/FailureContextAdapter，实际调用边界识别来源，模式内包装合并字段。复用原消息/任务/步骤JSON，不改表列和权限规则。
**Tech Stack:** Python/FastAPI/SQLModel，React/TypeScript，既有SSE/WS和三语系统。
**Spec:** 本目录spec.md/design.md；../085-cofco-knowledge-step-name/spec.md/design.md。

## Global Constraints

- 仅日常/任务；全局api/request.ts拦截、独立工作流/页面及权限规则不改。
- 无DDL/数据回填；旧码、事件、工具名、重试/降级/执行身份不变。
- 新增原因识别以PRD为准；业务/未知不强归五类；原始异常受控日志，公开对象脱敏。
- frontend不默认运行本地测试/构建；新增测试可编写，未运行不得报通过。

## Shared interfaces

- `common/schemas/failure.py`: FailureCategory五类、FailureReason内部细分、FailureInfo(version/failure_id/category/service?/service_name?/operation?/occurred_at/trace_id?)。
- `common/services/failure_context.py`: `FailureContextAdapter.capture(exc, *, category=None, service=None, service_name=None, operation=None, reason=None) -> dict | None`；在真实边界指定category/service，附加上下文并保留原异常，不改变重试。
- `FailureContextAdapter.from_error(exc) -> dict | None`: 继承原包装/异常链来源；仅可靠SDK/驱动类型可兜底推断，未知/业务返回None；同一错误对象保持ID/时间。
- `FailureContextAdapter.safe_detail(exc) -> str`: 公开安全说明，不返回异常原文；`FailureContextAdapter.validate(info) -> dict | None`白名单校验公开结构。
- `FailureContextAdapter.from_payload(payload) -> dict | None`: 从既有内部错误信封/平台软返回中读取并安全校验failure_info，禁止按任意文本猜来源。
- 步骤元数据：`extra_info.failure_info`、`extra_info.knowledge_target`；日常工具事件`failure_info`；日常终态`extra.failure_info`；任务`output_result.failure_info`和WS data.failure_info。

## Review Focus

1. SDK业务错误与真实服务失败分离，模型供应方内部数据错误仍归模型，平台Redis故障不归模型。
2. 局部工具失败不终止整轮，未知失败也不能伪装正常无命中。
3. 实时/刷新/补发同一failure_id与时间，部分答案、旧extra/output_result和恢复字段不被覆盖。
4. 名称候选非授权证据；真实ID/批量可见性/个人库隐私/旧历史中文兜底/memo刷新。
5. detail/exception/历史只读均不泄露凭据或内部原文，消息新字段不扩散到全局HTTP拦截。

## Tasks

- [x] T1 公共失败模型、原因分类、安全序列化：先写test/common/test_failure_context.py，验证五类、PRD反例、包装继承、ID稳定和脱敏，RED→GREEN；实现上述共享API。读取相关SDK真实异常类型。
- [x] T2 日常/模型/检索/工具异常接线：先补模式内传播测试；在转str/空结果前捕获、失败项透传、模型真实边界标记；保留软失败和重试。保存extra/events，与SSE同源。
- [x] T3 任务终态/步骤/名称接线：先补任务/mapper/名称测试；合并output_result，WS/历史保留元数据；同一候选批量核验，mapper纯转换，开始/结束/补发快照不丢。
- [x] T4 前端消费/展示/三语：新增FailureInfo验证/解析工具和类型，补日常/任务/历史/部分答案；复用卡片；名称前缀/兜底/展开/memo。编写针对性测试，不默认执行本地前端命令。
- [ ] T5 PRD覆盖台账、集成回归、架构检查和独立审查：逐项记录24历史示例及模式内复合来源；定向backend pytest/ruff/arch-guard；补E2E手工清单，不触碰105共享资源。修复实质发现。

## Progress / rulings

- 2026-11-05：用户确认进入开发；不是新增全局错误中心。公共契约先固定，独立文件范围并行，按T1—T5累计验证。

- 2026-11-05 重启恢复：保留已写改动，后端测试串行运行；前端仅读写文件，不运行测试、lint、类型检查、构建或 Vite。
- T1/T2/T3 验证：公共/供应方/存储边界 46 项、任务转换/名称/原有重试 63 项、日常流/历史/真实 ToolNode 12 项，共 121 项通过。应用启动、真实中间件和浏览器联调未执行。
- T4：三语、可选元数据、业务提示、移动端、部分结果、后台会话错误、断线查询及超长文件拆分已接线；新增前端测试已写，未运行。
- T5：独立审查的五组 P1 已修复；见 validation.md。Ruff 按 HEAD 比较无新增诊断，遗留告警仍在；架构检查仅保留 Endpoint 旧 DAO 导入警告。完整 E2E/场内验收仍待升级测试环境后执行，因此 T5 不标为全部完成。
- Ruling: 历史读取时裁剪原始错误及未授权名称，不回写数据库；共享 token 依赖仅移动到 domain 并保留原 API 导出，消除跨 API 导入，授权逻辑未变。
- Ruling: 真实启动响应丢失先查询已有版本；查询失败保留未知的执行状态及提示，不自动创建或重提任务。
