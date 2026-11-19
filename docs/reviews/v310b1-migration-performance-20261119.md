# 3.1.0-beta1 数据迁移性能评估

本文保留修复前评估与原始数据。后续 F118 修复、前后对比及恢复测试见[修复审查记录](v310b1-migration-performance-fix-20261119.md)；不代表原评估基线或已有版本标签已包含这些修复。

评估日期：2026-11-19。代码基线：`c3319b055033da7a2f4466cb2a0c9f6e94db63d3`。范围覆盖历史准备、F118 预检和正式转换、权限发布、引用回填、模型 Token/价格脚本及 Redis 索引回填。

**结论：存在确定的性能问题，大数据量环境应先优化高优先项，再在生产数据克隆上演练。** 已确认逐资源 SQL、正常数据下的二次方 CPU 开销、全表载入与无变更时的大范围锁定，以及存在清理对象时的乘积级集合构造。已检查的查询没有发现 SQL 笛卡尔积；问题主要出现在查询调用方式和 Python 数据处理层。

本次未改业务代码、未连接生产服务。合成复现使用实际迁移函数；仓储与权限发布测试使用本地 SQLite 和模拟的外部服务。计数可以证明代码的放大方式，耗时不能直接作为生产维护窗口。

## 一 结果与优先级

| 编号 | 优先级 | 触发条件 | 问题 | 影响 |
| --- | --- | --- | --- | --- |
| P01 | P1 | 正常权限资源也触发 | 历史准备逐资源查询业务对象是否存在 | `N` 条权限资源增加约 `N` 次 SQL 往返 |
| P02 | P1 | 正常空间成员、标签也触发 | 循环内重建全体知识根 ID 集合 | 成员路径为 `O(K×M)`，另有标签/标签关联乘积路径 |
| P03 | P1 | 即使没有业务修复也触发 | 13 张业务表全量载入、多份复制；apply 全表 `FOR UPDATE` 后才判断无变更 | 内存随全量行和 JSON 体积增长；无修复也有大范围加锁读取成本 |
| P04 | P1，条件触发 | 存在待清理对象 | 遍历每个 FGA tuple 时重复计算对象集合并集 | `O(U×D)` CPU 和临时集合分配 |
| P05 | P2 | 权限资源很多 | 正式权限转换按每个资源执行读取、校验和独立事务/checkpoint | 查询与提交次数很高；本地 401 根资源样本有 3,763 次 SELECT |
| P06 | P2 | 迁移分页多、对象存储有网络延迟 | 写分页后立即重复 GET；同一不可变权限计划重复读取/编译 | 增加 MinIO 请求、解码和编译成本 |
| P07 | P2 | Redis 总 key 数或 checkpoint 数很多 | 多轮全 DB SCAN，逐 key 串行命令 | 主要受总 key 数和网络 RTT 影响，`COUNT 500` 不等于批量处理 |

符号：`N` 为权限资源数量，`K` 为知识根数量，`M` 为空间成员数量，`U` 为 OpenFGA tuple 数量，`D` 为清理对象集合大小。P1 为大规模生产升级前优先处理，P2 为降低维护时长的后续优化；这些级别不表示已经发生数据错误。

## 二 高优先项的具体证据

### P01 历史准备存在正常路径的逐资源 SQL

`capture()` 已全量读取 `ResourcePermissionMode`，随后遍历每个 CURRENT mode 调用 `hard_missing()`；后者执行一条业务表主键查询。很多知识/文件事实此前已在 `business.read()` 的快照中，仍逐行往返数据库。工作流、应用等其他类型也逐个查询。

