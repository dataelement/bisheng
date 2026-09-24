# 复盘记录 Retrospective: 按文件分类自动移动到公共知识空间

## 阅读摘要
- F061 实现了多来源分类路由、版本链迁移和多存储补偿，但首次真实 apply 暴露了 MinIO 客户端入口未被直接测试的问题。
- REQ-007 已用最小修复替换为项目统一 `get_minio_storage_sync()`，并以 RED/GREEN 测试覆盖两个真实 helper。
- REQ-009 修复零宽字符名称匹配；线上8个空间已清理异常字符，真实 dry-run 已验证。
- REQ-010 将目标标签复制统一到既有来源快照，并增加双方标签 ID 诊断，避免复制与校验使用两套数据来源。

## 元信息 Metadata
- Feature ID: `061-classified-public-space-file-move`
- Status: `completed`
- Related requirements: `features/v2.6.0/061-classified-public-space-file-move/requirements.md`
- Related design: `features/v2.6.0/061-classified-public-space-file-move/design.md`
- Related tasks: `features/v2.6.0/061-classified-public-space-file-move/tasks.md`
- Related verification: `features/v2.6.0/061-classified-public-space-file-move/verification.md`
- Created: `2026-07-17`
- Updated: `2026-07-17`

## 已完成范围 Completed Scope
- 修复来源工件存在性检查和预览对象复制的 MinIO 客户端获取方式。
- 新增直接 helper 测试，覆盖对象存在、不存在、空对象名和复制参数。
- 修复版本链跳过报告的分类/detail 丢失，并避免一致分类重复解析目标。
- 运行56个定向回归及全部静态质量门，包含零宽字符 RED/GREEN 回归。
- 事务性清理线上8个目标空间名称，并执行17个来源空间 dry-run。
- 输出21条批内冲突及唯一占用单元关联清单。
- 修复真实 apply 暴露的目标标签快照不一致，完整定向回归更新为58个测试。

## 范围变化 Scope Changes
| Change | Spec Updated? | Reason | Impact |
|---|---|---|---|
| 新增 REQ-007 与 T011-T015 | yes | 首次真实 apply 暴露不存在的客户端方法调用 | 仅修正脚本 MinIO 入口和回归测试，无业务规则变化 |
| 新增 REQ-008 与 T016-T019 | yes | 真实 skipped JSON 无法定位目标未解析原因 | 补充已有信息并删除重复计算，原因码保持兼容 |
| 新增 REQ-009 与 T020-T026 | yes | 公共空间名称末尾 `U+200B` 导致2110条目标未命中 | 代码忽略已知零宽字符，线上数据限定 ID 事务清理 |
| 新增 REQ-010 与 T027-T030 | yes | 真实 apply 在目标标签校验阶段失败 | 标签复制改用缓存快照精确替换；不改审批模块或标签 DAO |

## 实现经验 Implementation Learnings
- 对外部存储 helper 只测试上层 orchestration 不足以发现错误 API；关键边界必须至少有一个直接调用真实 helper、仅 fake 最末端客户端的测试。
- `copy_file` 测试通过 mock `_snapshot_source` 绕过了 MinIO 快照路径，虽适合隔离 owner 行为，但不能作为工件完整性的唯一证据。
- 真实 apply 日志中的 `target_file_id=-` 与调用顺序共同证明失败发生在目标创建前，可避免不必要的数据补偿操作。
- 业务跳过不仅要记录“为何跳过”，还要保留做出决策时已经解析出的分类上下文；否则报告无法用于运维修复配置。
- 界面显示相同不代表字符串相同；按名称路由的关键边界应显式覆盖零宽格式字符。
- 数据库排序规则会将带/不带 `U+200B` 的值视为等价，数据修复预检不能只依赖 SQL 等值，还要在 Python 中核对精确 code point。
- 对同一完整性条件不能在复制时重新查询、校验时再比较旧快照；快照既然定义了成功标准，就必须同时作为写入数据源。

## 设计偏移 Design Drift
| Drift | Source | Impact | Follow-Up |
|---|---|---|---|
| 初版错误假设 `KnowledgeUtils` 提供 MinIO client accessor | REQ-005 / BishengMoveOperations | 首次真实 apply 的 3 个候选文件在来源快照阶段失败 | 已由 REQ-007 修复并回归覆盖 |
| 名称规范化仅使用 `.strip()` | REQ-002 / TargetRouteIndex | 除培训资源外的8个类别全部无法命中 | 已由 REQ-009 修复；线上数据同步清理 |
| 标签复制重新查询来源并增量添加，校验却比较原始快照 | REQ-005 / BishengMoveOperations | 89515、89516复制完成后校验失败并补偿目标 | 已由 REQ-010 收敛为快照精确替换 |

## 验证缺口 Verification Gaps
- 修复后尚未在真实业务环境重新执行 dry-run/apply。
- 真实 dry-run 已执行；本轮未授权 `--apply`，因此未移动2089个候选文件。
- 代码加固未直接热修复运行中 Pod，需通过正常发布进入后续容器镜像。
- REQ-010 本地修复未部署，89515、89516需在发布后小批量重跑并核对目标标签。
- 真实 MinIO、Milvus、Elasticsearch、OpenFGA 和版本图端到端一致性继续保持 `MANUAL_VERIFY_REQUIRED`。

## 后续工作 Follow-Up Work
| Item | Type | In Current Scope | Owner / Next Step |
|---|---|---|---|
| 部署修复并重新 dry-run，审核后重跑 apply | verification | no | 运维人员；重点核对 93073、93074、93076 |
| 使用更新脚本重新 dry-run 并核对 document 6307 的分类和底层 route reason | verification | no | 运维人员部署后执行 |
| 通过正常发布流程部署 REQ-009 代码加固 | deployment | no | 维护者构建新镜像；不建议直接覆盖 Pod 文件 |
| 审核 dry-run 后决定是否授权 `--apply` | operation | no | 运维人员；候选2089个，另74个保持跳过 |
| 部署 REQ-010 后先重跑89515、89516并核对标签3298 | verification | no | 运维人员；通过后再恢复批量 apply |

## 复盘质量门 Retrospective Quality Gate
- [x] Scope changes were reflected in requirements/design/tasks before implementation continued.
- [x] Follow-up work is not marked as completed scope.
- [x] Verification gaps are explicit.
- [x] Lessons that affect future implementation are recorded.
