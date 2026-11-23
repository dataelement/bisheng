# Migration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline and a fresh whole-change reviewer.

**Goal:** 在最新3.1.0-beta1实现现有通用失败分类与安全展示。
**Architecture:** 真实依赖边界标注FailureInfo；模式服务合并到既有消息和步骤JSON；客户端安全读取及复用卡片。
**Tech Stack:** FastAPI/Pydantic、既有LLM框架、React/TypeScript、三语。
**Spec:** spec.md / design.md。

## Global Constraints

- 不合并或整包cherry-pick客户提交；不带知识步骤名称等定制功能。
- 保留主线credit_exhausted/context_overflow/context_compress_failed与原重试/停止/项目/桌面行为。
- 前端按用户约定不在本地运行测试、lint、typecheck、构建；相关验证交镜像CI，不宣称通过。后端定向回归照常。

## Review Focus

- 模型供应方内部数据库错误仍为模型；平台额度不变成模型失败。
- 包装和历史不泄露原始诊断，失败ID和时间稳定。
- 实时消息与历史均保留部分答案和来源。
- 已有上下文治理及桌面/项目状态不得丢失。
- 旧记录/未知错误/主动停止兼容。

### Task 1: 公共来源与依赖边界
- [x] 先迁移并运行test/common/test_failure_context.py、test_provider_failure_boundaries.py、test_storage_failure_boundary.py，确认缺少实现时失败。
- [x] 实现common/schemas/failure.py、common/services/failure_context.py，适配llm/domain/llm/*及core/storage/minio/minio_storage.py；复跑上述测试。

### Task 2: 模式执行、步骤与历史
- [x] 迁移纯错误传播测试并先运行。
- [x] 适配workstation/domain/services/{chat_service,chat_helpers,workstation_service}.py、tool/domain/services/executor.py、tool/domain/langchain/linsight_knowledge.py。
- [x] 适配linsight/domain/{task_exec.py,models/linsight_session_version.py,services/{stream_event_mapper,state_message_manager,resilience_middleware,workbench_impl,workspace_backend}.py}与提交SSE出口；不迁知识名称逻辑。
- [x] 验证失败来源、公开序列化及主线既有上下文回归。

### Task 3: 客户端展示与三语
- [x] 增加utils/failureInfo.ts及类型/解析测试，扩展已有消息类型、SSE/WS/历史读取和现有hooks。
- [x] 复用ChatErrorCard/ServiceBusyNotice展示固定提示和安全定位信息；保留原业务和上下文提示。
- [x] 同步三语api_errors源文件并通过已有生成脚本生成产物；不复制客户翻译全集。

### Task 4: 验证与交付
- [x] 后端来源/传播/上下文回归、Ruff与架构检查；记录实际运行结果。
- [x] 按e2e-test流程准备验收清单及八列用例；无环境则如实记录未执行。
- [x] 独立代码审查，修复实质问题；只提交本迁移，不推送或部署。

## 实际验证与边界

- 任务1：公共/真实依赖方法边界51项通过；测试最初缺少模块而失败，迁移后通过。
- 任务2：任务来源/原mapper/原resilience56项通过；日常辅助/部分检索/历史/统一提交6项通过。
- 主线上下文转换与实际模型方法兼容2项通过。共115项定向检查。
- 完整主线上下文测试入口因隔离工作区缺少未跟踪config.yaml而未收集成功；以实际生产方法和转换器的隔离测试验证此次装饰器改动，不复制客户配置。
- 前端测试、lint/typecheck、构建及真实环境E2E未运行，测试清单已准备；不将该工作标为环境验收通过。
- 独立审查5项实质发现已处理，见code-review.md。
- 适配决定：只迁错误提示及其安全来源，不迁知识步骤名称等客户功能；不改主线恢复协议。
