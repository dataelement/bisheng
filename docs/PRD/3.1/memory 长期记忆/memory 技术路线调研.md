# BiSheng memory（长期记忆）技术路线调研

**取证日期**：2026-10-20（所有 star 数、commit 日期、版本号均为该日实测快照）
**调研范围**：11 个指定候选 + 9 个补充扫描项目 + 达梦 DM8 向量与全文能力 + BiSheng 侧接线面
**结论性质**：路线建议与分期属产品/工程取舍；每条淘汰理由均标注是技术限制（有一手出处）还是未核实

---

## 一、结论

**推荐路线 C：自研底座 + 借鉴算法。一期只做 client 日常模式的个人记忆。**

底座不是从零写，而是落在 BiSheng 已经在用的 **LangGraph `BaseStore`** 抽象上，自己实现一个 MySQL|DM8 + Milvus + ES 的后端。三条路的判定如下。

**路线 A（直接集成某个开源 memory 项目）—— 在"集成产品"这一层不成立，在"集成抽象"这一层成立。**

把 A 理解成"引入某个 memory 框架接管记忆层"，20 个候选逐个撞墙：要么强依赖 PostgreSQL + pgvector（Hindsight 公开宣称"No Storage Abstraction"、Letta、Cognee、memU、Memobase），要么必须部署图数据库（Graphiti 四个后端全是图库、Zep CE 同时要 pgvector 和 Neo4j），要么事实源是本地文件 / 本地 SQLite 因而多节点不成立（EverOS、BAI-LAB MemoryOS、ReMe、A-MEM、duoduo），要么 license 不可商用（OpenViking 是 AGPL-3.0、duoduo 的 FSL Competing Use 条款、memU 的手改非标准许可），要么引擎根本不开源（Supermemory）。唯一两个在"关系层可为 MySQL + 向量层可为 Milvus + 图库可不要 + Apache-2.0 + 纯 Python 可嵌入"上全中的是 **MemTensor MemOS** 和 **Memori**，但两者都有决定性折扣（见 §4）。

但把 A 理解成"用已有的持久化抽象 + 自己的后端"，它是可行的、而且摩擦最小。`BaseStore` 在源码层只有两个抽象方法 `batch` / `abatch`，其余 get/put/search/delete/list_namespaces 全部由这两个派生；namespace 是原生的 `tuple[str, ...]`，多租户隔离不需要额外机制；官方文档明确写了"后端不支持向量检索时，在传入 `query` 时抛 `NotImplementedError`"——**语义检索是可选的**。MySQL 后端有 MIT 许可的现成实现 `tjni/langgraph-checkpoint-mysql`（建表只用标准 `JSON` 列加一个 btree 索引，零扩展依赖），可直接取用或当模板。

**路线 B（纯自研不借鉴）—— 浪费。**

这些项目唯一确定可用的部分正是它们的机制设计，而机制与存储选型是可分离的：三元组落关系库、bi-temporal 事实失效、异步抽取、记忆写权限剥离、有效性反馈闭环，这些算法本身不受信创约束。§7 列出 20 条可直接照着实现的机制。

**路线 C 的决定性支撑：团队已经做过一次形状完全相同的事。**

`src/backend/bisheng/linsight/domain/services/checkpointer.py` 是 368 行手写的 `PlainRedisCheckpointer(BaseCheckpointSaver)`，文件头原话：替换 `langgraph-checkpoint-redis`，因为后者要求 Redis Stack / RediSearch，改用纯标准 Redis 命令实现。这与"自写一个 `BaseStore` 落在 MySQL|DM8 + Milvus 上"是同构决策——不是没人做过的事，是这个团队做过一次并且在生产跑着的事。

### 一期范围

**client 日常模式的个人记忆**：记住用户偏好、称呼、历史结论，跨会话延续。

选它作一期的理由是机制需求最窄且全部落在已验证可行的面上：只需"抽取偏好/称呼/结论 → 存事实 → 跨会话召回 → 冲突时覆盖旧事实"，不需要图遍历。向量召回直接用现有 Milvus，关键词用现有 ES，事实表落 MySQL|DM8，抽取挪到 Celery。

它要填的洞是现成的：`workstation_service.get_chat_history(chat_id, size=4, max_tokens=...)` 按 `chat_id` 取最近 4 条、超 token 上限就 `chat_history.pop(0)` 从头丢弃，作用域只到 chat_id，换会话归零。这是纯滑动窗口，没有抽取也没有持久事实。

---

## 二、这轮调研翻掉的三条结论

记录在此，避免下轮再被带偏。

**第一，Letta 的淘汰理由全错，但结论仍是淘汰。** 第一轮给出的三条淘汰性判断（硬依赖 pgvector、只能 Docker 独立服务、官方弱支持自托管）在对抗验证中全部 0-3 被推翻，补核后确认：license 是**干净的 Apache-2.0**（与官方文本逐词 diff 仅 APPENDIX 填了版权声明，无任何附加条款）、SQLite 档位确实在 ORM 层存在过、`SyncServer` 确实可进程内实例化。真正成立的淘汰理由是第一轮完全没查到的那条：**被集成的那个东西已经不存在了**——`letta-ai/letta` main 分支已无源码（只剩 12 个文档文件，`language` 字段为 `null`），README 写明当前源码在 `letta-ai/letta-code`、archive 分支是"the retired Letta V1 API server"。

**第二，Memori 从"首选参考实现"降级为"只能抄表结构"。** 第一轮核实的部分成立（原生支持 MySQL、知识图谱落普通 SQL 表、仓库内 pgvector 与 FULLTEXT 命中数均为 0）。但补核它的向量召回实现后发现：embedding 以 little-endian float32 打包存进 `blob` 列，**没有任何 SQL 侧距离计算、没有任何 ANN 索引**，检索时按"最近 + 最频繁"取回**最多 1000 条**到 Python，用一个**每次查询现建的 FAISS `IndexFlatIP`** 做精确内积。那个 1000 不是性能参数而是语义召回的硬天花板——超出的事实根本不参与相似度比较。

