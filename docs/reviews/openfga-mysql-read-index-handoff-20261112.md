# OpenFGA MySQL分页读取索引与镜像升级交接

目标：在OpenFGA项目为按Store分页读取关系增加组合索引，构建并发布固定版本镜像。本文供另一个agent直接实施；不修改SQL文件登记与ES/Milvus数据不一致，不修改授权模型、tuple数据或BiSheng业务库schema。

## 已核实基线

- 项目：`/Users/zhangguoqing/works/openfga`，origin为`dataelement/bisheng-openfga`，本地HEAD/tag `v1.15.2-dm`（`eecdfd106d9466553c833cfb805c242228d4ab48`）。存在无关未跟踪文件及worktree，必须保留；先读该仓库AGENTS。
- 116运行镜像标签为`cr.dataelem.com/openfga/openfga:latest`，2026-11-12实际二进制为v1.14.2 / `c8a0e7b553ec322edfaa88948d57ba73bcad8883`；镜像ID `sha256:65c4db264a403bfd62387fed4fe48f1b7cdda694bdac5f493a8f3c5a6460b4ba`。
- 本地v1.14.2、v1.15.1-dm、v1.15.2-dm均核对过：`assets/migrations/mysql/001`至`007`未提供tuple(store,ulid)索引。116 `goose_db_version` 1–7均已执行；不是116漏执行既有migration。
- BiSheng SQL授权发布中的openfga_version=1.15.1来自硬编码常量，不能据此认定运行镜像版本。不要为补索引直接改此元数据冒充二进制升级。
- MySQL原索引：PRIMARY(store,object_type,object_id,relation,_user)，idx_tuple_ulid(ulid)，idx_user_lookup(store,_user,relation,object_type,object_id)。changelog的PRIMARY(store,ulid,object_type)属于另一张表，不提供tuple读取路径。

## 问题与现场验证

`pkg/storage/mysql/mysql.go:Datastore.read`在ReadPage时使用如下形态：

```sql
SELECT store, object_type, object_id, relation, _user,
       condition_name, condition_context, ulid, inserted_at
FROM tuple
WHERE store = :store_id AND ulid >= :continuation_ulid
ORDER BY ulid
LIMIT 101;
```

首屏没有ulid条件；后续还可能有object/user/relation过滤。116全Store约14万条时，旧计划选择PRIMARY并filesort，每100条API约768–805ms，多次全Store校验各耗十多分钟。不能仅看到独立ulid索引存在就认为该查询已优化。

2026-11-11 19:59已在116追加：

```sql
ALTER TABLE openfga.tuple
  ADD INDEX idx_bisheng_store_ulid_read (store, ulid),
  ALGORITHM=INPLACE, LOCK=NONE;
```

DDL12.745秒；之后EXPLAIN使用新索引、无filesort，原SQL3.36–3.83ms；API首次连接13.09ms，后续5.34–7.69ms。未删除任何原索引、未修改tuple或业务行。该索引目前已存在，升级migration必须兼容，不能再加重复等价索引。

## 实施要求

1. 在**OpenFGA自己的MySQL Goose迁移**新增未使用的版本（当前mysql最大007，实施时再核对），不改已发布001–007；不能放进BiSheng Alembic。DM目录另有008，不能误改或把DM SQL拿到MySQL执行。
2. 目标索引前导列严格为(store,ulid)。建议规范名idx_tuple_store_ulid；Up通过information_schema按真实列顺序检测等价索引，名称不作为唯一依据。116已有idx_bisheng_store_ulid_read应直接复用。
3. 如果规范名已存在但列顺序/列前缀不满足，应明确失败报告，不能只看名称跳过。已有其它等价索引则不新建、不重命名，不删除旧索引，不强加FORCE INDEX。
4. 使用仓库支持的条件SQL或Go迁移实现；MySQL不能直接依赖CREATE INDEX IF NOT EXISTS。新增使用INPLACE/LOCK=NONE，设置合理metadata lock等待上限，失败需非零退出且可重跑，不得因在线DDL失败退回阻塞式DDL而不报告。
5. Down只删除本migration明确创建的规范索引，不能删116事先手工建的或其它同列索引。可在新建索引COMMENT写入精确migration所有权标记，Down同时核对标记、名称及列形状；未持有标记则保留。不要仅凭goose“Up已执行”推断索引一定由该Up创建。
6. 构建固定新tag并保留digest，说明基于哪个代码版本、是否包含DM功能及兼容的存储schema；不要覆盖latest作为唯一交付。沿现有发布线与CI，不夹带无关dirty文件。
7. **先执行新镜像的migrate命令，再切run服务**；镜像更换本身不等于存储DDL执行。提供compose/Kubernetes两种部署的migrate及run示例，不在每个API请求尝试建索引。
8. 此项不要求更新116业务服务或替换知识库索引。用户会另行安排镜像实施；不要自行连接116修改数据/升级服务。

