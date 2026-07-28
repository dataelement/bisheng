# Release Contract — v3.0.0-beta1

> 本文件是 v3.0.0-beta1 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。
>
> 本版本首批登记的四个 Feature 均来自 PRD《3.0.0-beta1 需求文档》§四 功能体验优化
> （https://dataelem.feishu.cn/wiki/Ifj6wOgSmiyClfkMQySc7ZmvnNb），均为 Small feature 轨道。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| —（无新增） | F043-report-node-optimization | 在既有工作流报告节点模板链路上：①新增「手动触发保存」端点（转发 forcesave 指令到 OnlyOffice，落盘仍走既有 callback）；②变量占位符格式扩展为 `{{显示名\|nodeId.field}}`（向后兼容旧 `{{nodeId.field}}`，解析仍以 nodeId 为键）。**范围仅工作流报告节点**——旧「技能」体系独立报告页入口已关闭、变量机制独立（`{id}_{name}`），不纳入、不做兼容投入，待随技能残留代码一并清理；不引入新领域对象/表/DAO |
| —（无新增） | F044-model-status-manual-verify | 在既有 `LLMModel` 上新增 `status_update_time` 字段（Alembic）与「手动验证单模型」对外 API；复用既有按类型探活逻辑，状态写入仍经由既有 LLM service/DAO；不引入新领域对象 |
| —（无新增） | F045-chat-image-preview | 纯 client 前端渲染改造（日常/任务/工作流会话消息附件的图片分流 + 失效占位）；不触碰后端与存储 |
| —（无新增） | F046-channel-source-link-failure-ux | 纯 client 前端改造（添加公众号信息源的失败状态机、弹窗文案、引导浮层）；不改后端识别接口与错误码 |
| —（无新增） | F047-linsight-citation-traceability | 在既有 citation 子系统上新增**灵思任务模式**的溯源接线：`search_knowledge_base` 保留 chunk 元数据并接入 registry、包装 `web_search` 登记来源、完成时经既有 `save_message_citations` 向 `message_citation` 写入（`message_id`=任务轮 `ChatMessage.id`，`chat_id`=会话 id）。只读 / 调用现有 `KnowledgeFile` / `MessageCitation` 与 citation 服务；不拥有 `message_citation` schema、不改日常模式、不改灵思检索的文件级可见性 |

**规则**：
- 非 Owner Feature 的 AC 中不得出现其他对象的"创建/修改/删除"行为，只能"读取"或"调用" Owner 的 Service
- 新增领域对象时必须先更新本表

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-8 | 报告模板变量解析必须以**节点 ID** 为取数键；显示名仅作展示，不参与执行期取数。解析端必须永久兼容存量旧格式 `{{nodeId.field}}`（不迁移、不改写存量模板） | 工作流报告模板 / 独立报告模板 | F043 |

（INV-1~7 为 v2.6.0 存量不变量，继续有效，见 `features/v2.6.0/release-contract.md`。）

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F043-report-node-optimization | 无 | 前后端小改；不依赖本版本其他 Feature |
| F044-model-status-manual-verify | 无 | 前后端小改 + 1 个 Alembic 字段；不依赖本版本其他 Feature |
| F045-chat-image-preview | 无 | 纯前端；不依赖本版本其他 Feature |
| F046-channel-source-link-failure-ux | 无 | 纯前端；不依赖本版本其他 Feature |
| F047-linsight-citation-traceability | F035, F029（均为 v2.6.0 存量，已上线） | 接线型；把灵思任务模式产物接入既有 citation 溯源子系统（Phase 1 应用内预览行内角标，覆盖 KB 文档 + Web 网页；Phase 2 下载 Word/PDF 烘焙可见 `[1]` 编号 + 参考资料，延后）；不新增领域对象/表/对外 API/错误码/不变量/`MessageEventType` 枚举；无 alembic 迁移（复用 `message_citation`）；不写 `LinsightExecuteTask.history`（避 DM8 写放大）；角标解析复用 F029 `view_file` 过滤守 **INV-7**（见 v2.6.0 契约） |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| —（本版本 Feature 均不新增错误码） | — | F043 复用工作流/报告既有错误响应；F044 验证失败是业务结果（状态=异常）而非错误响应，不占码；F045/F046 纯前端；F047 复用 citation 子系统与 F029 权限过滤的既有错误响应 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-07-24 | 初始化 v3.0.0-beta1 契约；登记 F043~F046 四个功能体验优化 Feature（均无新增领域对象；新增 INV-8 报告模板变量以节点 ID 为键 + 永久兼容旧格式；均不新增错误码） | F043 / F044 / F045 / F046 |
| 2026-07-27 | 登记 F047 灵思任务模式引用溯源（**由 v2.6.0 F040 迁入并改编**——v2.6.0 的 F040 编号已被 `040-rebac-read-path-perf-rollout` 占用，spec/design 内容未变，仅改版本与编号）：表 1 标"无新增领域对象"（在既有 citation 子系统上加灵思接线，写入仍经 `save_message_citations`）、表 3 记跨版本依赖 F035/F029（v2.6.0 存量已上线）；复用 F029 `view_file` 过滤守 v2.6.0 **INV-7**；无新增错误码/对外 API/不变量/alembic 迁移；分期 Phase 1 应用内预览行内角标（KB+Web）/ Phase 2 下载件烘焙可见引用（延后） | F047 |