**第三，Cognee 的淘汰范围被收窄。** 第一轮"开启访问控制即强制 LanceDB + Kùzu"的说法出自已 404 的旧页；现行文档是"存储组合通过运行期兼容性检查时才自动启用 multi-user mode"，且单库模式下官方给了 `VECTOR_DB_PROVIDER=milvus` 示例。淘汰结论应限定在"关系层 + per-dataset 多租户"两点，不能外推成"Cognee 整体在信创不可行"。

---

## 三、横向对比表

淘汰理由一栏中，**技术限制**指有一手源码或官方文档出处；**未核实**指没查到，不等于不支持。

| 项目 | License | 关系层可 MySQL | 需图库 | 纯库可嵌入 | 多节点 | bi-temporal | 结论 |
|---|---|---|---|---|---|---|---|
| **MemTensor MemOS** | Apache-2.0 | ✅ 已实现 | ❌ 可选 | ✅ | ✅ | 未核实 | **最接近可集成**，但降级后机制失色、Python 核心重心外移、DM8 未支持 |
| **Memori** | Apache-2.0 | ✅ 一等驱动 | ❌ 不需要 | ✅ SDK | ⚠️ 进程内线程池 | ❌ | **表结构可抄，召回实现不可用**（1000 条硬截断 + 现建 FAISS） |
| Mem0 | Apache-2.0 | ❌ history 默认 SQLite | ❌ 可选 | ✅ | ⚠️ | ❌ | 组件级可借鉴（向量层能落 Milvus/ES），整体不接管 |
| Hindsight | MIT | ❌ | ❌ recursive CTE | ❌ 伪嵌入 | ✅ 最好 | ✅ 唯一 | 淘汰为底座（公开宣称不做存储抽象），**机制最值得借鉴** |
| Graphiti | Apache-2.0 | ❌ | ✅ 必需 | ✅ | ✅ | ✅ | 淘汰（`neo4j>=5.26` 是核心必装依赖），抄 bi-temporal 失效 |
| EverOS（原 EverMemOS） | Apache-2.0 | ❌ 写死 SQLite | ❌ | ❌ 起 HTTP 服务 | ❌ 单引擎锁 | ❌ | 只可借鉴机制（向量层可切 Milvus 是唯一亮点） |
| Letta | Apache-2.0 | ❌ 零痕迹 | ❌ | ❌ 已删除 | ❌ 同进程 asyncio | ❌ | 淘汰（Python 服务端已 retired），**机制取证到实现级** |
| Cognee | Apache-2.0 | ❌ 源码级硬失败 | ❌ 可选 | ✅ | ⚠️ | 未核实 | 淘汰（关系层 + per-dataset 多租户两点） |
| **OpenViking** | **AGPL-3.0** | ❌ 仅网关账号表 | ❌ | ❌ 必须起服务 | ⚠️ 需非默认配置 | 未核实 | **淘汰（license）**，但多租户模型最契合 BiSheng 网关形态 |
| **duoduo** | **FSL-1.1 + Competing Use** | ❌ 文件 + git | ❌ | ❌ Node CLI | ❌ git index.lock | ❌ | **淘汰（license + 技术栈 + 单用户）**，机制最值得借鉴 |
| memU | 手改非标准（SPDX NOASSERTION） | ❌ | ❌ | ✅ | ❌ 需本地可写目录 | ❌ | 淘汰（license 需法务单独出意见 + 抽取要外部 agent） |
| Zep CE | Apache-2.0 | ❌ | ✅ Neo4j | ❌ Go 服务 | — | ✅ | 淘汰（已停更并降级为 legacy 目录） |
| BAI-LAB MemoryOS | Apache-2.0 | ❌ 本地 JSON | ❌ | ✅ | ❌ | ❌ | 淘汰（本地文件 + `faiss-gpu` 不适配国产 CPU），抄分层晋升 |
| A-MEM | MIT | ❌ 内存 Chroma | ❌ | ✅ | ❌ 默认不落盘 | ❌ | 淘汰（研究原型，近十个月未更新），抄链接演化 |
| ReMe（原 MemoryScope） | Apache-2.0 | ❌ 本地文件 | ❌ | ✅ | ❌ | ❌ | 淘汰（只有本地文件后端），抄存储抽象接口 |
| Supermemory | MIT（引擎闭源） | 未核实 | — | ❌ 服务 | ❌ 单机绑定 | 未核实 | 淘汰（引擎不在公开仓库、TypeScript） |
| Memobase | Apache-2.0 | ❌ Postgres | ❌ | ❌ 服务 | ✅ | 未核实 | 淘汰（2026-01 起停滞） |
| LangMem | MIT | 存储无关 | ❌ | ✅ | 取决于 store | ❌ | 算法层可选择性借用；包本身近停滞，优先用 LangGraph store 原生 API |

**传染性 license 命中两个**：OpenViking（AGPL-3.0）与 duoduo（FSL-1.1 的 Competing Use，性质不同但后果更重）。其余候选均为 Apache-2.0 或 MIT，例外是 memU 的手改文本。

---

## 四、两个"最接近可集成"的候选

### 4.1 MemTensor MemOS（记忆张量，国内团队）

**这是本轮唯一在存储硬约束上全中的现成项目**，第一轮完全没覆盖。

- `MemTensor/MemOS`，11,952 star，**Apache-2.0**，PyPI 包名 `MemoryOS` 2.0.33（注意与 BAI-LAB 的 `memoryos-pro` **撞名**），最近推送 2026-10-17。[来源: github.com/MemTensor/MemOS]
- **`pymysql` 与 `sqlalchemy` 是核心必装依赖，不是 optional。** 真有 MySQL 实现：`src/memos/mem_user/mysql_user_manager.py` 与 `mysql_persistent_user_manager.py`，SQLAlchemy declarative 建 `users` / `cubes` / `user_cube_association` 三张表。[来源: 同仓库 pyproject.toml 与该文件]
- **向量库只注册两个后端：`qdrant` 与 `milvus`**（`vec_dbs/factory.py`）。[来源: 同仓库]
- **图数据库是可选的**：`neo4j` 在 `[tree-mem]` extra 里。`MemoryFactory` 注册的 9 个 backend 中，`general_text`（`GeneralTextMemory`）只用 `vec_db` + embedder + LLM，完全不碰图库。[来源: `src/memos/memories/factory.py`]
- 即 **MySQL + Milvus 跑 MemOS、无需 Postgres 无需 Neo4j，这个组合在代码层面成立**。
- 多租户：`user_id` + `cube_id` 二级，MySQL 里有 `UserRole` 枚举（ROOT/ADMIN/USER/GUEST）与 user↔cube 多对多关联，是全部候选里**唯一自带租户/权限模型**的。
- 另有一份值得单独记的参考实现：`graph_dbs/postgres.py` 文件头写着"Simple implementation using standard PostgreSQL with pgvector extension. **No Apache AGE or other graph extensions required.**"——用 JSONB + 向量列的普通表实现图式记忆。将来要在 MySQL/DM8 上做图式记忆，这是现成的"图落关系库"范本。