## 必须验证的场景

| 场景 | 要求 |
| --- | --- |
| 空MySQL新装 | 全部migration执行成功，恰好1个满足(store,ulid)的索引 |
| 原schema007升级 | 新索引创建，原PRIMARY、用户查询及ULID索引保留 |
| 116已有手工索引 | Up成功复用；无重复索引；Down不删除借用索引 |
| 异名等价索引 | 按列顺序正确复用，含前缀列索引不得冒充完整等价 |
| 同名错误列形状 | 明确拒绝或按明确策略处理，不能假成功 |
| 重跑及中断 | 无重复索引、schema版本不误记完成，恢复后可继续 |
| Down/再Up | 只移除本migration创建的索引，借用索引始终保留 |
| 多Store分页 | 首屏/后续页无缺失或重复，continuation token语义与现有版本一致 |
| 条件/对象/用户过滤 | 原ReadPage结果一致，不能因索引调整漏行或改顺序 |
| 实际MySQL执行计划 | 约14万/100万tuple、多Store及不同选择率下记录EXPLAIN和延迟；不只靠SQLite或SQL字符串断言 |
| 正常业务回归 | Check、BatchCheck、ListObjects和写入延迟没有显著恶化；记录新增索引的写入/空间成本 |

给出版本、DDL、EXPLAIN、前后P50/P95、分页正确性、索引磁盘成本及回退结果。现场5–8ms是116样本，不作为任意环境的强制时延承诺。

## 对read_tuples的评估

### 合理的使用范围

跨权限模型升级/离线审计必须了解实际Store原图，而不只是SQL能推导出的关系。否则旧namespace、未知残留或在新模型下重新生效的潜伏关系可能被漏掉。不能为了加快升级只读SQL已有资源并宣称完整图已核验。

旧F048已经有同类场景：BiSheng的permission/migration/f048_runtime_source.py:_load_tuples调用无过滤read_tuples；f048_runtime_verification.py:acollect同样读取完整Store。模型发布工具还扫描department.subtree_member旧关系。不是F118首次发明这种查询。

正常在线鉴权使用Check/BatchCheck、ListObjects或明确对象/主体的Read，不应每个业务请求全Store读取。本项加索引不意味着允许业务改成全量扫描。

### 当前客户端的成本与建议

- BiSheng `core/openfga/client.py:iter_tuples`每页100条、按continuation token顺序读取；分页是正确方向。
- `read_tuples`只是把iter_tuples全部收集成list；不带过滤时，HTTP分页仍然**不会限制最终内存占用**。
- F118 publisher使用iter_tuples，但ascan把全图存成set做前后比较，仍是O(N)内存。这在14万条尚可，百万级应测RSS；仅将函数名改成iter不能声称内存问题已解决。
- 本次OpenFGA agent范围是存储索引及镜像，不要同时改BiSheng冻结协议/续跑账本。BiSheng侧后续优先把只需单对象的read_tuples调用改为带过滤；全Store流式审计避免不必要list副本，并评估分区/有界外排差异比较。
- 同一稳定停服阶段可复用已经核验的事实，但不能用旧缓存跨越关系写入阶段。初始原图、写入结果不确定的恢复及最终图核验不能因“索引加好了”或“抽检过”被删掉。减少重复扫描须证明与既有恢复合同等价，不借性能修改改变权限结果。
- 不增加Celery队列消费检查或服务探测；停服由业务/运维保证，与FGA图完整性校验是不同职责。

结论：**离线全Store读取有必要；正常业务全Store读取应收敛；当前主要瓶颈先由组合索引解决，list聚合及重复扫描作为BiSheng侧独立优化，不在这次镜像索引补丁中混改。**

## 证据与源码

- 本地OpenFGA源码：`assets/migrations/mysql/{001_initialize_schema,007_collate_object_id}.sql`，`pkg/storage/mysql/mysql.go`。
- 116原始性能证据：`/opt/server/bisheng-test/upgrade-records/f118-20261111/fga-read-index/`及logs/fga-*。
- 本地tag核查：`/Users/zhangguoqing/.codex/visualizations/2026/11/11/01a1c875-f593-7ca0-9f54-488dcabc4550/migration-review-20261112/openfga-tag-evidence.json`。
- 业务侧边界与已确认策略：[迁移反馈](f118-migration-feedback-and-flow-20261112.md)、[恢复及旧重试bug核查](f118-recovery-and-open-questions-20261112.md)。
