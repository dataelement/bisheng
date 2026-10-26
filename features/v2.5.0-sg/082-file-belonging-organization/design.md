# 文件所属组织设计

- Feature ID: `082-file-belonging-organization`
- Status: `implemented-local-verified`
- Created: `2026-10-23`

## 当前证据与约束

- `knowledge/domain/models/knowledge_file.py`：文件主表没有独立组织列，已有原始来源列不能承载可更新组织归属。
- `database/models/department.py`：`UserDepartment.is_primary` 区分主组织和附属组织；现有主组织查询直接取首条，不能单独证明唯一性。
- `database/models/group.py`：团队创建人使用 `Group.create_user`。
- `knowledge/domain/models/knowledge_space_scope.py`：科室、团队目标可以通过空间归属类型及 owner_id 区分。
- `knowledge_document_distribution_service.py`：发布激活迁移管理入口及物理版本，源库保留发布入口，必须在业务成功事务中同步组织。
- `open_endpoints/domain/services/filelib_sync_service.py`：统一 add_file 后还会将上传人改为责任人，必须覆盖最终登记身份，不能只在 add_file 读取当前登录账号。
- 保持 Service → Repository → ORM；租户过滤由现有机制注入；迁移兼容 MySQL/DM8，不新增依赖。

## 数据与权威来源

- 在 `knowledgefile` 增加 `belonging_organization_id`：可空整数，保存组织表 `department.id`，不存名称副本，不对文件夹赋值。
- 不新增文档主表列。单文档以其当前主版本文件的值作为继承锚点，已有发布/分享入口保存同一值。
- 人员组织通过仓储批量取得主组织关系，校验唯一且组织有效、属于当前租户；缺失、多主组织或引用异常返回空。不得沿用 `.first()` 掩盖异常。
- 字段用于业务元数据，不作为权限事实源，不接收客户端任意指定组织的新参数。

## 写入时机

1. 新文档首次登记：按最终上传人解析组织；网页导入等已有登记路径保持相同口径。Filelib 同步在责任人身份确定后赋值。
2. 个人库发布激活：使用激活前源库层级识别个人库，目标科室取绑定组织，目标团队查团队创建人及其唯一主组织。
3. 同一激活事务中锁定文档，通过仓储更新全部物理版本与发布/分享业务入口。原库保留入口也同步；不把投影清理墓碑当成业务文件。
4. 新版本、版本关联、发布及分享入口创建继承所属逻辑文档的现有值；更正替换不得丢失字段。发布到已有文档版本链时，受影响的最终逻辑文档按该次触发规则统一。
5. 其他发布方向、分享、移动、人员调组织、重解析、主版本切换不重算归属。旧文档空值不从当前人员组织悄悄回填。

拒绝、撤回、激活失败不提交组织更新；临时仓储故障仍按既有错误和重试处理，不将数据库故障伪装成无组织。无需新增 ES/Milvus 字段或历史索引刷新。

## 文件结构计划

以下路径相对 `src/backend/`；标明新增的名称为计划落点，实现前仍须读取调用方及就近规则。

| 路径 | 动作与职责 | Requirements |
|---|---|---|
| `bisheng/knowledge/domain/models/knowledge_file.py` | 新增可空字段及模型读出 | REQ-001, REQ-006 |
| `bisheng/core/database/alembic/versions/` | 新增版本化迁移，不回填历史值 | REQ-001, REQ-006 |
| `bisheng/knowledge/domain/services/knowledge_file_organization_service.py`（新增） | 组织解析、继承及发布触发编排 | REQ-002 至 REQ-005 |
| `bisheng/knowledge/domain/repositories/interfaces/`、`implementations/` | 复用或扩展批量人员组织读取及文档内组织更新，不在服务写ORM | REQ-002 至 REQ-006 |
| `bisheng/knowledge/domain/services/knowledge_space_service.py`、`knowledge_service.py` | 文件登记及网页登记接入 | REQ-002 |
| `bisheng/open_endpoints/domain/services/filelib_sync_service.py` | 最终责任人组织赋值 | REQ-002 |
| `bisheng/knowledge/domain/services/knowledge_document_distribution_service.py` | 发布成功事务及入口继承 | REQ-003 至 REQ-005 |
| `bisheng/knowledge/domain/services/knowledge_version_service.py`、`knowledge_file_correction_update.py` | 版本关联、更正继承及一致性 | REQ-004, REQ-005 |
| `test/knowledge/`、`test/open_endpoints/` | 组织解析、事务、入口继承及实际上传身份回归 | REQ-001 至 REQ-006 |

## 迁移、兼容与回退

- 新列可空且没有自动组织默认值，旧数据保持空；不新增表，不修改原始来源列。
- 部署时先迁移再运行新后端和 worker，新增可选数据不要求前端同步修改。
- 代码回退优先保留新增列和值；旧代码不消费该列。仅回退代码期间新增文件不保证赋值，重新上线后不自动补齐。
- 删除新列会丢失已经记录的组织事实，属于另行确认的数据操作；本次不执行线上迁移或回退。
- 已登记本版本 release-contract；迁移脚本版本为 `f118_file_belonging_organization`，前驱为 `f117_portal_course_duration_seconds`。

## 实际落点补充