**三条必须讲清的折扣：**

1. **放弃图层就放弃了它的招牌机制。** README 强调记忆"structured as a graph, inspectable and editable by design"；LoCoMo 88.83 / LongMemEval 89.20 这些分数对应的是 TreeTextMemory 路径，不是 `general_text`。
2. **Python 核心的重心正在外移。** `src/memos` 最后一次提交是 2026-09-09，而 2026-09 以后的活跃提交全在 TypeScript 的 local plugin（`apps/memos-local-openclaw`、`packages/memos-core`）；GitHub 把仓库主语言判为 TypeScript。
3. **DM8 需要改一行并验证一片。** MySQL 连接串是硬编码的 `mysql+pymysql://` f-string，改成 DM8 dialect 是单点改动，但 SQLAlchemy 的 DDL 能否在 DM8 上原样建表**未核实**。

工程噪音两条：`fastapi[all]` 是核心依赖（作为库引入会拖进整套 web 栈）；`mem-scheduler` extra 需要 Redis + RabbitMQ（BiSheng 有 Redis，无 MQ）。

**结论**：不建议整体引入，但建议作为 **MySQL/Milvus 适配层与分层记忆设计的参考实现**，优先级高于其它候选。

### 4.2 Memori（已迁至 MemoriLabs）

**地址更新**：`GibsonAI/Memori` 现 301 重定向到 `MemoriLabs/Memori`，`pyproject.toml` 的 Repository URL 已改、author 为 "Memori Labs Team"、license 声明为标准 `Apache-2.0`、当前版本 `3.3.7`、`requires-python >=3.10`。后续查资料用新地址。

**成立的优点**（第一轮已核实，此处不重复取证）：七个驱动目录（mongodb / mysql / oceanbase / oracle / postgresql / sqlite / tidb），MySQL 有独立实现 + 独立单测 + 集成测试；知识图谱落普通 SQL 表——`memori_subject` / `memori_predicate` / `memori_object` 三张查找表存唯一值，`memori_knowledge_graph` 以 `subject_id/predicate_id/object_id` 连成三元组，全程不提任何图数据库；仓库内 pgvector 与 FULLTEXT 命中数均为 0，说明既不依赖 PG 专有扩展也不走 MySQL 专有全文语法。

**决定性折扣一：向量召回不可用于生产规模。**

| 环节 | 实现 |
|---|---|
| embedding 列类型 | 全方言裸二进制：MySQL/MariaDB/OceanBase/TiDB `blob`、PostgreSQL `BYTEA`、SQLite/Oracle `BLOB`。7 个 migration 文件里 `vector` 命中数为 **0** |
| 编码 | `struct.pack(f"<{len(embedding)}f", *embedding)` 小端 float32 紧凑数组 |
| 取数 SQL | 普通分页查询，**无任何距离表达式**：`SELECT id, content_embedding FROM memori_entity_fact WHERE entity_id=%s ORDER BY date_last_time DESC, num_times DESC, id DESC LIMIT %s` |
| 相似度计算 | **每次查询现建** `faiss.IndexFlatIP` + `add()`，精确暴力内积，无 IVF / HNSW / 量化，无持久化无跨请求复用 |
| 硬上限 | `MEMORI_RECALL_EMBEDDINGS_LIMIT` 默认 **1000**，官方定义为"Maximum number of embeddings to compare against" |

这个 1000 的后果需要说清：**超出的事实不是查得慢一点，而是根本不参与相似度比较。** 排序键是"最近被提到 + 被提到次数最多"，所以一条两年前说过一次的关键事实，在该用户事实数破千后就永久召不回来。截断是 per `entity_id` 的，而 `entity_id` 就是用户维度，所以阈值是"每用户 1000 条事实"。官方唯一相关建议在故障排查页："High memory usage — Reduce embeddings limit: `mem.config.recall_embeddings_limit = 500`. Use PostgreSQL for production."

量级推算（**非实测**）：默认 all-MiniLM-L6-v2 是 384 维 float32，单条 1536 字节，1000 条约 1.5 MB——即每次 recall 从 MySQL 拉回约 1.5 MB blob 并新建一次 FAISS 索引，按多 worker 形态要乘并发数。`MEMORI_USE_RUST_CORE` 不改变这个架构属性：它注册的 `fetch_embeddings` 回调仍然全量取回 blob，只是相似度计算搬到 Rust。

**决定性折扣二：方言抽象不在 SQLAlchemy 层。**

它的 SQLAlchemy adapter 的 `execute` 是 `self.conn.connection().exec_driver_sql(operation, binds)`——**原始字符串直通驱动**。所以 SQLAlchemy 的类型编译、paramstyle 适配、分页改写一概用不上，方言差异全靠人工在每个驱动里重写。各驱动规模：MySQL 806 + 308 行、PostgreSQL 814 + 303、SQLite 764 + 313、Oracle 774 + 402。schema 版本管理是自建的单行表 `memori_schema_version`，不是 Alembic。

新增 DM8 驱动需实现 **19 个方法** + 顶层 `Driver` 类 + 一份约 15 张表的 DDL dict，**约 1100–1200 行新代码，一人 2–4 周（含真机联调）**。好处是**不需要 fork**——`Registry._adapters` / `_drivers` 是类属性字典，外部包用装饰器即可注册。但有两个坑：`memori/storage/__init__.py` 的 driver 导入列表硬编码 7 个，自定义驱动必须由接入方显式 import 一次才会触发注册；走裸 dmPython 连接时 dbapi adapter 的 `get_dialect` 用硬编码映射表，没有 `dm` / `dmPython`，会抛 `ValueError`。

**BiSheng 接入的两个已实测拦路点：**

