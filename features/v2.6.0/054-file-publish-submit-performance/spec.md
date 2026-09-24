# Feature: 发布申请提交性能优化（第一阶段）

**Feature ID**: `054-file-publish-submit-performance`  
**Status**: Implemented（真实 DM8 与生产耗时待环境验证）  
**Mode**: Bug Fix  
**Created**: 2026-07-14  
**Updated**: 2026-07-14  
**优先级**: P0  
**所属版本**: v2.6.0

## 1. 概述

首钢门户创建文件发布申请时，接口响应约 14 秒。代码调查确认同步路径包含：空关键词全量候选复验、逐候选 `view_file`、逐审批人事务写入和同步站内信。本 Feature 实现已确认的第一阶段优化，同时保留必须同步完成的登录、空间权限、目标合法性和审批事实创建。

详细需求、设计与任务分别见：

- [requirements.md](./requirements.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)

## 2. 目标

- 提交只按选中的目标 ID 做常数级校验，不扫描目标空间全部候选。
- 提交权限与发布搜索对齐，不再执行目标文件 `view_file`。
- 发布申请站内信改为独立通知 outbox + Celery，申请事实落库后即可返回。
- 首节点审批任务使用一次批量事务写入。
- 输出可定位剩余 OpenFGA/数据库耗时的分段性能日志。

## 3. 非目标

- 不异步化权限、目标校验、审批路由和审批人解析。
- 不修改 API 契约、Client UI、普通版本搜索或文件发布执行流程。
- 不在本阶段优化 OpenFGA owner/manager 查询。

## 4. 核心验收摘要

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-01 | 提交选择已有目标文档/文件 | 只定向读取目标，不调用空关键词全量搜索 |
| AC-02 | 提交权限复验 | 不调用候选文件 `view_file`，空间级权限保持 |
| AC-03 | 创建 pending 发布申请 | 实例和任务同步落库，通知 outbox 入队后立即返回 |
| AC-04 | Celery/消息发送失败 | outbox 保留状态并由 Beat 在上限内补偿 |
| AC-05 | 多审批人首节点 | 一次批量事务创建任务，响应 task_ids 顺序不变 |
| AC-06 | 成功或失败提交 | 输出结构化分段耗时，原异常不被吞掉 |

验收标准的稳定追踪 ID 和验证方法以 [requirements.md](./requirements.md) 为准。

## 5. 架构决策摘要

| ID | 决策 | 结论 |
|---|---|---|
| AD-01 | 目标校验时机 | 保持同步，但改为按 ID 定向查询 |
| AD-02 | 通知异步载体 | 新增独立 `ApprovalNotificationOutbox`，不复用业务执行 `ApprovalOutbox` |
| AD-03 | 交付语义 | Celery at-least-once；唯一 outbox、成功短路、锁和 Beat 补偿 |
| AD-04 | 异步范围 | 仅发布申请初始站内信；知识空间创建等其他消息不变 |
| AD-05 | 任务持久化 | Repository 单事务批量创建，保持输入顺序 |

## 6. 风险与发布约束

- 新代码依赖 F058 新表，必须先执行 migration 再上线应用。
- Worker 或 Beat 不可用只会延迟通知，不改变审批实例和任务事实。
- 消息发送后、outbox 标记成功前 Worker 崩溃时，at-least-once 模型仍可能产生重复提醒。
- 第一阶段不承诺消除全部 14 秒；性能日志用于判断是否需要第二阶段 OpenFGA 优化。

## 7. 当前状态

- `requirements.md`：已确认并实现。
- `design.md`：已按第一阶段方案落地。
- `tasks.md`：11 个任务全部完成。
- 自动化验证：专项测试、静态检查、编译和迁移 head 检查通过；详见 [verification.md](./verification.md)。
- 环境验证：真实 DM8 migration 与生产接口耗时待部署环境验证。