- 新增专用组织仓储接口及实现，统一提供同步/异步唯一主组织查询与文档内批量更新，发布调用不新增提交边界。
- 科室支持实际门户的用户所有者及历史部门所有者形式，通过 `department_knowledge_space` 绑定取得组织；用户所有者ID不是组织ID。绑定缺失、冲突或组织无效时不写入错误组织。
- Filelib 单元测试在原有外部依赖替身之外显式声明组织查询替身；真实组织解析由新 SQLite 仓储集成用例覆盖，接口用例验证最终责任人参数与写回值。

## 存量脚本扩展（2026-10-23）

- 新增 `src/backend/scripts/backfill_knowledge_file_organization.py`、脚本说明与隔离测试。用户仅授权编写，不在环境中执行回填。
- 唯一回填规则：有完整版本链时取当前主版本上传人的当前唯一有效主组织，整文档补空；无版本链的普通文件取自身上传人。不推导发布路径，不读取原始上传人作替代，不用目标科室或团队创建人。
- 默认只读输出JSONL计划；`--plan ... --apply` 只处理该计划，锁定文档与文件后重新计算并比较。已有非空值与推导值冲突整组跳过；缺失组织、损坏链路、跨租户、收藏引用、墓碑及在途分发不写入。
- 显式限定租户，可按知识库/文件选择种子；文档种子会扩展到同租户整份文档。维护窗口运行，脚本不停止服务。使用租户上下文及逐行复核，不新增业务查询中的手工租户条件。
- 输出文件独占创建且权限0600；写前落盘意图，提交前读回，提交后记录结果；回退只清理本次从NULL补入且未发生后续漂移的值，不覆盖已有归属。无提交确认的意图列为未知，不盲目回退。
- 门户实际科室/团队是 `owner_type=user`：科室取独立绑定表；团队取范围created_by（历史缺失时取知识库创建人），所有者不等同组织。此前部门/用户组结构仍兼容。

## 批量并发扩展（2026-10-26）

- 范围仅限该脚本、测试和说明，不修改业务服务、数据库Schema或环境数据。当前串行代码会在完整查询后才去重，且每个文件分别UPDATE、每条报告同步fsync。
- 预览分页批量读取种子与版本归属，查询前按逻辑文档去重；以有限窗口派发任务，CLI默认4并发、允许1～16。每个任务通过既有会话工厂取得独立会话，携带相同租户上下文并校验数据库身份，不共用AsyncSession。
- 执行/回退保留一文档一事务；同文档目标ID按 `--write-batch-size` 分批UPDATE（默认200，上限500），显式 `update_time=update_time` 保留各行时间，核对影响行数及完整读回。任一批失败回滚整个文档。
- 任务仍按意图持久化→更新→读回及prepared持久化→提交→committed持久化顺序执行。异步日志写入由单锁串行化，文件写和fsync转到线程，调用方必须等待完成；预览每个完成窗口可合并一次fsync，写入屏障不弱化。
- 异常停止下一窗口派发；已经派发的任务等到提交/回滚和日志结束，检查全部异常再返回。中断同样等待当前窗口，不能把已提交的并发文档误报为回滚。
- 不改变JSONL版本或候选快照结构，可使用旧预览计划和写入日志。实际MySQL/DM8连接池和锁竞争仍需维护窗口验证；并发不会保证固定倍数提速。

## 可选计划扩展（2026-10-26）

- 用户要求不必使用 `--plan`。新增直接扫描方式：`--tenant-id N --apply --output ...`；不加 `--apply` 仍生成只读预览。保存计划方式保持可选，与直接方式共用候选、写入及回退逻辑。
- `scan()` 共用分页、范围校验、预先去重及有界独立会话；`preview()` 保留为强制只读兼容入口。直接模式解析候选后结束只读事务，再通过原 `apply_item()` 锁定重算并比较快照，避免扫描快照代替写前复核。
- 直接写入报告头使用既有V1 `mode=apply`，逐文档持久化intent/prepared/committed；与保存计划写入日志使用相同 `--rollback` 入口。只补空值、组织冲突跳过、时间保留、失败排空及未知提交保护不变。
- 此扩展取代早期“必须先生成计划”的CLI限制，不授权执行环境扫描、回填或迁移。字段迁移及维护窗口要求不变。

## 测试策略与追踪

| Evidence | Acceptance | 主要验证层及充分结果 |
|---|---|---|
| V-001 | AC-01, AC-06 | 迁移/模型：升级前旧行保持空、新字段读写、可选字段兼容；MySQL/DM8方言检查，真实DM8无环境则保留人工验收 |
| V-002 | AC-02, AC-06 | 真实仓储集成，参数化单主组织、无主组织、多主组织、失效或跨租户组织；页面上传与接口责任人结果正确 |
| V-003 | AC-03, AC-04, AC-05, AC-06 | 发布/版本集成：科室与团队、旧版本与入口同步、审批未完成和事务回滚、重复执行、继承及非触发路径不重算 |

迁移、事务与多入口共享状态按 V3 风险验证；复用现有真实ORM测试夹具，选择业务结果测试，不为每个字段单独堆叠用例。真实生产中间件与线上验收需分别报告，不用本地通过替代部署证据。
