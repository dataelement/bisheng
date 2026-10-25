# 审计启用与回退说明

> work-110 部署先读 [work110-port.md](./work110-port.md) §3.2：本分支迁移头为 `f062_work110_audit_tree`，下文来源迁移名称仅为历史记录；已有来源审计链的数据库不得直接切换到本分支镜像。

## 2026-10-19 会话目录升级（尚未在业务环境执行）

1. 隔离副本预估DDL锁影响，正常Alembic升级唯一头dsh_audit_groups（前序dsh_audit_sources）；模型发现/create_all创建dsh_model_audit_conversation。create_all不能替代旧表加列迁移。
2. 升级全部API、消费者、巡检/Beat，不改变模式、密钥或正文；旧写入进程可能继续产生NULL状态，必须全部升级再回填。
3. 在src/backend逐租户预览：`python scripts/backfill_dsh_audit_presentation.py --tenant-id <ID>`。确认后加`--apply --batch-size 200 --max-batches 20`；按输出after_request_id用`--after-request-id`续跑，最后从头复核至examined=0。只补状态/缺失摘要和投影标记；若已有status却缺摘要，仍需原名称回填脚本。
4. 巡检复用租户header和独立事务投影，失败留pending重试；query-readiness的status_ready/name_ready就绪后开放对应筛选，indexing_pending提示延迟，不表示全覆盖。
5. 核对目录、未关联请求、同一请求条件、双层分页、查看全部/返回与原文留痕；新UI只传完整名称，旧model_id仅兼容，下文按ID选择的旧口径已替代。
6. 正式JWT/DM8/真实容量和SQL计划待验收。回退保留新表/列/记录及密钥，旧程序回退后产生NULL状态须重升后再回填，不删除对象或业务数据。

日期：2026-10-14。仅交付运行步骤，本轮没有部署/启用业务租户。正式启用前先完成[验证记录](./validation-results.md)的环境门禁。

## 启用前

### 模型查询索引升级（dsh_audit_model_lookup）

发布包含本次修改的镜像时，先执行正常 Alembic DDL 迁移，增加可空 `model_name_digest` 和两条模型查询联合索引；迁移不回填数据。所有 API/消费者均切到新版本后，按实际租户运行 `scripts/backfill_dsh_audit_model_names.py --tenant-id <ID>` 预览，再带 `--apply --batch-size 200 --max-batches 20` 分批补齐旧摘要。可用输出的 `after_request_id` 续跑；最终从头重跑至 `examined=0`，逐租户确认。脚本仅补 NULL 摘要，不改模型名称或原文。旧数据补齐前名称精确查询会漏掉未补记录，不启用大表扫描兜底；按模型 ID 查询不依赖回填。DDL 建索引的耗时及锁影响需在目标 MySQL/DM8 环境预估，不能宣称无锁。此次候选接口返回 `{id,name}`，API 与前端需协调同批发布，禁止混用旧版字符串候选响应。

### 通用启用检查

1. 发布线同步及质量门禁处置；在实际 MySQL/DM8 环境确认八张表/索引、租户 hook 导入、API 和 Celery/Beat 同版本。新表沿既有 model discovery/create_all 创建，不回填存量租户模式。若已运行早期原型，create_all 不会自动补列/改精度，须先审查并执行独立差异迁移，不能删业务表解决。
2. 所有新/旧租户仍默认 OFF。仅全局超管在客户端管理→模型审计选择租户，切 METADATA 或 CONTENT；操作附 `operation_id/expected_version`，模式与留痕同事务。租户管理员只读；受限管理上下文不会自动取得全局操作权。
3. CONTENT 前明确数据/安全责任方、持续存储容量、访问日志、私有 bucket 策略、报警、备份与恢复责任；本期**没有到期删除或孤儿对象自动 GC**。部分写入失败可留下无引用加密对象，不得贸然全局删除。
4. 所有 API 与原文读取进程配置相同外部 `BS_DSH_MODEL_AUDIT_KEYS`（JSON：版本引用→base64 编码 32-byte AES key），`dsh.audit_active_key_id` 指定活动版本。密钥通过已有安全 secret 管理注入，不能写源码、命令历史、普通 YAML/日志，也不复用 License/HMAC 密钥。管理接口在开启 CONTENT 前实时校验当前实例的活动密钥，缺失/无效返回 26135、不写配置；页面禁用正文选项并提示原因。已开启后密钥失效时不自动改模式，打开/刷新显示异常，CONTENT 只能尽力保留不完整元数据、不回退明文、不阻断模型。`content_available` 仅反映处理配置请求的实例，不证明 MinIO、历史密钥或其他实例就绪；启用前仍须分别核验所有采集/读取实例的密钥与共享存储，不能用负载均衡后一次预检代替集群核验。
5. 密钥版本不可原地替换材料；新请求固定新版本，旧版本保留给历史读取。备份 SQL、MinIO 对象及对应所有历史密钥；缺任一部分均不能承诺恢复。先在合成样本演练后再切生产模式。

