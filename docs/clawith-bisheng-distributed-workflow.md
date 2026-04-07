# Clawith × Bisheng：分布式 Agent 协作架构

> 2026-03-27

## 核心想法

每个人有自己的 **Clawith**（个人 Agent），团队用 **Bisheng** 设计业务流程（Workflow）。

Workflow 里的每个节点可以分发给对应的人，由他们的 Clawith 来执行。

流程启动时，通过 Clawith 作为入口，驱动整个 Workflow 运转。

---

## 架构示意

```
         组织层（Bisheng）
┌────────────────────────────────────┐
│                                    │
│  [Node A] → [Node B] → [Node C]    │
│     ↓            ↓          ↓      │
└─────┼────────────┼──────────┼──────┘
      │            │          │
      ▼            ▼          ▼
  张三的           李四的      王五的
  Clawith         Clawith    Clawith
  (个人Agent)    (个人Agent)  (个人Agent)
```

---

## 节点类型对比：INPUT Node vs Clawith Node

**现有 Bisheng INPUT Node**
```
Workflow → 暂停等待 → 同一个发起人输入 → 继续
```
- 只能是发起人自己回答
- 没有 AI 辅助，只是一个表单

**Clawith Node（新想法）**
```
Workflow → 里面有clawith node - 分发node任务给指定人 → 那个人用自己的 AI Agent 完成 → 结果回传 → 继续
```

| 维度 | LLM/Code Node | INPUT Node | Clawith Node |
|---|---|---|---|
| 执行者 | 机器 | 发起人 | 指定人 + 其 AI |
| 速度 | 秒级 | 取决于人 | 取决于人 |
| 多人协作 | ✗ | ✗ | ✓ |
| 人工判断 | ✗ | 简单输入 | 深度处理 |
| AI 辅助执行者 | - | ✗ | ✓ |

---

## 三种方案对比

### 方案 A：纯 Clawith（Agent 自组织）

```
Agent A 收到任务 → 自己判断需要谁 → 调用 Agent B/C → 汇总结果
```

**优点：** 灵活，动态调整，不需要预定义流程，适合探索性任务

**缺点：**
- 不可控：不知道会调用谁，顺序不确定
- 无审计：事后难以追溯
- 无治理：无法限制跨部门调用权限
- 容易死循环：A 调 B，B 调 C，C 又调 A
- 无 SLA：不知道整个流程要多久

### 方案 B：Clawith Skill 预定义流程

```yaml
# 定义一个 skill：客户工单处理流程
skill: handle_customer_ticket
steps:
  1. 调用 LLM 分类工单
  2. if 技术问题 → call_agent("tech_support", task)
  3. if 账单问题 → call_agent("finance", task)
  4. 等待结果 → 汇总 → 回复客户
```

**优点：** 能跑，稳定，适合简单固定流程

**缺点：**
- 业务人员改不了流程 — 每次改都要找开发者改代码
- 看不到全局 — skill 里嵌套调用了 5 个 Agent，哪个卡住了看不到
- 状态管理是噩梦 — Agent A 调了 B 和 C，B 完成了 C 超时了怎么办？
- 规模不 scale — 3 个 Agent 协作用 skill 可以，15 个呢？

### 方案 C：Clawith + Bisheng Workflow

```
Bisheng 定义流程 → 节点分发到 Clawith → Agent 执行 → 结果回传 → 下一节点
```

**Bisheng 是「导演」**，定义谁做什么、顺序、条件
**Clawith 是「演员」**，执行具体任务

**优点：** 可预测、可审计、可治理、可复用、可优化

**缺点：** 需要预先设计流程，灵活性略低

### 场景对比

| 场景 | 适合方案 |
|---|---|
| 探索性任务（「帮我调研竞品」） | 纯 Clawith，Agent 自行决定 |
| 客户工单处理，保证每个环节走到 | Clawith + Bisheng Workflow |
| 跨部门审批、多人协作 | Clawith + Bisheng Workflow |

---

## Clawith Skill vs Bisheng Workflow

用 Skill 预定义协作路径能跑，但有天花板：

| 维度 | Clawith Skill | Bisheng Workflow |
|---|---|---|
| 流程定义 | 代码/prompt 写死 | 可视化拖拽 |
| 修改流程 | 改代码，重新部署 | UI 上拖线 |
| 谁能改 | 开发者 | 业务人员 |
| 并行分支 | 需要自己写 async | 原生支持 fan-out/fan-in |
| 条件路由 | if/else 硬编码 | 条件节点，可视化配置 |
| 执行状态 | 自己记日志 | 全局状态机，可暂停/恢复 |
| 错误处理 | try/catch | 节点级重试、超时、fallback |
| 监控 | 无 | 每个节点执行耗时、成功率 |
| 复用 | 复制粘贴 skill | 流程模板，一键复用 |

### 适用边界

```
任务复杂度
    │
高  │  ▓▓▓▓ Bisheng Workflow ▓▓▓▓  可视化、可管理、可审计
    │  ░░░░░ 灰色地带（两者都行）░░░
低  │  ████ Clawith Skill ████     简单、灵活、快速
    └──────────────────────────────
```

Skill 永远解决不了「业务人员改不了流程」这个问题。

---

## 分工边界

| | Clawith | Bisheng |
|---|---|---|
| 使用者 | 个人 | 团队/业务 |
| 设计者 | 个人配置 | 业务/研发设计 |
| 适合场景 | 轻量、灵活、快速 | 标准化、可管理、可审计 |
| 核心价值 | 个人效率 | 流程协作 |

---

## 核心价值

Bisheng 的真正价值不是「能跑流程」，而是「让非技术人员能设计和管理流程」。

Clawith 负责执行，Bisheng 负责编排 —— 两者互补，而非替代。

---

## 商业价值

- **降本**：减少跨部门沟通成本（会议、邮件往返）
- **提效**：异步并行处理，不阻塞流程
- **可审计**：每个环节有明确责任人和 AI 辅助记录
- **差异化**：市场上没有「个人 Agent + 组织 Workflow」的产品

**Slogan：** 从单机 Agent 到协作网络
