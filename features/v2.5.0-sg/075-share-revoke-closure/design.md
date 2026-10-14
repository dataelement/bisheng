# 设计

## 已检索的链路

1. `FileShareDialog.tsx` → `/approval/shougang/file-share/revoke` → `KnowledgeSpaceService.revoke_document_share()`。
2. `KnowledgeDocumentDistributionService.remove_share_entry()` 锁定文档/入口，提交 `deleting`，尝试撤销权限，调度后台任务。
3. `process_document_projection()` 使用 `DocumentProjectionBatchService`；批量仓储通过文档及入口锁检查同文档已有租约。
4. `_finalize_deleting_entry()` 在领取状态复核成功后只删旧入口权限及行，并产生全文删除意图。
5. `ApprovalCenterService` 与 `ApprovalQueryRepository` 按审批实例/任务读取历史，不依赖分享引用存在；现有审批操作日志支持使用调用方 session 写入。

## 关键决策

- 覆盖业务目标，不复用旧引用 ID：旧引用保持 `deleting` 供清理，新审批产生新的 `share` 引用；不同 ID 防止旧权限和全文删除任务误删新授权。
- 不修改通用占位查询默认规则。分享专用校验在锁定状态下排除 `share + deleting`，并复核所有占位记录，避免先查到旧记录时漏掉新有效记录。
- 新申请仍走原分享审批。审批回调再次检查有效目标占位与租户/文档/目标身份，避免提交和审批间状态变化产生重复有效入口。
- 复用既有文档级投影互斥：旧任务已领取时，新投影等待其完成再读取当前入口集合；旧任务未领取时，其清理基于新分享仍有效的集合生成归属。不得单纯放宽重复校验而跳过并发验证。
- 审批历史由 approval 模块负责。通过新的分享历史领域服务与现有仓储写 `share_revoked` 操作日志，关联精确的原实例/旧入口；不把已完成审批改成“审批中撤销”。
- 撤回历史与 `deleting` 事务提交保持一致，包括接收方删除分享引用路径。租户、场景、文档、目标身份不匹配时失败关闭；历史不依赖最终被删除的文件行。
- 原审批回调执行前读取持久撤回事实。撤回已发生时直接返回业务终态，不再次创建引用或触发分享积分旁路。
- 查询端批量生成 `share_revoked` 兼容字段；列表、任务详情和申请详情统一显示“已撤回”，保留原审批结果与操作时间线。
- 已有不存在的引用不能直接推断为撤回。历史补齐/恢复丢失数据不在本次范围。
- 旧清理耗尽时显示失败；仍允许独立新申请。继续复用显式、可审计的单条失败恢复工具，不无限自动重开预算。
- 重复申请查询以原审批的 share_revoked 日志排除业务终态，即使原执行状态尚未收敛为成功；非分享场景保持原查询。
- 分享弹窗打开且存在待清理记录时，每 10 秒串行刷新状态，关闭或切换资源时取消定时器并忽略旧响应；审批中心订阅现有跨标签页文件刷新事件。
- 从消息打开已处理任务时切换到已处理筛选，保留显式选中的任务，防止记录实际存在但列表视图隐藏。
- 复用现有中文“已撤回”语言键；新增 ShareRevokedBadge 子组件。knowledgeFileRefresh.ts 支持审批中心不限定空间订阅，既有限定空间订阅行为不变。

## File Structure Plan

以下均相对仓库根目录 `/Users/wenruli/code/project/bisheng/bisheng`：

| 文件 | 改动边界 |
|---|---|
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_file_repository.py` / `implementations/knowledge_file_repository_impl.py` | 分享专用目标占位读取，保留通用默认规则 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_document_distribution_service.py` | 新分享与旧引用共存、事务撤回事件、接收方删除路径；不碰物理版本删除 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 撤回操作人透传与清理状态响应；只改局部，不重构大型文件 |
| `src/backend/bisheng/approval/domain/services/knowledge_file_share_history_service.py`（新增） | 精确关联审批撤回日志，供撤回事务和旧回调终态检查复用 |
| `src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py` | 如需要，补同 session 的锁定/幂等事件读取，保持 MySQL/DM8 兼容 |
| `src/backend/bisheng/approval/domain/services/shougang_approval_service.py` / `shougang_approval_handler.py` | 仅排除已撤回旧分享占位；阻止已撤回审批重放 |
| `src/backend/bisheng/approval/domain/services/approval_center_service.py` | 批量撤回标记与详情历史，保持查询权限和任务状态 |
| `src/frontend/client/src/api/approval.ts` | 增量兼容字段 |
| `src/frontend/client/src/pages/knowledge/SpaceDetail/FileShareDialog.tsx` | 清理中/失败状态与刷新，保持再次分享可用 |
| `src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx`、必要子组件及语言文件 | 列表、详情“已撤回”和时间线；局部改动，不重写大文件 |
| `src/backend/test/approval/`、`src/backend/test/knowledge/`、对应前端测试 | 定向集成、失败/并发/拒绝路径和用户可见回归 |
| `features/v2.5.0-sg/release-contract.md` | 执行阶段补充 Owner 复用承诺，保留当前其他改动 |

共享索引 writer 与 batch 仓储只在复现证明现有互斥不足时做必要最小修复；不得无证据扩大为通用投影重构。

## 风险、发布与回退

- 风险对象：库间分享占位、撤回状态、异步清理及审批履历。变化：已撤回旧入口不再阻止新的审批；有效入口与访问授权规则保持。
- 撤回标记保存在现有表，无新增表、字段或历史迁移。本地代码和文档可用 Git diff 回退；不删除既有审批历史。
- 前后端一起部署；上线前验证真实 ES/Milvus/OpenFGA/队列，不把 SQLite/fake 验证当线上验证。
- 回退后新增历史日志仍保留；旧代码可能重新阻止仍在清理的旧入口，不自动恢复被撤回授权。

## 验证策略

V3，按业务结果组织验证：再次分享/有效占位拒绝；旧任务与新分享交错；历史在最终删除后仍存且旧回调不可复活；权限拒绝与事务失败。前端主要验证标记、状态和刷新，不重复测试后端状态机。复用同一代码状态下证据，最终只运行受影响回归与构建。
