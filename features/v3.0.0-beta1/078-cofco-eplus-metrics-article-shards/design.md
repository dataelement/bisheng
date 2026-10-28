# Design: F078 中粮 E+ 事件指标与频道文章主分片迁移

**状态**：实现及本地验证已完成；用户已授权合并推送目标线，交付状态以 Git 记录为准；未执行生产迁移。验证边界见 [validation.md](./validation.md)。
**关联**：[Spec](./spec.md) · [版本契约](../release-contract.md) · [需求确认](../../../docs/cofco-1028-eplus-es-shards-discovery.md#6-确认记录)
**版本**：v3.0.0-beta1 / 中粮定制线；基线 `8ebcfdcc270fbfa1c20b100262ccd5d83844c76c`。
**最后更新**：2026-10-28；补充迁移批量参数。

## 1. 目标与非目标

正式 E+ 问答在终态提交后输出自包含指标日志，监控只凭终态做人数、消息、会话与成功率统计；连接生命周期和协议存活事件支持监控计算当前连接数。频道文章索引主分片配置默认 3，配套停写维护脚本迁移已有数据。

本次不建设统计服务、Redis 聚合、实时用户计数、可靠日志投递或采集看板；不改变现有身份、权限、问答调度与连接单活规则；不在线双写，不自动在应用启动时迁移，不执行生产迁移。

## 2. 关键约束

遵循 [Constitution](../../../docs/constitution.md) C1–C8、当前版本契约和 `src/backend/scripts/AGENTS.md`。本功能不新增领域表、关系库 schema 或 HTTP API；业务终态仍由既有业务存储决定，指标不反向参与业务判定。

- 所有指标通过现有 `emit_metric` 和 `metric_log.enabled/eplus` 开关，新增域必须显式注册到 E+ 开关；未知域默认放行不能代替注册。
- 多节点共享的是业务消息身份，不建立统计集合。监控按 `tenant_id/user_id` 去重人数，按 `tenant_id/bot_id/message_id` 去重问答。
- 正式 Worker 才注入指标输出器，调试服务默认不注入。指标失效时记录脱敏诊断并返回，不抛到业务调用方。
- ES 文章索引是现有部署内的共享存储；维护范围覆盖所有租户、全部 API/Celery 写入方。脚本建立写屏障，但不替运维停止、排空或恢复应用任务。
- 迁移环境需要源与目标的读写/管理权限、任务查询权限、可用的 `_source`，以及足够容纳源、恢复副本与新目标的磁盘和分片容量；不临时降低副本数来绕过容量要求。
- 指标时钟沿用当前服务/DB 的时间约定，部署内 DB 与所有 Worker 必须时区一致且同步时钟。总耗时基于持久化接收时间与终态时间，不用不同进程的 monotonic 值相减。

## 3. 方案对比与选定

### 决策 1：自包含终态日志与监控侧去重

- 备选：每阶段指标由监控关联；在后端用 Redis 做去重/窗口统计；终态带齐统计信息。
- 选定：终态带齐信息，仅监控去重。现有 `BS_METRIC` 已用于模型调用完成事件，用户明确要求沿用并简化监控处理。
- 不采用阶段关联和新增 Redis 统计，因为同一终态已有足够信息；现有业务去重、租约、回复限额依赖保持原用途。
- 重新考虑条件：用户明确需要实时在途量、在线人数或可靠的完整业务账本时，另行定义需求。

### 决策 2：业务提交后输出，覆盖多个终态入口

- 备选：只在 `robot_service.run_turn` 正常退出时打日志；统一在既有事务提交后输出终态快照。
- 选定：事务提交后输出。代码中准入拒绝、排队超时、重启恢复分别在 admission、scheduler/repository 路径完成，单一正常执行出口会漏记。
- Repository 复用必要的既有消息/轮次读取构造只读快照，暂存在当前事务的 session.info；Service 成功退出事务后取出并调用注入的输出器。缓冲不是共享真相，事务失败随会话丢弃，不新增统计 SQL。Repository 不直接写日志，不把日志回调放在事务提交前。
- 重新考虑条件：业务终态入口改变时同步终态覆盖表；不能靠追加 finally 把回滚、取消或重复状态误计为新终态。

### 决策 3：主分片配置与迁移

- 备选：全局 ES 默认值；应用启动自动重建；频道文章专属配置与显式维护脚本。
- 选定：专属配置 `channel_article_index.number_of_shards`，严格正整数、默认 3。同步/异步创建共用一个 settings 构造函数；已有索引不变。
- 旧数据采用任意有效目标分片数的 reindex，不依赖 split/shrink 的倍数约束。应用继续使用 `channel_articles`；切换采用别名，不新增业务索引名配置或要求所有节点同时改配置。
- 重新考虑条件：文章存储改成租户独立索引、数据流或 ILM 时，另行评审迁移范围。

### 决策 4：停写、完整基准与可恢复切换

- 备选：边写边复制后数文档；停写后复制，只比较 count；停写屏障与刷新后做完整身份/内容核验。
- 选定：运维停写并排空 → 源 `indices.add_block(block="write")` → 检查每个分片的屏障结果 → 源 refresh → 建立源完整基准 → 复制/核验 → 切换。专用 write-block API 成功返回时覆盖已在途写入；refresh 使此前已确认操作进入检索视图。[ES 写屏障](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/index-modules-blocks.html)、[Refresh](https://www.elastic.co/docs/api/doc/elasticsearch/v8/operation/operation-indices-refresh)。
- 若 `channel_articles` 仍为具体索引，必须先验证独立恢复副本，再用同一 aliases 请求移除原具体索引并添加同名业务别名；原本为单索引别名时，移除旧关系并添加新关系，保留旧实体。切换需验证响应和实际关系，不能只看 HTTP 200。[ES Aliases](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/aliases.html)。
- 重新考虑条件：客户不能停写，或实际集群不具备所需 API/容量时，先报告前置条件不满足，不能偷偷降级为有遗漏风险的复制。

## 4. 基线与实现流程

### 4.1 已核实的基线

- `eplus/worker.py:build_worker_runtime` 构造正式 admission、scheduler 和 connection supervisor；`EPlusWorkerProcess.run` 先调用 `initialize_app_context`。
- `message_service._reserve` 先持久化接收消息再校验身份。`turn_id` 在 PREPARING 阶段建立，因此准备失败也属于已准入问答；无权限、繁忙没有新问答轮次。
- `conversation_scheduler.complete_and_wake_next/expire_waiting_turn/recover_queued` 包装既有 SQL 事务；对应 Repository 完成处理终态、等待超时和恢复中断。`reply_status=FINISHED` 也可表示失败提示已发送，不能独立判断问答成功。
- `connection_client._emit` 已提供每次连接 ID、认证和协议 `heartbeat.ok/failed`；正式 Worker 目前未注入指标 event sink。supervisor 已有租约有效性检查。
- `article_index.py` 的同步/异步创建共用 ARTICLE_SETTINGS，尚未声明主分片数；实际读写统一使用 ARTICLE_INDEX_NAME。
- 正常初始化在 `core/context/manager.py` 为默认 EsConnManager 注册 `settings.get_search_conf()`；`get_es_connection` 在缺失上下文时的兜底却使用 `get_telemetry_conf()`。迁移必须完整初始化并取默认连接，不能直接依赖兜底，也不在本功能顺带修改该历史差异。

### 4.2 问答终态流程与埋点覆盖

业务入口 → 既有 Repository 事务生成终态和快照 → Service 成功提交 → 输出器将快照转为指标 → `emit_metric("eplus_robot_request", ...)` → 外部日志管线。

| 终态路径 | 接入位置 | 输出要求 |
| --- | --- | --- |
| 无权限/繁忙/准入前失败 | `message_service` 的 reserve/拒绝事务提交之后 | admitted=0，result=rejected，固定原因分类 |
| 正常回答或执行/发送失败 | `conversation_scheduler.complete_and_wake_next` 提交之后 | admitted=1，result=success/failed，取最终持久化状态与回复状态 |
| 准备/排队超时 | `conversation_scheduler.expire_waiting_turn` 提交之后 | 仅实际终态转换成功时输出 failed |
| 重启恢复 PREPARING/RUNNING 中断 | `conversation_scheduler.recover_queued` 提交之后 | 对本次真正确认失败的既有消息输出 failed；不扫描回填其他历史终态 |
| 重复回调 | admission 返回 DUPLICATE 时 | result=duplicate，单独观察回调处理结果，不冒充原消息问答终态 |

新增 `eplus/domain/schemas/metric.py` 的终态快照只包含日志需要的元数据，不携带正文、答案或媒体。Repository 从既有业务读取结果构造快照，放入当前事务的 session.info；terminal_metric_transaction 在提交后清空并通知，回滚时丢弃。原公开返回值保持兼容，不在 Service 写 SQL。完成、超时和恢复查询用 LEFT JOIN 复用对应 inbound 行，不新增单独查询；inbound 缺失时保持原业务异常，不因指标静默跳过。恢复扫描范围沿用既有逻辑。

在 `worker.build_worker_runtime` 注入 `eplus/infrastructure/metric_events.py` 输出器；测试和 debug 默认使用空输出器。只观察实际已提交状态；事务回滚不输出成功，重复调用不伪造新结果。指标封装连同脱敏、序列化的异常一起隔离。

### 4.3 日志字段合同

统一 `BS_METRIC` + logfmt，新增域 `eplus_robot_request` 和 `eplus_robot_connection` 均映射到现有 `metric_log.eplus`。`schema_version=1`，`source=eplus_robot`，不改已有 `eplus_notify`。

| 字段 | 类型与规则 | 消费方 |
| --- | --- | --- |
| `tenant_id` | 正整数，既有租户 ID | 所有统计隔离 |
| `bot_id` / `bot_config_id` | E+ 机器人 ID / 当前配置 ID | 机器人分组及连接关联 |
| `user_id` | `sha256` 对规范化 JSON `["eplus-user-v1", tenant_id, sender_external_id]` 的完整十六进制摘要；跨节点/机器人确定性一致 | 监控按 tenant_id + user_id 去重；不输出原外部用户 ID |
| `message_id` | 既有 E+ `msgid`，同一业务消息不重新生成 | 与 tenant_id + bot_id 组成业务消息去重键 |
| `conversation_id` | 既有会话 UUID；准入前未建立时省略 | 对 admitted=1 的已结束会话去重 |
| `event_id` | 每次实际输出的观察事件 UUID；日志被重复采集时不变 | 去重重复采集；duplicate 回调观察不与原业务终态合并 |
| `admitted` / `result` | 0/1；success、failed、rejected、duplicate | 成功率只选 admitted=1 且 result=success/failed |
| `reason` / `reply_status` | 固定原因码及既有回复状态，不放 exception 原文 | 失败分类 |
| `event_time_ms` / `elapsed_ms` | 终态业务时间的 Unix 毫秒；持久化接收至终态的总耗时，含准备/排队 | 窗口归属及单次耗时 |

用户标识的 SHA256 是稳定脱敏，不是新的业务身份，也不引入密钥轮换或身份映射表。消息 ID 取已校验的协议标识，不使用连接级 req_id 或新生成的回调 ID 替代。

对业务终态重复观测，使用相同的 `message_id/result/event_time_ms`；重新采集不改变 event_id。监控先排除 duplicate，再按业务消息键去重问答。duplicate 仅以 event_id 去重采集后计回调重复次数，不读取或重写原消息结果。

新增合同示例（本地测试验证字段，非客户环境采集记录）：

```text
BS_METRIC domain=eplus_robot_request schema_version=1 source=eplus_robot tenant_id=1 bot_id=robot-a bot_config_id=12 user_id=<sha256> message_id=m-42 conversation_id=<uuid> event_id=<uuid> admitted=1 result=success reply_status=FINISHED event_time_ms=1793097600000 elapsed_ms=3200
```

统计均按 `event_time_ms`，不按采集时间。已结束问答去重后，成功率 = success / (success + failed)，分母为 0 时无样本；拒绝与重复单列。使用人数为有已准入问答结束的去重用户，完成回答人数只看 success；不推算实时在线用户。

### 4.4 连接事件

supervisor 在每次尝试构造 client 后，调用可选指标接线接口，注入绑定当前租约的观察回调；WorkerConnection 将其接入现有 transport event sink。回调只读现有租约的 ensure_owned，不新增 Redis 请求或统计键；不改变持锁与续租周期。

- 字段：公共字段、`connection_id`、该连接内递增 `event_seq`、`event`、`event_time_ms`、可选固定 `reason`。
- 事件：opening、authenticated、auth_failed、retrying、heartbeat_ok、heartbeat_failed、closed、taken_over。
- authenticated 与成功协议 heartbeat 才构成存活证据；输出时必须仍持有租约。复用当前 30 秒协议心跳，不新增独立统计定时器。
- 新增 `metric_log.eplus_connection_stale_after_s=90`，严格正数；对每次实际连接的心跳配置检查该值不小于 `2 * (heartbeat_interval_seconds + ack_timeout_seconds)`，不满足时该连接的指标报告明确配置错误，不能改变业务连接。存活事件带 `expires_at_ms`，监控以其判断过期。
- transport 的最终清理路径保证各类退出都能发 closed（正常进程退出除外的不可执行场景沿用超时）；仅打日志，不再以历史 AUTHENTICATED 数据库行判断实时状态。
- 监控按 connection_id/event_seq 处理乱序，旧 heartbeat 不能覆盖同连接更晚的 closed；观察器自身也拒绝 closed/taken_over 后的存活事件。取未过期且未关闭的连接后，按 `(tenant_id, bot_id)` 去重得到有效机器人连接数，避免租约切换窗口重复算同一机器人。连接次数由 opening 事件计数。

### 4.5 分片配置与新建索引

新增 `ChannelArticleIndexConf` 注册到核心 Settings：

```yaml
channel_article_index:
  number_of_shards: 3
```

`number_of_shards` 使用严格整数且大于等于 1，拒绝 bool、浮点、小数文本和无效值。无配置使用同一模型默认 3。更新受版本控制的 `docker/bisheng/config/config.yaml` 示例，不修改用户本地的忽略配置文件，也不把部署级分片参数混进 initdb_config。

`channel/domain/es/article_index.py:get_article_index_settings()` 深复制当前分析器配置，再注入 `settings.channel_article_index.number_of_shards`；同步/异步 ensure 函数共用该构造结果，不修改共享字典。迁移从同一 Settings 字段取值，不另设 --shards 参数。

### 4.6 手动迁移流程

新增 `scripts/repartition_channel_articles.py` 及可选薄 shell wrapper，README 登记。脚本 bootstrap backend 路径并使用 argparse；`config` 环境变量和共享 settings 与服务一致。`initialize_app_context(config=settings)` 后取得默认 `get_es_connection`，finally 执行 `close_app_context`；不得调用 init_config、create_all 或权限运行时。默认 dry-run 不调用任何业务/ES 写 API，初始化过程也须用测试验证不产生持久化配置或业务写入。

脚本参数：默认 dry-run；`--apply` 执行；apply 需要显式 `--writers-paused` 表示已停并排空全部写入方；`--run-id` 标识一次维护；`--status` 只读检查已有 run；`--batch-size` 为严格正整数，默认 5，在访问 ES 前校验，统一控制全量指纹校验分页及备份/目标 reindex 的 `source.size`，dry-run 与 apply 分别传入相同值。run-id 限定安全的小写字母数字连字符；无值时 dry-run 展示新建议值，apply 要求使用该明确值。没有目标分片命令行覆盖，也不允许任意源索引或通配符。

1. **解析与预检**：解析 `channel_articles` 为一个具体实体，记录名称、UUID、原 mappings/settings、所有关联 alias 元数据、当前分片和文档数；缺失与多实体 alias 分别报错。若分片已达标仅报告跳过。源关闭、不可读、缺少 `_source`、集群 red、磁盘水位/分片容量不满足、原有只读限制未解释时停止；展示源/备份/目标的占用估计与分配条件，不能把估计当成空间保证。
2. **互斥与恢复前提**：同一源一次只允许一个运维执行者；所创建固定恢复实体名同时作为原子执行资格，创建失败不能进行后续源写操作。先检查活跃 reindex 任务及已有本功能目标/恢复副本，发现未完成 run 就只报告状态、拒绝新 apply。使用源 UUID 派生的固定恢复副本名，在任何源写屏障之前原子 create 恢复实体，create 请求内一次性写入 RESERVED 阶段及 run/源身份元数据；成功者才拥有本次执行资格，并发 create 失败方停止，不自行接管。该实体尚无数据，不作为有效备份；已有副本不被覆盖。
3. **写屏障与完整基准**：先确认运维停写，再专用 add_block(write)，检查 acknowledged 与各分片结果；源 refresh 后所有 search/scroll 禁止部分分片结果，建立完整基准。源 UUID、alias 关系或源业务 mappings/settings 相对预检改变即停止。
4. **构建恢复副本及目标**：恢复名 `channel_articles__backup_<sha256(source-uuid)前32位>`，目标名 `channel_articles__reshard_<sha256(run-id)前32位>`；二者从源实际 mappings/settings 建立，目标注入配置分片数，恢复副本维持原分片数。恢复实体沿用步骤 2 已原子预留的实体，不重复创建；失败时空实体不算有效备份，不能切换。
5. **复制**：异步 reindex 精确的源实体到预建实体，`op_type=create`、`routing=keep`、不使用 conflicts=proceed；先完成恢复副本再完成新目标。每个任务拿到 ID 后立即输出，并更新该实体 mappings `_meta.bisheng_article_reshard` 的 run 标记；检查 completed、顶层 error、timed_out、failures 与冲突。原业务 `_meta` 原样保存，命名空间存在不属于本功能或当前格式不可识别的内容时拒绝；识别到本功能历史标记时按业务 mappings 与当前运行标记分离，旧运行资料保留于旧实体/恢复副本，不把历次快照递归嵌入新快照。
6. **核验**：恢复副本与目标分别 refresh 并建立 write block，完整扫描比较源基准与副本/目标的文档数、身份、routing 和 `_source` 指纹，检查 mappings、相关 settings、实际分片数与副本配置。每次搜索都检查失败分片；源基准核验前后保持不变。只按 count 或抽样校验不足以通过。
7. **切换准备**：恢复目标正常写入所需的原 refresh/ingest 等设置并再次核验；新目标在切换前仍保持 write block。记录完整 aliases 操作计划，再次确认源 UUID、alias 关系、源基准和目标配置未变。
8. **切换**：源为具体 `channel_articles` 时，一个 aliases 请求中 remove_index 原实体并 add 目标为同名 alias；源已是别名时 remove 原关系（must_exist=true）再 add 新关系。原实体的其他 alias 关系同步迁移到目标，保留 filter、routing、is_hidden 及原写入规则；业务 alias 明确唯一写索引。所有名称精确列举，不使用通配符。检查 errors/action_results，并重新解析所有受影响 alias；HTTP 超时或结果不确定进入待核实，不能重发删除动作。
9. **结束检查**：仅确认所有关系正确后解除目标的本次 write block，检查逻辑入口可查询且指向唯一可写实体；保留恢复副本的写保护。输出目标分片、基准/目标文档数与指纹、任务及恢复资料。脚本不写入测试文章；真实写入/更新/删除通过验收环境验证，运维据报告恢复应用写入。

迁移元数据记录在已创建副本/目标的 `_meta`：run-id、源 UUID、目标分片、batch_size、阶段、任务 ID、原设置/alias 摘要、基准指纹。dry-run/完成报告及复制进度输出本次 batch_size；status 返回运行元数据内的值，历史运行缺少该字段时返回 null。完整原 mappings/settings/alias 快照作为同一元数据的嵌套字段保存，用于恢复；快照单独保存源业务 `_meta`，剥离本功能历次运维标记以避免递归嵌套，不保存凭据。它是运维恢复资料，不新增应用运行时查询或全局业务状态。源 UUID 和 run-id 均用 SHA256 的前 32 位生成固定长度安全索引片段；不得直接拼接未校验原 UUID。

**不自动续跑**：重试相同 run 先读上述元数据、实际 alias 和任务状态，只显示 phase/任务/恢复动作；不会重新 launch 已有任务、重新创建已有目标或猜测成功。进程在任务提交与记录 ID 之间退出时，已写入的 COPY_PENDING 表示任务状态未知，保留停写，运维先检查/取消遗留任务并核实数据后再处理。`--status` 和默认 dry-run 均保持只读。用户需要可靠自动续跑时另立需求。

### 4.7 settings、内容核验与恢复

复制实际源配置，排除 ES 生成/只读的 UUID、创建时间、版本、provided_name、历史 resize 字段及旧的物理 routing-shard 拓扑；目标由目标主分片生成合法 routing 拓扑，但保留每个文档 `_routing`。原 `routing_partition_size` 等限制与目标不兼容时预检失败，不偷偷改业务路由。保留 analysis、similarity、排序、业务 mappings、refresh 策略和副本策略；未知且无法合法重建的源配置明确报错。

复制期间显式禁用目标与恢复副本的 default/final ingest pipeline，reindex 请求 `pipeline=_none`，避免既有数据被再次转换；完成后恢复原设置并核验。创建前解析匹配的 composable/legacy 模板及其有效配置，若会给任一临时实体自动附加 alias，先拒绝创建，避免提前污染业务查询；无法确定模板效果也停止。创建后再核验实际 mappings、aliases 和 settings，无法保持源合同则在切换前失败，不修改集群模板。[ES ingest 设置](https://www.elastic.co/docs/reference/elasticsearch/index-settings/index-modules)。

mappings 核验排除单独比较的本功能运维标记；源原有业务 `_meta` 与其他 mappings 内容仍须一致。全量指纹：逐文档规范化 JSON `[_id, _routing, _source]` 后 SHA256，累加 256-bit sum 和 xor 并记录 count，顺序无关、内存有界。对相同冻结基准比较三项及 mappings/settings；这是全量内容指纹核验，不将它写成逐字节人工比对或现网验收结论。扫描按 `--batch-size` 分页，默认 5 条，大文章或内存紧张时建议传 1；备份和目标 reindex 同样显式传入 `source.size=batch_size`。该参数控制文档条数，不限制响应字节或单篇文档内存占用，不能保证消除 MemoryError；减小批量会增加请求开销，仍须完成全量校验。任一批次/分片失败均拒绝切换。修改批量参数不接管、不清理、不续跑旧失败 run。

恢复规则：

- 复制/验证失败：源仍在，保留源写保护和所有副本/任务；确认任务停止并核实源完好后，运维可按记录恢复源原有写入设置，再恢复应用。没有完成核验的副本不能当作恢复依据。
- 切换结果不明：先 GET alias、UUID 与元数据确定当前指向；不自动解除任一候选写保护，不重复删除源，不宣告成功。
- 已切换但尚未恢复写入：保持全部写入方停止，把业务/关联 alias 切回已核验的恢复副本或仍存在的原实体，确认唯一可写目标后恢复；原具体索引已移除时，恢复方式是把业务 alias 指向恢复副本，不谎称原实体仍在。
- 已恢复写入：旧恢复副本已落后，不能直接换回。再次停写/排空并对当前权威目标做屏障和刷新，以其完整数据重新迁移到所需恢复目标并核验；没有完成这一步保持维护。
- 备份、失败目标和任务状态不自动清理。单次失败后的新 apply 需要运维先审计并解除原 run 的执行资格：保存/验证独立恢复资料，按明确路径归档或处理占用的固定恢复名，再重新 dry-run；脚本不自动删除该副本或抢占旧 run。

### 4.8 模块职责

| 修改/新增位置 | 职责 | 不承担 |
| --- | --- | --- |
| `common/services/metric_log.py`、`core/config/settings.py` | 新域开关与配置模型 | 用户/消息去重、业务结果判定 |
| `eplus/domain/schemas/metric.py` | 无正文的终态快照 | 持久统计 |
| `eplus/domain/repositories/eplus_repository.py` | 从已处理业务行构造终态快照 | 直接输出日志、额外写统计表 |
| admission/scheduler Services | 提交后通知输出器，保持原业务返回合同 | 直接 ORM 查询、重放业务 |
| `eplus/infrastructure/metric_events.py`、worker/client/supervisor | 脱敏、事件字段和正式入口接线，连接事件 | Redis 聚合、新身份系统 |
| `channel/domain/es/article_index.py` | 共用新建 settings 构造 | 应用启动迁移 |
| `scripts/repartition_channel_articles.py` 与同目录 helper | 维护编排、复制、核验与报告；单文件接近 600 行前按职责拆分 | HTTP API、定时自动运维 |

## 5. 已知坑与处理落点

| 事实 | 忽略的后果 | 处理位置 |
| --- | --- | --- |
| 回复 FINISHED 可是“无权限/超时”等提示 | 把失败提示当成功回答 | 终态快照按业务状态、turn_id 与 reply_status 联合分类 |
| 超时和恢复路径不经过正常回答出口 | 漏记失败、成功率偏高 | scheduler 的超时/恢复提交后观察 |
| transaction 内打日志早于 commit | 回滚也被计成功 | Service 事务外输出 |
| 进程崩溃没有可靠最后日志 | 永久保留已断线连接、或伪造完整业务账本 | connection 存活过期、终态尽力语义 |
| 默认连接正常初始化与懒加载兜底的 ES 来源不同 | 脚本复制错实例 | 完整 initialize_app_context；双 ES 配置的定向测试 |
| write block 不等同 refresh | 已确认写入不进入复制视图 | add_block 成功后源 refresh，关闭自动刷新场景验证 |
| reindex 不复制 mappings/settings，且 ingest 可再次改写内容 | 分析器变化、内容被二次转换 | 脚本预建/核验实体、复制阶段关闭 pipeline |
| aliases 请求可能有逐动作错误，remove_index 是删除实体 | 半成功被误报成功或误删唯一源 | 独立恢复副本、关系后验核验、结果不明保持维护 |
| alias 可能有 filter/routing，脚本创建索引会匹配模板 | 少迁数据、改变查询语义 | 从具体实体复制全量，保存/恢复 alias 元数据，核查模板注入 |

## 6. 对外合同与依赖

### 6.1 本功能提供

| 合同 | 调用方/消费方 | 兼容性 |
| --- | --- | --- |
| 两个新增指标域及本节字段 | 外部日志采集与监控 | 只追加，不更名或重释现有域 |
| `get_article_index_settings()` / 频道文章配置 | 同步/异步文章索引创建、运维脚本 | 缺省 3；现有实体不自动变化 |
| CLI / phase 与退出码 | 运维手动执行 | 0=完成/无需迁移/只读计划，2=参数/前置条件失败，3=复制失败，4=校验失败，5=切换结果不明，6=需要人工恢复 |
| 终态快照观察接口 | 正式 E+ Service/worker | 只读快照、默认空回调；既有业务结果不变 |

无新增 HTTP API、关系库表或错误码。日志字段新增合同确认后同步到 `docs/observability/metric-log-contract.md`；迁移帮助与示例同步脚本 README。字段以本文与代码共同维护；实际输出及迁移验证证据见 validation.md。

### 6.2 外部依赖

| 依赖 | 调用/用途 | 风险 |
| --- | --- | --- |
| F073 消息唯一键、turn/reply 状态与既有恢复 | Service/Repository 内部调用 | 新状态和终态入口需更新分类，不能仅看 FINISHED |
| 现有 `emit_metric`、F042 配置 | 指标日志 | 新域忘记注册将绕过 E+ 子开关 |
| Worker 与配置的租户上下文 | 正式入口 | 不允许从日志参数选业务身份 |
| 当前 ES 8.x 客户端与对应服务 API | 写屏障、refresh、reindex、scroll、aliases | 实际服务版本需在演练记录，不把官方 8.19 文档当已部署版本 |
| `config`、共享 Settings、app context | 运维脚本 | 配置/初始化不同会连接错误 ES；连接清理必须 finally |
| 日志采集管线 | 外部监控解析与去重 | 丢失/延迟是尽力指标边界，不等于业务审计 |

不新增系统二进制或第三方 Python 依赖。

## 7. 测试与可观测

1. 单元/契约：两个域开关和脱敏稳定性；仅终态、失败提示、拒绝、重复、事务回滚、超时/恢复；多用户多机器人去重字段；连接正常/异常退出、租约失效、心跳过期与乱序；分片默认/自定义/非法、同步异步共用配置；脚本 dry-run 零写入与每阶段失败禁止切换。
2. 真实 ES 8.x：用临时测试实体和生产相同客户端演练具体索引与已有别名；关闭源自动刷新，停写前新增/更新/删除立即迁移；custom routing、分析器、filter alias、pipeline 和模板；校验完整 `_source` 指纹与恢复副本；停写后查询及恢复后的写/改/删。中断复制与切换超时分别验证恢复；记录实际版本、容量与耗时，不推断生产耗时。
3. E+ 集成：真实两 Worker 验证租约转移、同用户跨节点标识一致、同消息重复投递、完整回答/失败/拒绝；按指定窗口只消费终态验证成功率与人数。需要客户 E+ 协议端点与租户账号；本地仅验证隔离 WebSocket/租约模拟及 SQLite；未连接客户 E+ 端点，不记录凭据。
4. MySQL/DM8：不新增 schema 或方言 SQL；新增 Repository 查询使用 SQLModel。真实双 DB 运行证据依赖中央环境，未执行不得标通过。按项目要求在实现阶段运行 e2e 与最终代码评审。

已交付命令（以下为使用示例，非生产执行记录）：

```bash
cd src/backend
export config=config.yaml
python scripts/repartition_channel_articles.py --batch-size 1
python scripts/repartition_channel_articles.py --apply --writers-paused --run-id maintenance-20261027 --batch-size 1
python scripts/repartition_channel_articles.py --status --run-id maintenance-20261027
```

本地后续验证入口：`uv run pytest test/metric_log/ test/eplus/` 与新增的 `test/channel/test_article_index_settings.py`、`test/channel/test_repartition_channel_articles.py`；执行范围与结果记录在 validation.md。

## 8. 后续边界

不做实时用户/在途聚合、可靠日志 outbox、自动迁移或自动抢占/恢复任务。固定恢复副本占用后的处理交给明确维护流程，避免把一次手动运维脚本扩展为分布式迁移平台。需要在线无损迁移、自动续跑或跨集群恢复时重新评审合同；同集群恢复副本不等同于灾备快照。

## 修订记录

| 日期 | 内容 | 原因 |
| --- | --- | --- |
| 2026-10-27 | Design 初稿，已核对当前调用链和官方 ES API；未实现 | 用户确认 Spec 后要求继续 |
| 2026-10-27 | 完成实现与自审：事务内快照缓冲/提交后通知、LEFT JOIN 保留原缺失行语义、正式 Worker 可选连接观察器、安全索引名与 COPY_PENDING 恢复标记；隔离 ES 8.12.2 演练与回归记录另附 | 用户确认 Design 后继续实现；同步最终调用与恢复合同 |