1. **直接传 SQLModel Session 会被拒。** SQLAlchemy adapter 的匹配条件是严格相等 `type(conn).__module__ == "sqlalchemy.orm.session"`，而 `sqlmodel.Session.__module__` 是 `'sqlmodel.orm.session'`；dbapi adapter 又会因 `hasattr(conn, "get_bind")` 且类名为 `Session` 主动排除它。结果两个 adapter 都不匹配，抛 `UnsupportedDatabaseError`。解法是传原生 `sqlalchemy.orm.Session`，或自己注册一个匹配 `sqlmodel.orm.session` 的 adapter。
2. **它绕过 ORM，BiSheng 的租户自动过滤不会生效。** 全程走 `exec_driver_sql` 原始 SQL，不经 SQLModel/SQLAlchemy 的 ORM 事件，因此基于 ContextVar 的租户自动注入（C3）对 `memori_*` 这 15 张表完全无效。Memori 自己的作用域只有 `entity_id` / `process_id`，没有租户维度——租户隔离需在 `entity_id` 的命名约定上自行编码（如 `t{tenant_id}:u{user_id}`），且无任何强制机制，漏传就跨租户。

**结论**：**表结构可直接照搬，召回实现不可用。** 归一化三元组的四表设计（三张查找表 + 一张三元组表）是"要图谱能力但不要图数据库"的现成答案，在 MySQL 与 DM8 上都是普通表与索引；但向量召回必须换成 Milvus，不能沿用它的 blob + 现建 FAISS 方案。

---

## 五、效果基准：全部不可用于拍板

**所有项目方自评的数字都显式标注如下**，一个都不要作为选型依据。

| 项目 | 基准与分数 | 评测执行方 | 可信度问题 |
|---|---|---|---|
| Memori | LoCoMo 87.0% / 721 added tokens | **项目方自评**，自家 docs 明写"our LLM-as-a-Judge framework" | README 把 721 写成"tokens per query"，自家 docs 表头却是"Added tokens (mean)"；且 README 的 87%/721 与所链论文摘要的 81.95%/1,294 **互相矛盾** |
| EverOS | LoCoMo 94.42（1540 题）/ LongMemEval 94.00（500 题） | **项目方自评**，但给了 `benchmarks/reproduce.sh` | README 自披露两处口径问题：对比表里别家 EverMemBench 是九类 macro 平均、自家是 micro 平均，不可并列；"九个类别"代码无法确认 |
| Hindsight | LongMemEval 91.4% / LoCoMo 89.61% | 论文口径（arXiv 2512.12818） | README 称成绩由 Virginia Tech Sanghani Center 独立复现，但**那四位研究者就是论文共同作者**，不构成独立第三方 |
| OpenViking | LoCoMo：OpenClaw 24.20%→82.08% 等 | **项目方自评** | 口径是"装上前后对比"而非横比别家；仓库内有 Agent Memory Leaderboard 适配器，但榜上是否已有成绩**未核实** |
| memU | LoCoMo 92.09% | **项目方自评 + 自建评测环境**（`memU-experiment`） | 这是 v1.5.1 的数字；**v2 没有任何公开得分**，且 v2 检索已改成单轮纯向量、无 LLM 参与，v1 数字不能外推 |
| MemTensor MemOS | LoCoMo 88.83 / LongMemEval 89.20 | 项目方 | 对应 TreeTextMemory 路径，不是能跑在 MySQL+Milvus 上的 `general_text` 档 |
| Letta | AIME / GSM 上"Pareto improvement" | **项目方自评**（Lin et al., 2025） | 博客页未给具体数值，无第三方复现 |
| BAI-LAB MemoryOS | LoCoMo F1 +49.11% / BLEU-1 +46.18% | 论文（EMNLP 2025 Oral） | 相对提升值，非绝对分 |

**唯一一次跨项目可比的真第三方横评**：`rocke2020/open-agent-memory-benchmark`（Apache-2.0，8 star），LongMemEval 六类各抽 10 题共 60 题，统一协议、关掉生成式 query rewrite / reflection / rerank，judge 与 answer 都用 DeepSeek V4.1 Flash：

| 项目 | 准确率 | 检索延迟 | 索引时间（中位） | answer-visible token |
|---|---|---|---|---|
| Hindsight 0.9.2 | **57/60（95.0%）** | p50 0.17s / p95 0.33s | 762s（最短） | 954k（最多） |
| Mem0 OSS 2.0.19 | 52/60（86.7%） | — | — | 392.6k（最省） |
| OpenViking 0.4.19 | 51/60（85.0%） | p50 0.79s / p95 1.30s | 1190s（最慢） | — |

该 README 自己指出 60 题样本小、不宣布胜者、未评估 user profile 质量（作者另称手工体验上 Hindsight 的 profiling 偏弱）。

**基准本身的已知缺陷**（叠加上述问题后，LoCoMo 分数只能作定性参考）：答案键错误约 6.4%；LLM-judge 会接受最高 63% 的故意错答；多人无法本地复现已发表数字。

**建议**：效果判据改为在 BiSheng 自己的对话与任务数据上建小规模评测集，不依赖公开基准。

---

## 六、信创侧结论：不要用 DM8 原生能力替掉 Milvus 和 ES

这是本轮一个独立的核实任务，结论明确。

### 6.1 DM8 确实有原生向量类型和 ANN 索引

**不是"做不到"。** 三条官方侧面证据相互印证：

- SQL 语言使用手册附录 1 的关键字表里，`VECTOR` 与 `HNSW` 列为关键字，`TO_VECTOR` 列为**系统保留字**，`IVF` 也在列。[来源: eco.dameng.com/document/dm/zh-cn/pm/sql-appendix.html，官方]
- dmPython 使用手册的 dmSQLAlchemy 方言包一章把 `VECTOR` 列入类型映射清单，写明"dmSQLAlchemy 2.0.8 起新增向量类型支持"，定义形式 `VECTOR(dim=3, format='float64')`。[来源: 同站 dmsqlalchemy-dialect-package.html，官方]
- 系统管理员手册附录 1 的数据字典，`SYSINDEXES.TYPE$` 原文列出"IF：IVFFLAT 向量，HS：HNSW 向量，MP：BMP 向量，DA：DISKANN 向量"，`XTYPE` 位标志同步给出对应值。[来源: 同站 dm8-admin-manual-appendix1.html，官方]

