# 部门权限投影告警与排查

采集API和Celery Worker标准日志；运维脚本执行日志也应归档。F086本身输出日志，不创建外部告警规则或发送消息。

日志格式为固定前缀 `PERMISSION_PROJECTION_ALERT ` 后跟一行JSON。已有Loguru日志时间、level和trace前缀可以保留；采集器应提取固定前缀后的完整JSON。若采集器支持Loguru结构化extra，也可读取 `permission_projection_alert`。字段版本为 `schema_version=1`。

## 建议规则

以下是平台无关的规则定义，需要映射到客户现有日志告警平台的字段和语法。

| 规则 | 条件 | 时间与去重 | 建议级别 |
| --- | --- | --- | --- |
| 权限投影失败 | severity=ERROR，event为FAILED/MANUAL_REQUIRED/CONTEXT_REJECTED，details.mode不是DRY_RUN | 最近1分钟出现即触发；按tenant_id+scope_key+reason_code去重5分钟 | 严重 |
| 祖先导致用户鉴权拒绝 | event=CONTEXT_REJECTED，reason_code为ANCESTOR_INACTIVE或DEPARTMENT_FAILED_CLOSED | 按tenant_id+details.ancestor_id+reason_code合并；一个祖先影响多个部门时只开一个根因告警 | 严重 |
| 投影长时间处理中 | event=CONTEXT_REJECTED，reason_code=DEPARTMENT_PROJECTING | 同一祖先连续5分钟有事件再触发；短暂正常投影为WARNING | 警告 |
| 对账发现不一致 | event=INCONSISTENT或MANUAL_REQUIRED，details.mode=DRY_RUN | 每次人工扫描汇总异常scope；不要与线上请求故障重复呼叫 | 运维检查 |
| 数据库/基础设施问题 | reason_code为DATABASE_TIMEOUT、INFRASTRUCTURE_TIMEOUT、EXECUTION_LEASE_LOST、CONSISTENCY_MARKER_NOT_READY | 1分钟内出现即触发，按tenant_id+reason_code合并 | 严重 |
| 修复完成 | event=RECOVERED | 同tenant_id+scope_key核对operation_id/recovery_id，结合后续普通用户验证解除告警 | 信息 |

`alert_key`是tenant/scope/op/reason的稳定摘要，适合相同错误去重。恢复成功使用不同原因码，因此**不能要求RECOVERED与FAILED的alert_key相同**。多个来源operation可能被一项人工维护取代，需同时使用recovery_id、部门与共享审计关联。

INFO事件PROJECTED只表示新业务操作的原投影已提交，不能当作归档关联清理完成或解除故障告警。

日志只在发生投影/扫描/请求时出现；无日志不证明健康。周期任务默认5分钟，但每轮有尝试/时长上限，大量历史异常不能保证一轮扫完。鉴权请求遇到坏祖先会立即记录其ID。应另行使用现有Worker/Beat存活监控确认任务在运行。

## 字段与示例

```json
{"schema_version":1,"severity":"ERROR","event":"CONTEXT_REJECTED","tenant_id":7,"scope_type":"department","scope_key":"11","operation_id":null,"reason_code":"DEPARTMENT_FAILED_CLOSED","alert_key":"示例摘要","details":{"ancestor_id":3,"ancestor_status":"active","ancestor_projection_state":"FAILED_CLOSED","phase":"request_permission_context"}}
```

这表示部门11的请求被祖先3的投影门禁拒绝；不意味着部门11自身的member元组缺失。请求路径不会为了告警额外查询operation，故operation_id可为null；用部门ID查同时间的执行日志和只读扫描。

| 字段 | 含义 |
| --- | --- |
| tenant_id、scope_type、scope_key | 故障作用域；跨租户祖先场景同时看ancestor_id |
| operation_id | 本次执行/来源绑定操作；人工维护同时以recovery_id关联prepared/finalized证据 |
| event、severity、reason_code | 稳定机器条件；不要从自然语言堆栈猜告警类别 |
| current/expected/target_version | 实际观测与原操作版本，变化说明不能重放旧意图 |
| store_id/model_id、current_store_id/current_model_id | 原pin与当前绑定，避免将模型变化误判为普通缺tuple |
| ancestor_id/status/projection_state | 具体断链祖先，不输出用户姓名/完整人员名单 |
| missing_count、extra_count及member计数 | 当前拥有域与目标差异；成员只给计数 |
| missing/extra_topology_sample | 最多8条父子关系样例；不是全量元组导出 |
| actual_path、expected_path | 已证明业务链的路径诊断；未完整证明时不能据此自动重挂 |
| contained | true为已确认保护，false为未关闭，null表示没有证明提交；不能把异常日志当SQL提交凭证 |