## 运行边界与观测

默认块 16 KiB、每请求正文预算 16 MiB、全局正文队列 64 MiB/4096 events；证据队列独立、最多 4 MiB；模式读取超时 0.1s→OFF，单次存储超时 5s、最多 3 次尝试、有限关闭 5s。活动刷新 10s、观察窗口 300s、Beat 扫描 60s（audit_state_scan_interval_seconds 可调）；每次租户/请求扫描最多 100。全部是可调运维默认值，不是性能 SLA。

阻塞 I/O 独立 4 线程、最多 12 个实际提交工作，超时不能强杀底层线程，但不提前释放容量，也不耗尽主业务默认线程池。监控现有 BS_METRIC domain=dsh_model_audit 的 mode_read_failed、buffer_rejected、capture_incomplete、written、write_exhausted，以及安全的类型级存储/活动/访问异常。指标不含正文、token、会话 ID。

写入完整仅表示实际观察的输入/输出及终止清单校验通过；不保证供应商收到、客户端收到或全量覆盖。完全失写仍可能没有逐条可查证据。进度的 pending_events=null 是跨进程缓冲全量未知，不等于零；本页水位不能作为总体覆盖率。原文读取先 durable attempt 再流式返回，日志失败拒绝出正文。

原文编码-v1 历史读取最大块固定 64 KiB，不随新写块调小而失效；NDJSON 帧解析预算 256 KiB。页面每段最多 100 frames，当前只在单次展开组件内保留原文，收起清除；默认服务端 16 MiB 正文预算小于页面 20 Mi-character 显示预算。若调高单请求预算，需要同时评估浏览器内存/显示上限，不能承诺任意大正文都能直接完整渲染。

多节点采用共享 SQL/Redis/MinIO，不能把进程缓冲当恢复来源；统一 UTC 和时钟同步，服务端开始时间排序不等同于并行请求的客户端因果顺序。本期不做源消息身份或气泡复刻。

## 回退

1. 超管将受影响租户设 OFF；只影响新开始请求，不追溯抹除历史，不改变在途快照。
2. 按既有服务生命周期停止 API/消费者，有限 drain 后允许未持久缓冲丢失。停止新增审计 Beat；不停止原用量/额度/席位账本任务。回退应用时确认旧代码不会解释新表为业务主账本。
3. 保留所有审计表、加密对象、查看/模式历史及对应密钥，不做 DROP/TRUNCATE/bucket 清空。OFF 不会关闭已有历史的管理员读取授权；回退至不含读取代码的版本可能暂时无法在 UI 查看，但原件保留。
4. 恢复到含审计的版本后重新核验样本、权限、完整性与历史密钥；未通过前保持 OFF。读模式失败会按 OFF 降级并尽力告警，不以旧 CONTENT 缓存继续采集。

隔离 PoC 由 `python -m test.dsh.audit_local_server --real-stores` 启动，退出只删除其唯一命名的本机测试容器/卷。数据是可重新生成的合成数据，不是历史业务审计的回退方式。