距离函数 `VECTOR_DISTANCE(vec1, vec2, distance_type)` 支持 COSINE / DOT / EUCLIDEAN / EUCLIDEAN_SQUARED / MANHATTAN / HAMMING，默认 COSINE。元素格式 int8 / float32 / float64 / binary。`dm_vec_client` 甚至给了仿 Milvus 的 API（`create_collection` / `insert` / `search` / `upsert`，`anns_field` 字段名都对齐 pymilvus）。

### 6.2 但工程上不可依赖，三条理由

**第一，SQL 层语法无公开文档。** 公开的 DM8 产品手册共 23 本，**没有向量手册、没有向量章节**；SQL 语言使用手册的数据类型清单不含 `VECTOR`，`CREATE INDEX` 语法里没有向量索引分支。能证实功能存在的全是侧面证据。这意味着调优参数、维度上限、索引行为、异常语义全部要靠厂商支持和自己实测，出问题时没有可引用的契约。

**第二，完整的向量叙事属于 DM9 不是 DM8。** DM9 于 2026-04 发布，白皮书写明支持四种元素格式、稠密与稀疏向量、四种 ANN 索引、六种距离函数——与 DM8 数据字典高度一致，说明两代共享内核。但**存量信创客户手上是 DM8**，而 DM8 官网版本动态（2024Q3 至 2026Q2 逐季条目）里连一条"向量"字样都没有，**起始补丁号未核实**。做成"需要某个未公开补丁号以上"的功能，等于把 memory 的可用性押在客户现场的小版本上。

**第三，增量写入模式与 memory 场景正面冲突。** 官方明说大批量插入后**必须重建索引**，否则新数据搜不到。memory 是持续小批量写、立刻要能召回的负载，这是最不适配的一类。Milvus 的 growing segment 本来就是为这个设计的。

### 6.3 全文侧必须不替

DM8 全文索引的中文分词其实比 MySQL FULLTEXT 好（真词典分词、三档粒度：`CHINESE_LEXER` 最少分词 / `CHINESE_VGRAM_LEXER` 机械双字 / `CHINESE_FP_LEXER` 最多分词），查询走 `CONTAINS(col, '洪山区' AND '太阳城')`。但对比 ES 缺的是整个可配置层，**且下列每条都是官方文档明示的技术限制**：中文分词依赖的系统词库**只读、不允许修改**（无自定义词典 / 同义词 / 停用词）、**不支持模糊匹配（通配符）**、索引非近实时（基表增删改先记入 P 表，未同步的数据查不到，要 `REBUILD` / `INCREMENT` 或建索引时指定 `SYNC TRANSACTION`）、无聚合能力、仅支持简体中文和英文。

更决定性的是本仓库的实际用法：**ES 远不止 RAG 关键词召回一路**，`telemetry_search`（dashboard 聚合查询）、`channel`（文章索引）、`core/logger` 都在用它。即使全文召回那一路换掉，ES 依赖也去不掉——存储种类不会减少一种，只会多出一套需要双实现维护的检索路径。

### 6.4 代价清算表

| 项 | 性质 |
|---|---|
| 稀疏向量（BM25 式稀疏召回） | **技术上不支持**——`SPARSE_FLOAT_VECTOR` 官方明说数据库暂不支持、使用报错 |
| 驱动层只暴露 HNSW / IVF_FLAT | **技术限制**（内核有 BMP/DISKANN，Python 侧取不到） |
| MySQL 兼容模式下向量不可用 | **技术限制**（与双方言策略冲突） |
| 全文的自定义词典 / 同义词 / 模糊匹配 | **技术上不支持**（词库只读、文档明示不支持模糊） |
| 全文索引近实时 | 支持但不够（需 `SYNC TRANSACTION` 或显式 `INCREMENT`） |
| 增量写入后的召回新鲜度 | 支持但不够（需重建索引） |
| 性能与可承载量级 | **未核实**——无任何官方或可信第三方数据 |
| 国产 CPU 上向量性能差异 | **未核实**——ANN 索引通常依赖 SIMD（x86 AVX2/AVX-512 vs ARM NEON/SVE），必须自测 |
| 起始补丁号、维度上限 | **未核实**——无公开文档 |
| ES 的聚合与 telemetry 用途 | **替不掉**（与检索无关的既有依赖） |

### 6.5 一处必须记录的来源可信度警告

达梦社区有两篇技术分享（《DM9 RAG 多路召回》《DM9 向量数据库内核设计》，2026-09-10，**社区投稿非官方**）给出了 `CREATE INDEX … USING hnsw (embedding vector_cosine_ops) WITH (m=16)`、`ORDER BY embedding <=> query_vec`、`to_tsvector('chinese', …)`、`SET hnsw.ef_search` 这类语法。**这是 pgvector / PostgreSQL 的语法，与达梦官方的 `TO_VECTOR` / `VECTOR_DISTANCE` / `CONTAINS` 体系互相矛盾**，大概率是套模板或 AI 生成。这两篇里的所有语法和数字（IVFFLAT 10-30ms、DISKANN 30-80ms、"AI 性能提升 30 倍"等）都不应采信。

### 6.6 Python 接入面（正面结论）

- `dmPython` 官方驱动已在 PyPI 发 wheel，最新 2.6.1（2026-10-19），覆盖 Linux x86-64 / aarch64 + Windows x86-64，CPython 3.7–3.14。**无 macOS wheel、无 sdist、无 LoongArch wheel**——龙芯上要自己从 DM 安装目录编译（可行性未核实）。
- `dmSQLAlchemy` 官方出品、PyPI 有包、三条线并行维护（1.1.x / 1.4.x / 2.0.x 对应 SQLAlchemy 1.3/1.4/2.0），2025 年至今每季度都有发版。**支持 async**：自 2.0.7 起，要求 SQLAlchemy > 2.0.22 且安装 `dmAsync`，URL 为 `dm+dmAsync://`。
- 国产 CPU：飞腾官方适配库登记 DM8 V8.4 × 银河麒麟 V10 / 统信 V20 / openEuler 22.03 等；但达梦社区下载按"CPU 型号 + OS"分发，官方明说组合不全、需留言提需求——**特定组合（如鲲鹏 920 + 麒麟 V10-SP3-arm）不一定现成有包**。