## 常见原因与动作

| reason_code | 解释与处理 |
| --- | --- |
| ANCESTOR_INACTIVE / ANCESTOR_MISSING | 源业务树/本地祖先失效；先人工dry-run，必要时精确IAM证明，不能只补member |
| ANCESTOR_NOT_CURRENT / DEPARTMENT_FAILED_CLOSED | 合法祖先投影未完成；查看该祖先operation，先恢复依赖 |
| DEPARTMENT_PROJECTING | 正在执行或执行遗留；持续存在时查最后阶段及Worker |
| BUSINESS_PATH_INVALID | path与真实parent图不符；当前人工计划判断，不按旧path猜父级 |
| OPERATION_MODEL_PIN_MISMATCH | 自动原意图pin已变；默认转人工当前模型对账 |
| ORIGINAL_TARGET_NO_LONGER_CURRENT | 当前业务目标已变；不能重放旧MOVE |
| DRIFT_OUTSIDE_ORIGINAL_EFFECTS | 发现原操作之外的成员/拓扑差异；自动拒绝扩大写入，人工预览完整当前目标 |
| COMMITTED_AFTER_STATE_MISSING | 台账声称COMMITTED但完整AFTER已缺失；不盲写，必要时保护性关门并转人工 |
| OTHER_ACTIVE_DEPARTMENT_OPERATION | 本部门有其他活跃来源，自动不接管；核对运行者与维护窗口 |
| BOUND_OPERATION_MISSING / BOUND_OPERATION_NOT_OWNED | 错绑/缺台账，需人工核实，不能凭旧ID补造 |
| MAINTENANCE_OPERATION_REQUIRES_CLI | 专用人工记录被普通恢复发现；用相同计划/窗口续跑专用CLI |
| ARCHIVE_OWNER_CLEANUP_REQUIRED | 已归档但成员/角色/空间等义务未完成；不能直接解封 |
| DATABASE_TIMEOUT | 达梦-608；对照同operation的PERMISSION_PROJECTION_RUN SQL耗时与慢SQL指纹，再看DBA执行计划/等待 |
| FGA_MIXED_COMMIT / FGA_TRANSPORT_ERROR | 部分/未知观测或传输错误；保持门禁，用真实读回核查，不能根据网络异常推断未写 |
| EXECUTION_LEASE_LOST | 当前进程失去执行权；查Redis与其他执行者，旧进程不得继续写 |
| SQL_COMMIT_NOT_VERIFIED | FGA可能已达目标，SQL未能证明提交；保留证据并按原计划核查续跑 |
| UNCLASSIFIED_PROJECTION_FAILURE | 查看exception_type及同一操作的常规异常日志；不输出原始异常到结构化告警以防凭据/SQL绑定泄露 |

## 排查顺序

1. 按tenant/scope和operation_id/recovery_id定位，先确认是否DRY_RUN或短暂PROJECTING。
2. 看失效祖先与版本/模型，再看拓扑缺失/多余样例；避免把业务父级失效一律解释成FGA缺成员。
3. 找最后阶段：before_saved只是文件；recovery_gate_committed是T1；fga_verified不代表SQL提交；sql_readback_verified/item_result才表示该项已核验收口。
4. 查 `PERMISSION_PROJECTION_RUN`、CLI summary 的SQL请求/耗时、慢SQL指纹、FGA请求及限速等待；慢SQL指纹不含绑定值，完整SQL须从受控DBA证据取，不在公共日志回显。
5. 默认dry-run重新核查。已持久prepared且窗口/计划未变按原计划续跑；发生业务/模型/第三态变化先保留证据再生成新计划。
6. 恢复后核对共享SQL记录，并用普通有权/无权用户做成对鉴权验收。仅凭RECOVERED不能声称所有知识空间权限均已业务验收。