代码：[capture 资源循环](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/prepare_f118_history.py#L405)、[hard_missing](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/prepare_f118_history.py#L200)。

无外部 I/O 的复现执行真实 `capture()` 和 `hard_missing()`，对健康文件和权限提供合成快照，仅替换 Session 运输、pin 和冻结状态：

| 健康权限资源 | 全量 mode 查询 | 逐资源存在性查询 | 这两类 SQL 合计 |
| --- | --- | --- | --- |
| 100 | 1 | 100 | 101 |
| 1,000 | 1 | 1,000 | 1,001 |

这里统计的是这两类查询，不是脚本全部 SQL。若有 100 万个相应 mode，就有约 100 万次存在性往返；仅按每次 1 ms 假设计，累计约 16.7 分钟，尚未计服务端处理及其他阶段。

建议按资源类型分组，以主键 seek/小批 `IN` 获取存在集合，完整保留“跨租户或类型不符的实际行不等于物理不存在”的判定。对于已读取的完整快照可复用有证明的主键集合；未覆盖的类型仍分批查询，不能简单删掉存在性检查。

### P02 空间 ID 集合在成员循环内反复重建

`business.build()` 在每个空间成员上执行 `{str(k) for k in roots}`。标签关联和标签也有相同写法。即使所有数据均正确，没有任何待修复行，也会执行。

代码：[标签关联](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/f118_history_business.py#L230)、[标签及空间成员](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/f118_history_business.py#L261)。

执行真实 `build()`，只放入正常根和合法成员，输出的修改/删除/阻塞计划均为空：

| 根数量 K | 成员数量 M | 本机单次耗时 |
| --- | --- | --- |
| 1,000 | 1,000 | 0.0514 s |
| 2,000 | 2,000 | 0.1777 s |
| 4,000 | 4,000 | 0.7617 s |
| 8,000 | 8,000 | 3.0779 s |

另对根 ID 的 `str()` 调用计数：100 根×100 成员为 10,000 次；200 根×200 成员为 40,000 次。它证明了实际乘积开销，不只是计时噪声。生产上 1 万根×100 万成员，对应这一处约 100 亿次 ID 转换。

建议一次构建 `root_ids_as_text` 后复用，将这部分降为 `O(K+M)`。同文件还应一起索引以下条件路径，避免修复项多时再次退化：`file_references()` 每次扫描全部引用、`change()` 扫描已生成更新、标签 siblings 扫描全部 taglink，以及应用更新计划时逐项扫描整个目标表。

### P03 历史准备并未实现受控分页内存，空操作也锁全量数据

`business.read()` 对 13 张表执行 `select(model).order_by(id).all()`，包括文件、QA、文档版本、成员、工作流版本和引用表；读取的是完整 ORM 行，包含相关 JSON 正文。

随后 `build()` 复制原/后快照，`state_digest()` 再复制并整体 JSON 编码。内存峰值会同时包含原行、字典、快照、摘要输入字节等，不能用“单条 SELECT 数量少”判断便宜。

代码：[read 与 state_digest](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/f118_history_business.py#L49)、[快照复制](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/f118_history_business.py#L85)。

apply 在初次检查中又读全量快照；随后 `if repairs:` 判断的是带摘要等字段的非空计划字典，即使 `updates/deletes/physical` 全空也进入 `business.apply()`。后者先执行 `read(lock=True)`，再比较 `after_digest` 判断是否已经完成。因此没有业务修复时，也会先对这 13 张表的全部返回行请求 `FOR UPDATE`。

代码：[apply 初检](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/prepare_f118_history.py#L630)、[空计划仍调用 apply](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/prepare_f118_history.py#L703)、[先锁后判空](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/f118_history_business.py#L322)。

按当前升级文档的 preview→apply 顺序，无业务修复时也至少读取 3 遍完整业务快照：preview、apply 前检查、apply 内加锁读取。有修复时还会进行 after 校验；涉及物理孤儿备份的分支另有一次全量读取来提取文件列表。

建议先处理无变更计划的非必要加锁，保留只读完整性验证；再改成主键分页、受控字段投影和流式摘要。需要保留全局比对的事实可用磁盘暂存/索引表，不在内存中复制整个业务集。不能只给 `.all()` 外面套一个循环而仍累积全部结果。

### P04 FGA 流式读取中存在乘积级集合分配

`capture()` 虽然通过分页流读取 OpenFGA，但每个 tuple 两次执行 `owned | orphan_objects`。这会每次新建集合，成本与待清理对象数成正比。

代码：[tuple 循环](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/scripts/prepare_f118_history.py#L449)。

对源码原 AsyncFor 语法树执行合成流，1,000 个 tuple、500 个 owned 对象，实际执行 2,000 次集合并集、累计处理 1,000,000 个输入元素。若清理对象为空，此项成本很小；大量历史孤儿时会明显放大。

建议在循环前预计算一次并集；同时按 subject/object 建立相关 incoming 索引。后面的每个 purge 扫完整 `incoming/mode_links` 及删除树多轮排序，也要用邻接索引和队列处理，保持完整外部下游检查。

## 三 正式迁移与外部服务的主要成本

### P05 权限发布的逐资源事务和重复读取

`PermissionPublicationApplication._resources()` 每个资源调用一次 `_commit()`。`aapply_resource()` 先读 mode、Grant、VisibleSource、Assignee，再对发生变化的资源读取 after；每个资源另有 Run/checkpoint 读取和独立提交。before/after 相同的资源仍要逐个读取并推进 checkpoint。

代码：[逐资源提交](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/knowledge/application/unification_permissions.py#L325)、[单资源读写](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/permission/domain/repositories/f118_resource_write_repository.py#L115)。

运行仓库原有规模用例，401 根资源的正式 SQL 转换及权限发布产生：

| 指标 | 结果 |
| --- | --- |
| SELECT | 3,763 |
| DML（UPDATE/INSERT/DELETE 执行事件） | 1,712 |
| 权限发布阶段全 Store 扫描 | 3 次 |
| FGA 写批次 | 39 |
| tracemalloc 峰值 | 24,072,111 bytes |
| 本地执行耗时 | 18.042 s |

这是 SQLite、模拟 FGA/制品存储下的原有测试；**计时从 fixture 完成 M2 冻结之后开始，不包含历史准备、M2 扫描和 M4 引用回填**。它说明即使复杂度接近线性，查询系数和事务数仍然较高。SQLite 本机耗时不能按比例当作生产耗时。

建议把有限的一批资源及其完整 before/after 与 checkpoint 放进同一事务，保留原冻结计划、行锁顺序、失败回滚和未知提交结果处理。不要通过并发跑多个迁移进程绕过同 Run 的串行约束。

### 全 Store 扫描有用途，但当前默认流程成本较高

正常首次升级且不需额外 purge 时，文档的执行顺序至少包括：历史准备 preview 1 次、F118 新 Run preview 1 次、正式 M2 1 次、权限发布 3 次，共约 **6 遍全 Store**。历史 purge 的 apply、恢复重试和特殊保留证据可能增加读取。

权限发布的三遍分别核对原图、切换指针前 staged 图和最终 after 图。源码已经避免每 90 条写批次就重扫全 Store，规模用例也验证为 3 次。因此不能把三次全部归为无意义重复，也不能为了快而删除未知 tuple、父链和撤权检查。

客户端 Read 当前固定 `page_size=100` 且串行翻页。假设 100 万 tuple，每遍约 1 万页，6 遍约 6 万次分页请求。若每页平均 10 ms，单纯累计分页约 10 分钟；若平均 100 ms，则约 100 分钟。这是假设计算，尚未包含数据库处理、Python 解码、制品存取和写阶段。

代码：[分页实现](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/core/openfga/client.py#L401)、[阶段扫描](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/knowledge/application/unification_permissions.py#L430)。

优先核对目标 OpenFGA 实际分页 SQL 的 EXPLAIN 和 `(store, ulid)` 索引。仓库[历史现场记录](openfga-mysql-read-index-handoff-20261112.md)曾测到约 14 万 tuple 环境的分页从约 0.8 s 降到约 5–8 ms；那是特定环境和日期的记录，不证明本次生产实例已有该索引或有相同延迟。该索引属于 OpenFGA 自己的数据库迁移，不放入 BiSheng Alembic。分页大小调整需核对所发 OpenFGA 版本允许的上限及完整分页语义。

### P06 制品重复 GET 和计划重建

`UnificationArtifactStore.aput_canonical()` 已经回读验证，外层 `_Pages._put()` 随后又 `aload_canonical()`，即同一写入紧接着进行两次完整读取校验。

代码：[内层回读](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/knowledge/application/unification_artifacts.py#L121)、[外层再次读取](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/knowledge/application/unification_inventory.py#L146)。

权限发布中 `aplans(tenant)` 也会重新读取、解码并编译该租户完整计划，首次正常流程在预检 tuple plan、正式 tuple plan 和资源执行中分别调用。各阶段还会重新遍历已冻结制品图。

代码：[aplans](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/knowledge/application/unification_permissions.py#L161)。

可统一写入回读职责，并为同一 Run、同一 SHA256 的不可变分页提供有容量上限的复用。不能用不受控全量内存缓存替代当前重复读取，也不能缓存跨事务的实时 SQL/FGA 判定。

### P07 Redis 索引回填的扫描与串行往返

checkpoint 回填分别扫描 `write:*`、`data:*` 两个模式；客户端用量启用时再扫描一次 `*:events`。Redis 的 MATCH SCAN 仍遍历整个 DB。按文档 preview→apply→verify，客户端启用时合计约 9 遍 DB 遍历，关闭用量部分时为约 6 遍。

每个 checkpoint 的 preview 至少有 PTTL、SISMEMBER 两次串行调用；apply 还查询索引 TTL，单 key 提交一个 pipeline 再校验。用量流也逐个执行类型、消费组、积压及索引查询。代码没有把几百个 key 的这些步骤批量流水化。

代码：[checkpoint 回填](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/linsight/domain/services/checkpoint_index_backfill.py#L8)、[用量回填](https://github.com/dataelement/bisheng/blob/c3319b055033da7a2f4466cb2a0c9f6e94db63d3/src/backend/bisheng/dsh/infrastructure/usage_index_backfill.py#L10)。

建议单轮 SCAN 分流识别 key；按有界批次 pipeline 查询/写入，保留每个 key 的 TTL 和“全部 write 已入索引后才发布 checkpoint 完整标记”的顺序。重新校验仍保留，不能删旧事件或提前打完成标记。

## 四 已确认合理的检查与次要风险

- 正式 M2 的多数仓储已采用主键 seek 和 199/200 条小批读取；工作流父表、应用父表和授权来源父表均有明确关联条件。196 项实际仓储测试将 SQLAlchemy 笛卡尔积警告提升为错误后通过，没有发现这些路径的 SQL 笛卡尔积。该结果不等于所有生产 SQL 已有最优执行计划。
- M2 中模型共享集合与名称目录按租户准备一次，创建者与目标事实有去重缓存；不是每条引用都重新调用 OpenFGA Check。ContextVar/事务身份的 `_scope/check()` 多数是本地检查，不能按出现次数推算网络请求。
- M4 按来源回填后会再逐来源完整复核，以签发 Coverage。第二遍有校验意义；代价是每个来源仍有 SQL 会话、业务读取和引用核对。应量测保留版本数和引用槽位数，不只统计当前空间数量。
- SQL 分页并不保证整个流程内存有界：正式预检会积累文件目录、权限 namespace；权限发布会持有原 tuple 列表、集合及计划，峰值仍随单租户资源量和全 Store tuple 数增长。
- 模型补价的 JOIN 有明确 `server.id=model.server_id`，没有发现 SQL 笛卡尔积；但 apply 会先为打印计划全量读一遍模型，再为写入读一遍。Token 脚本会一次读取全部模型和服务，并逐模型 refresh。这些成本主要取决于模型数，通常应排在文件、成员和 tuple 路径之后；模型数很大时同样改成受控批次。

## 五 建议的处理顺序与生产演练

1. 先修复 P01、P02 和 P04：批量存在性读取、循环外固定集合、预建引用和下游索引。它们不需要放宽任何校验，也不改变升级业务范围。
2. 处理 P03：消除空操作的大范围加锁；设计分页/磁盘暂存和流式摘要，给实际内存峰值设上限。
3. 对 P05 做小批事务/checkpoint，消除 P06 的即时重复 GET，再批量化 Redis。分别验证中断恢复、未知提交、撤权、跨租户坏数据和零引用来源，不能只测正常成功速度。
4. 用目标生产数据库的完整克隆和最终镜像演练。至少记录：各表行数与大 JSON 总体积、每租户最大文件/成员数、全部保留业务版本数、引用槽位、权限 mode/Grant/Assignee/tuple 数、Redis 总 key/checkpoint/流数，以及各阶段 SELECT/DML/FGA/MinIO/Redis 请求数、峰值 RSS、P95 请求时延和锁等待。
5. 对全局孤儿 anti-join、租户主键分页、资源权限桶、OpenFGA Store 分页分别保存 EXPLAIN。索引以实际访问路径和现场已有索引为依据，不重复建索引，不直接修改现网数据验证。

在上述量级和执行计划缺失时，无法给出可信的停服分钟数。当前证据已足以排除“只是一次线性扫描，所以大库也不会有问题”的判断。

## 六 本次验证及复现材料

已执行 196 项仓储测试和 1 项原有权限发布规模测试，共 **197 passed**；另有无外部 I/O 的查询计数和 CPU 复现。未执行全部后端回归、MySQL/DM8 生产规模压测或真实服务升级。

- [合成复现脚本](evidence/v310b1-migration-performance-20261119/probe.py)：运行真实历史构建函数和健康资源循环；进程内拒绝服务网络连接，存在性 SQL 使用 fake Session 计数。
- [CPU 与 SQL 调用计数](evidence/v310b1-migration-performance-20261119/synthetic-results.json)
- [FGA 循环集合并集计数](evidence/v310b1-migration-performance-20261119/tuple-union-results.json)
- [正式权限发布规模计数](evidence/v310b1-migration-performance-20261119/publication-scale-results.json)

在本基线的隔离 checkout 中，配置一份仅供离线测试的 YAML，使用已安装项目依赖的 Python：

```bash
cd src/backend
export config=/absolute/path/to/offline-test.yaml
export PYTHONPATH=./
python -m pytest -q \
  test/knowledge_unification/test_migration_inventory_repository.py \
  test/knowledge_unification/test_migration_resource_repository.py \
  test/knowledge_unification/test_perm_migration_snapshot.py \
  -W 'error:.*cartesian product.*:sqlalchemy.exc.SAWarning' --tb=short
python -m pytest -q -s \
  test/knowledge_unification/test_permission_publication_scale.py \
  -k published_input0 --disable-warnings --tb=short
python ../../docs/reviews/evidence/v310b1-migration-performance-20261119/probe.py
```

最后一个探针替换的 module 函数只存在于该进程，需单独启动进程运行。合成耗时及内存只作本机样本，后续优化应在同数据和同环境比较调用次数与实际运行表现。