### 6.7 结论

**memory 不要走"信创下用 DM8 原生能力替掉 Milvus + ES"这条路。** 信创部署能省的那一种存储省不下来：ES 因 telemetry 和 channel 必须留，Milvus 因增量召回新鲜度和无公开性能数据不宜换。

若要给 DM 原生向量留位置，合理做法是在 vectorstore 抽象层**预留一个 DM 后端的扩展点但不实现**，等三件事同时成立再做：达梦公开 SQL 层向量文档、客户环境普遍到 DM9、在目标信创硬件上实测出可接受的增量写入召回延迟。

**需要向达梦官方直接确认的三点**（均为未核实，非不支持）：向量功能的最低 DM8 补丁号、`VECTOR` 的维度上限、aarch64 / LoongArch 上 ANN 索引是否有 SIMD 加速。

---

## 七、可借鉴机制清单

按"价值 × 落地成本"分组。每条都取证到可照着实现的程度。

### 7.1 守态与成本控制（来自 duoduo，四条）

这组解决的是"常驻记忆层会不会一直烧 token"，是全部候选里唯一把这个问题正面回答掉的。

1. **机械闸门与智能工作分离，接口是持久化任务单。** 确定性代码负责"测量 + 决定该做什么"，LLM 只负责"做"，两边通过 `.pending` 任务单交接，ack 方式是删除任务单。好处三个：空闲时零模型调用；任务单持久化，后台跑挂了只丢在途的那一个；任务单格式版本耦合，升级时能检出不匹配。**BiSheng 落点**：Celery beat 跑机械扫描、写一张 `memory_signal` 表，agent 侧消费。

2. **活动指纹闸。** `sha256(记忆三目录最新 mtime + 最新一条外部事件 id)[:16]`，与上次心跳相同就整轮跳过。**一个设计细节值得照抄**：广播板自己不在指纹里，所以改广播板不会自激发下一轮。**BiSheng 版本**：`max(update_time)` over 记忆表 + 最新一条外部事件 id，拼接取 hash，存 Redis。

3. **交互日窗口，不是墙上时间窗口。** 衰减窗口数的是"有真实用户消息的天数"（`FH = 30`），不是自然日。CHANGELOG 对这条的说明是"a quiet week no longer ages memories out"。**这条在企业场景比个人场景更重要**——客户使用密度差异极大，按自然日衰减会让低频客户的记忆被持续误删。

4. **退避与分区预算。** 超时且连续失败 > 2 → `min(n × 周期, 2h)`；报错且连续失败 > 1 → `min(2n × 周期, 4h)`；成功清零。分区配置带 `cooldown_ticks` / `max_duration_ms` / `model` / `effort`——**后台工作可以单独指到便宜模型**。

### 7.2 记忆有效性与治理（来自 duoduo，四条）

这是 BiSheng 最缺的一块：怎么证明写进去的记忆真的在起作用。

5. **有效性反馈闭环。** 四个 trajectory 标签把"记忆有没有用"变成可累积证据：`STRENGTHENING`（触发出现且行为符合）/ `WEAKENING`（触发出现但没照做或需纠正）/ `NEUTRAL`（扫到但无相关上下文）/ `NEW_SIGNAL`（有持久信号但无对应记忆行）。配套硬规则：**没有行级证据就不许改那一行**，并且"自然衰减"和"看着太长想压缩"都不构成修改理由——coldness 必须量出来。`WEAKENING` 细分 `recall-miss`（记忆存在但只凭摘要行动、没展开）与 `direction-wrong`（展开了，错在内容），**两者修法相反**：前者修召回纪律，后者修内容。

6. **接线温度指标。** touch 的定义是"前台工具调用的 `input_summary` 里出现了记忆文件路径"，写类工具不算 touch。由此导出四个指标：`expansionRate = memoryTouches / foregroundToolEvents`、`liveRatio = filesTouched / inventory`、`wiringIncompleteness = hotOrphans / filesTouched`、`coldCount`。另单列 hot orphan（被读了但索引不可达）前 10。**BiSheng 已有完整的工具调用事件流，这套指标几乎零成本算出来**，直接回答"写进去的经验 agent 到底读不读"。报告**读即删**的设计也要照抄——避免一次挂掉的后台任务冻结一份过期快照。

7. **两层分工：一行只负责点火，不负责讲完。** 常驻注入层每行 = 可识别触发 + 一句方向 + 一个指针；完整的 how 放在指针指向的节点里按需打开。这解决一个很实际的失效模式：一行写得太全，agent 光凭这行就行动了，指向的节点永远不被打开，两层塌成一层。对应的治理动作（内容下沉）**不需要证据即可执行**，因为它不判断、不丢失，只搬家。

8. **双硬上限 + 禁止标题 + 行序即排序。** 100 行 × 每行 200 有效字符（`[[x]]` 按一个字符计），超则投压缩任务单——天花板约 20K 字符写死在代码里。禁止标题的理由是"标题不携带梯度，过期的标题还会误标它下面每一行"。排序禁止按任何单一计数机械排序，因为"注意力是位置相关的：头尾强、中间弱、相邻成簇"。

9. **先警告再删除的遗忘三态机。** `ISLAND`（有入边但索引不可达）/ `NEWBORN`（< 48h）/ `STALE`（不可达 + 零入边 + ≥ 48h），只有 `STALE` 会被删。开关设计上"只开删除不开检查"会被代码主动拒绝并记日志——**保证一个节点在被删之前一定收到过警告**。BiSheng 版本把 `git rm` 换成软删除 + 版本表即可。

### 7.3 agent 记忆架构（来自 Letta，五条）

10. **记忆写权限与对话权限分离。** 主 agent 只给只读工具（`conversation_search` / `archival_memory_search`），记忆写工具全部挂到后台 agent 上——两套工具集在代码里是互斥的。这解决主 agent 在对话压力下胡乱覆写记忆的问题。**落到 BiSheng 很自然**：后台 agent 正好是一个 Celery task，比 Letta 的同进程 asyncio task 更可靠，顺带解决了它那个"进程重启留下永远 running 的 Run 记录"的缺陷。

11. **触发闸 + 增量水位。** 频率用 `turns_counter % N` 计数闸（默认 `None` = 每轮都跑），水位用 `last_processed_message_id` 记在会话上，后台 agent 每次只读 `(水位, 本轮首条)` 的增量窗口。**这样调低频率只会让单次 transcript 变长而不会漏消息。** 成本上界要按"后台 agent 数 × max_steps(50)"估，不是按一次调用估。

12. **把剩余容量写进 prompt。** 渲染记忆块时每块带 `chars_current={len(value)}` / `chars_limit={block.limit}`，模型因此能自己决定何时压缩，而不是溢出后由系统截断。**配套的 line-number 编辑模式必须带那句警告**："Line numbers shown below (with arrows like '1→') are to help during editing. Do NOT include line number prefixes in your memory edit tool calls."——不加模型一定会写回去。

13. **把记忆伪装成文件系统。** 现役写入工具是 `str_replace_editor` 风格的单一工具 `memory(command, path, ...)`，子命令 `create / str_replace / insert / delete / rename`，路径形如 `/memories/user_preferences`——复用模型最熟的文件编辑范式，比自造 `core_memory_append` 这类专用工具效果好（它自己就是从后者演进过来的）。

14. **上下文淘汰用部分驱逐 + 递归摘要。** 触发 `0.9 × context window`（用 0.9 而非 1.0 是为了避开 provider 的"too many tokens in prompt"回退）。算法：`target = round((1-0.30) × total)` 保留末尾约 30% → 从该点向后找**第一条 role==assistant** 作切点（因为 index 0 是 system，插入摘要后 index 2 必须是 assistant，否则部分 provider 的消息序列校验会失败）→ `messages[1:切点]` 送摘要 → 摘要以 **role=user 插回 index 1** 形成递归摘要。三层回退：clamp 工具返回值长度 → 按 UTF-8 字节预算中间截断（head 0.3 / tail 0.3）→ 硬截断。

### 7.4 数据模型与检索（来自 Hindsight / Memori / Graphiti，六条）

15. **bi-temporal 三列分开记。** `occurred_start` / `occurred_end`（事实发生、有效区间）、`mentioned_at`（被提及即记录时间）、`event_date` 三者独立成列。Hindsight 是全部候选里唯一真正实现 bi-temporal 的，**可直接作为 BiSheng 的 schema 蓝本**。Graphiti 的核心价值也在这里（不在它的存储——四个图库都不可用）：把"事实何时为真"与"何时被记录"分开，新事实到达时让旧边失效而非删除。在 SQL 三元组上用 `valid_from` / `valid_to` / `recorded_at` / `invalidated_by` 四列实现。

16. **归一化三元组落普通 SQL 表。** `subject` / `predicate` / `object` 三张查找表存唯一值，一张三元组表以 `subject_id/predicate_id/object_id` 连成边，查询靠 JOIN。**这是"要图谱能力但不要图数据库"的现成答案**，在 MySQL 与 DM8 上都是普通表与索引，没有专有语法。实体消歧与谓词归一化做成可替换策略。

17. **客观事实与主观信念分开存。** Hindsight 的四类记忆网络：world facts（世界事实）/ experiences（agent 自身经历）/ observations（多条记忆凝聚出的、带证据的信念）/ mental models（综合出的世界理解）。`confidence_score`（0–1）有 CHECK 约束，**只允许 `fact_type` 为 opinion 或 observation 的行持有**——事实不带置信度，信念才带。

18. **冲突消解是精炼而非覆盖。** observations 的新证据是加强、削弱或扩展既有信念，每条保留原文引述和 `proof_count`。OpenViking 的做法可以叠加：**保守合并**（只合并明确同一身份的，拿不准的要人工点明）+ **不覆盖冲突**（目标已存在就报冲突，要求读两份后显式合并再删源）。

19. **四路并行检索 + RRF + rerank。** semantic（向量）/ keyword（BM25）/ graph（实体、时间、因果链）/ temporal（时间范围过滤）并行，RRF 融合后 cross-encoder rerank，再按 token 预算裁剪。融合的两级 boost 值得注意：stage 1 在 rank 空间提权，stage 2 对被 boost 的 arm 的 rank 1 加绝对值再按 rank 衰减 `additive × rank_divisor / (rank_divisor + rank - 1)`，**temporal arm 例外不衰减**，因为它按日期邻近度排序而非相关度。BiSheng 的知识库已是 Milvus(dense) + ES(sparse) 双召回，这套可以直接长在上面。

20. **标签双写。** JSON 列便于取回 + junction 表便于查询（Letta 源码注释原话"dual storage: json column for fast retrieval, junction table for efficient queries"）。在 MySQL|DM8 上可直接落地。

21. **三层渐进加载。** OpenViking 的 L0 abstract（一句话）→ L1 overview → L2 全文，**目录级作用域检索而非全局平铺向量池**。这比"一个大向量池 top-k"更省 token 且更可控。

22. **可插拔存储抽象的形状。** Mem0 的 `VectorStoreFactory` 是 provider 字符串 → dotted path 的类级 registry + 动态 import + config 作 kwargs，未知 provider 抛错。BiSheng 把 Milvus/ES 做成两个 provider，并给 DM8 留一个关系库 provider 位（§6.7 的扩展点）。

### 7.5 两条踩坑记录（来自 Hindsight 文档，直接抄走）

23. **作用域 id 只在上层边界内唯一时，所有按它做 key 的地方都要带上上层边界。** Hindsight 的 bank id 只在 tenant schema 内唯一，多租户部署的 LLM 路由必须同时按 `target.schema` 做 key，否则一个租户可以用另一个租户的 bank 名**把账单记到对方头上**。

24. **分片主键必须带作用域。** Hindsight #4244：`chunks` 表只按 `chunk_id` 做主键，老版本生成的 id 会跨 bank 碰撞导致串数据，现已改为拒绝覆盖并抛 `ChunkIdOwnedByAnotherBank`。

---

## 八、底座设计要点

一次设计、分期开通，不是三套实现。

1. **事实的唯一存储是 MySQL|DM8 的事实表 + 三元组表。Milvus 与 ES 只存派生索引，可重建、不作 SSOT。** 这条同时解决了"信创下向量层能否降级"和"索引损坏怎么恢复"两个问题。

2. **作用域字段从第一天就写全**：`tenant_id` / `user_id` / `scope=personal|agent|org` / `source_session_id`，避免二三期回填。参考 memU 的 ADR 0003——把 scope 作为真实列合并进所有持久化模型，而不是外挂过滤，并对全部 scope 字段建复合索引。

3. **多租户靠现有 ContextVar 自动注入，不引入项目自带的 user/namespace 概念。** 注意既有坑：租户自动过滤**只拦 SELECT**，批量 UPDATE/DELETE 与 raw `text()` SQL 无注入，必须手写 `tenant_id` 条件（已泄漏过两次）。共享范围统一走 OpenFGA 判定，**不要在 memory 层自建第二套权限模型**。

4. **所有抽取走 Celery，记 token 账，抽取失败不阻塞对话。** 可复用 `llm_token_log` 加 `biz_type` / `biz_id` 列的既有做法。注意 Celery Beat × 多租户的既有坑：任务体迭代所有活跃租户时要逐次 `set_current_tenant_id()`，跨租户枚举查询本身要包在 `bypass_tenant_filter()` 里。

5. **存储层做成 provider 抽象**（照 Mem0 的 factory 形状），保证 MySQL 与 DM8 两套方言、以及未来换向量后端时不触碰业务代码。DM 原生向量留扩展点不实现。

6. **记忆状态绝不能做成"每轮重写一个大 JSON 行"。** 这是已踩过的坑：热路径上整行重写大 JSON 在 DM8 上会耗尽 undo 段、报"undo 记录版本太旧"，UPDATE 挂住持锁、该行所有读 500（灵思详情白屏就是这么来的）。高频状态走 Redis 作无损事实源，按节流落库。

7. **任务模式的接线点已经现成。** `linsight/domain/services/agent_factory.py` 基于 deepagents，已挂四个自定义 `AgentMiddleware`（resilience / invalid_tool_call_repair / tool_loop_breaker / citation_source）。记忆的读注入与写触发都有扩展位，不需要改框架。

8. **新 config.yaml 顶级键必须默认注释掉。** `ConfigService.load_settings_from_yaml` 在 import 期对未知顶级键抛 `KeyError`，老镜像会直接重启循环。

---

## 九、分期建议

**一期：client 日常模式个人记忆。**
机制需求最窄，全部落在已验证可行的面上。借鉴 §7 的 15/16/18/19/20（数据模型与检索）+ 10/11（写权限分离与增量水位）+ 2/3（指纹闸与交互日窗口）。不需要图遍历，不需要 bi-temporal 的完整语义（但 schema 要预留那四列）。

**二期：任务模式 agent 长期记忆。**
与一期共用事实存储，增量是"跨任务经验与失败教训"的粒度定义、工作区延续，以及与现有 deepagents/Celery 的接线。对标 Letta 与 duoduo，两者的机制都已取证到实现级（§7.1 / §7.3）。**风险集中在"写入什么粒度才复用得上"而非存储**——这一期的主要工作是 §7.2 的有效性反馈闭环，因为没有它就无法判断写进去的经验是否真的在被用。

**三期：组织/团队知识沉淀。**
最晚做，因为它才真正需要 bi-temporal 与实体消歧（多人多会话的同一实体、互相矛盾的事实、事实的有效期），并且必须与现有知识库/知识空间并存。借鉴 §7.4 的 15/16/17/18 + §7.5 的两条踩坑记录。共享范围统一走 OpenFGA。

---

## 十、未核实清单与复核时点

**未核实（不是不支持），需要时自行取证或向厂商确认：**

- DM8 向量功能的最低补丁号、`VECTOR` 维度上限、aarch64 / LoongArch 上 ANN 索引是否有 SIMD 加速——需向达梦官方直接确认。
- DM8 在 memory 负载下的向量检索性能与可承载量级——无任何官方或可信第三方数据，只能在目标信创硬件上压测。
- MemTensor MemOS 的 SQLAlchemy DDL 能否在 DM8 上原样建表。
- Memori 新增 DM8 驱动时需逐项实测的方言行为：`create table if not exists` 是否支持、upsert 走 `MERGE INTO` 还是 MySQL 兼容语法、dmPython 对 bytes/LOB 的绑定行为、分页语法、标识符大小写（DM8 默认大写而它按小写列名取值，极可能需统一加引号）、`on update current_timestamp` 的等价物、`requires_rollback_on_error` 取值。
- `dmSQLAlchemy` 的 `dialect.name` 实际取值（推断为 `dm`，未运行验证）。
- Letta sleep-time compute 的额外 token 倍数；letta-code 的气隙部署可行性。
- duoduo 是否有企业生产案例（唯一真查不到的一项）。
- OpenViking 在 Agent Memory Leaderboard 上是否已有成绩。
- MindMemOS 论文（arXiv 2608.12428）中 memU 66.67 / mem0 64.20 / MemOS 80.76 这组对比数字（只看到检索摘要，未读原文）。
- 蚂蚁 / 智谱官方 GitHub 组织页是否有未被搜索收录的开源 memory 框架——本轮**未核实到任何专门面向中文或国产化环境的开源 memory 方案**，但这是"没查到"不等于"不存在"，国内团队常先发 Gitee 或内部版本。唯一的间接国产化信号是 OceanBase 官方做了 `langgraph-checkpoint-oceanbase`，说明 MySQL 协议侧的 `BaseStore` 适配在国内已有先例。

**复核时点**：Graphiti（v0.31.1，2026-10-15）与 Cognee（main 分支）都在高频演进，Kuzu driver 已标 deprecated 待移除；Memori 近半年发生过云形态上线与组织迁移；letta-code 接近日更。**三个月后（约 2027-01）结论需复核一次。**

**来源等级说明**：本报告的项目事实以 GitHub API 元数据、`raw.githubusercontent.com` 拉取的源码与 LICENSE 原文、官方文档为主；达梦部分明确区分了官方手册与社区投稿（§6.5 记录了一处已证伪的社区来源）；duoduo 的机制细节部分来自用户 fork 内的反压缩还原产物，该产物有 AST 全等证明链（出厂 ≡ 美化 ≡ 还原，100% 覆盖，CI 每 PR 重跑，静态部分在 v0.8.3 成立），并与上游提示词、CHANGELOG、技能文档三处交叉吻合。
