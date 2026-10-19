# 中粮生产从0920升级到909r1

适用路径：`v3.0.0-cofco-0920` → `v3.0.0-cofco-909r1`。目标提交为 `2113fc2108af5921cd3e170f798c86ce40684886`，源提交为 `f6c82c2ffd5eabf19d505a28ac43c99be3e35a1d`。

这次是同一条909定制线的正向升级，**不需要先降级，也不能只替换镜像**。需要备份、停止业务进程、升级表结构、显式发布权限模型、更新前后端及所有Worker，再启用E+机器人。本文按此前客户环境的K8s、ARM64、DM8编排；生产实际配置、部署名称和副本数必须先核对。

## 1 上线前必须准备

| 准备项 | 要求 |
| --- | --- |
| 新后端镜像 | `dataelement/bisheng-backend:v3.0.0-cofco-909r1-arm64`，在线源加 `cr.dataelem.com/` |
| 新前端镜像 | `dataelement/bisheng-frontend:v3.0.0-cofco-909r1-arm64`，不能继续用0920或909h6前端 |
| 离线包和校验文件 | 必须是909r1，检查SHA256、包内标签和实际`linux/arm64`；此前已下载的909h6包不是本次目标 |
| 旧版本镜像 | 保留生产正在使用的0920前后端镜像、digest，以及原Deployment/ConfigMap/Ingress清单 |
| 数据库备份 | 完整业务DM库，以及OpenFGA实际使用的数据库；在停写后取得同一维护窗口的恢复点，备份复制到Pod以外并核验可恢复 |
| 其他数据 | 保留MinIO文件、Redis持久数据/队列与配置；沿用现有Milvus、ES数据，不清库、不重建索引 |
| 配置备份 | API和所有Worker的env/envFrom、配置挂载、Secret引用、资源限制、探针、启动脚本及原副本数；含网关/IAM配置，按敏感资料保存 |
| 维护权限 | Kubernetes操作权限、DBA备份恢复能力，以及权限发布审计使用的真实管理员用户ID |
| E+参数 | 生产机器人ID、Secret、WebSocket地址、绑定助手/空间、是否需要CA；不能照搬测试机器人的密钥 |
| 模型和OCR | 助手模型、自动生成助手信息所用模型、嵌入模型均可用；图片OCR配置和服务可达 |
| 停机窗口 | 禁止新会话/上传，排空在途任务；权限发布期间API、全部Worker和调试服务都不能运行，防止旧新版本混跑 |

**没有可恢复的业务库和OpenFGA备份，不进入生产写操作。** 不能用“镜像可以回滚”代替数据恢复准备。

## 2 这次到底迁移什么

### 2.1 数据库表结构

0920代码的唯一迁移头是 `f059_merge_cofco_909_f058_heads`；909r1代码的唯一迁移头是 `f061_merge_cofco_909_f066_heads`。

正常0920库执行目标镜像的`alembic upgrade head`会按迁移图补齐以下4条revision，不需要手动逐条执行：

| Revision | 变化 |
| --- | --- |
| `f053_pat_default_ttl_365` | 将`open_api_tenant_setting.pat_ttl_days`数据库默认值改为365；不修改已存在的租户选择和已签发密钥过期时间 |
| `f066_pat_data_scope` | 给`open_api_tenant_setting`增加非空`pat_data_scope`，默认`all_visible`；已有行由DDL默认值填充，不主动收窄已有可见范围 |
| `f060_merge_cofco_909_f053_ttl_heads` | 合并迁移分支，无业务DDL |
| `f061_merge_cofco_909_f066_heads` | 合并迁移分支，无业务DDL |

此外，在线Alembic upgrade会加载当前ORM模型并通过`create_all(checkfirst=True)`创建缺失的新表：

- `eplus_bot_config`：机器人配置和连接状态。
- `eplus_bot_space`：机器人绑定的知识空间。
- `eplus_inbound_message`：入站消息去重和处理状态。
- `eplus_conversation`：机器人与单聊/群聊的会话映射。
- `eplus_turn`：问答轮次、历史和图片解析结果。

这些是整表创建，不是额外5条Alembic revision。`create_all`不会给**已存在**的表补列；若生产曾热装过机器人功能，必须比对已有E+表与909r1模型，不能认为“表已存在”就通过。

本次新增迁移没有删除、重建或清空`llm_server`、`llm_model`、用户、知识文件和普通助手历史。模型服务商的真实表名是`llm_server`，不要按口头的“server表”修改数据库。文件和索引不要求重新解析或导入。

**停止条件：**实际库版本不是预期0920基线，出现未知revision、923的`f068_knowledge_chat_entry`或额外迁移头，先报告偏差，不执行downgrade/stamp，不删除`entry_flow_id`，不在生产临时生成merge revision。

### 2.2 权限模型和存量标记

0920代码要求 `f048-v4-contextual-departments`，909r1要求 `f048-v5`。同一OpenFGA Store中需要发布/复用新模型、更新SQL CURRENT Catalog绑定，并补齐已有资源的`service_account:*`技术状态标记。

使用目标镜像内已有脚本：

```text
/app/scripts/publish_authorization_model_change.py
```

它不改业务Grant、用户或服务账号，不替客户重新授权；会保持原继承/自定义权限边界。**这是手动维护步骤，API启动、Alembic升级和换镜像都不会代跑。** 即使输出`already_current`，也要完成apply的标记补齐与校验。

已有F048环境不要重新跑`migrate_f048_permission_data.py`。只有已发现Grant可见投影不完整时，才另行评估`reconcile_f048_visible_projection.py`；正常0920升级不默认运行完整对账或孤儿tuple清理。

### 2.3 服务和配置

- API和已有Celery/Beat/Linsight全部换909r1后端镜像；前端换909r1前端镜像。无需更换DB、Redis、MinIO、Milvus、ES和OpenFGA服务镜像。
- 新增独立`backend-worker-eplus` Deployment，使用同一后端镜像，启动命令为`sh /app/entrypoint.sh eplus`。它不是Celery任务模式Worker。
- 若`/app/entrypoint.sh`由ConfigMap覆盖，必须更新挂载内容，支持`eplus`；镜像更新不会覆盖ConfigMap里的旧脚本。本说明配套目录提供909r1原始脚本。
- 复用真实后端的数据库、Redis、MinIO、ES、Milvus和模型配置，以及必要的网关/IAM设置。不要复制仓库Compose中的示例地址或示例密钥到生产。
- E+ Worker和API需要能够访问相同MinIO对象；不能靠某个Pod本地目录共享图片或证书。图片下载、解密、OCR在E+处理链内执行，OCR依赖现有文档解析服务配置。
- 不自动部署机器人调试服务。其前端入口默认编译开启，但后端需要独立显式启用；生产未批准时不开放`/robot-debug/api/`代理。启用后同租户所有登录用户可以问机器人绑定空间，且诊断日志会记录问题和检索正文。
- 如果已有临时Python ConfigMap补丁，逐个备份和比对后去掉覆盖909r1源码的挂载；保留正常`config.yaml`和已核对的`entrypoint.sh`挂载。不要直接清空所有volumeMounts。

## 3 推荐升级顺序

### 第一步 只读预检和镜像预载

1. 核对生产namespace、节点架构、实际镜像digest、Deployment副本数、Job/CronJob/HPA/GitOps控制器、ConfigMap和卷挂载；确认没有其他节点/进程使用同一个权限Store。
2. 用生产现有镜像查询当前数据库revision；用**909r1目标镜像的独立维护Job**检查`alembic heads`，不要运行默认API entrypoint。
3. 检查模型服务商记录和模型关联、权限CURRENT Catalog、在途权限操作，保存只读报告。SQL见配套`preflight.sql`；其他表计数用DBA现有工具补充。
4. 提前拉取或导入909r1镜像至所有可能调度节点的K8s runtime。Docker镜像缓存不等于K8s containerd缓存。
5. 预备旧镜像和原清单，验证备份恢复方案；记录审批人及执行管理员ID。

离线校验和containerd导入示例，文件名、socket、runtime以现场为准：

```bash
sha256sum -c bisheng-v3.0.0-cofco-909r1-arm64.tar.gz.sha256
gzip -dc bisheng-v3.0.0-cofco-909r1-arm64.tar.gz | ctr -n k8s.io images import -
ctr -n k8s.io images ls
```

`ctr`必须连接K8s实际使用的containerd。若使用k3s、其他socket或其他CRI，换用现场对应工具。不能在没有`ctr`时临时启动一个不相关Docker容器并认为镜像已导入成功。

对已离线导入的精确镜像引用使用`IfNotPresent`；核对清单中的仓库前缀与包内RepoTag一致。只在一个节点导入时，将维护Job和新Pod限制在已导入节点，否则仍会拉取失败。

### 第二步 停写及可恢复备份

1. 入口置维护状态，拒绝新会话/上传/管理写操作；停止Beat新增投递、暂停相关CronJob/自动扩缩容，按现场机制暂停外部IAM等写入方。
2. 等现有问答、上传解析、工作流/任务和权限投影结束。不要通过清空Redis队列实现排空。
3. 保存真实副本数后，停API、所有Celery/Beat/Linsight、已有E+和调试进程；确认其他节点/独立进程也停止。数据库、OpenFGA及其存储、Redis、MinIO、Milvus、ES保持运行。
4. 取得停写后的业务库与OpenFGA数据库备份，核验并存到Pod外。保留配置和所需对象/队列恢复点；核对没有新业务写入。
5. 等待F048运行时心跳消失。默认心跳TTL为45秒；最终以脚本的心跳门禁为准，不手工删除heartbeat键。若被阻断，查找仍活跃的API/Worker/调试进程。

不要先滚动上线909r1 API再做权限发布：旧进程会持有旧模型，维护脚本也会因活跃心跳拒绝执行。

### 第三步 独立Job升级数据库

维护Job使用909r1后端镜像，复用API实际env/envFrom、Secret引用、配置挂载、网络和运行身份；**不启动uvicorn、不启动任何Worker**。Job不要继承API Service用于选Pod的业务label，避免被接入请求流量。

以下是只读预检Job的执行内容，不是可直接apply的完整清单；`config`应沿用现场有效配置路径：

```bash
cd /app
export PYTHONPATH=./
export config=/app/bisheng/config.yaml
.venv/bin/alembic current
.venv/bin/alembic heads
```

核对当前revision与目标唯一head，批准后另一个独立迁移Job才执行：

```bash
cd /app
export PYTHONPATH=./
export config=/app/bisheng/config.yaml
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

Job的shell使用`sh -ec`，任一步失败立即停止；先核对前两项输出再批准upgrade，不能把未知基线直接送入升级。只允许一个Job执行DDL，其他API副本继续为0。

完成要求：

- `alembic current`仅为`f061_merge_cofco_909_f066_heads`。
- 5张E+新表存在，字段/索引与目标模型一致。
- `open_api_tenant_setting.pat_data_scope`存在，默认`all_visible`；`pat_ttl_days`默认365，已有配置未被改写。
- 模型服务商、模型、助手、文件及权限业务记录的计数和关键关联未出现非预期变化。

DM8的DDL会自动提交，失败不能视为“整轮已回滚”。保留日志、确认已执行到哪里、处理原因后重新走可恢复正向升级；不删除revision记录强行跳过。

### 第四步 手动发布权限模型

仍在独立维护Job里、使用同一配置，先dry-run：

```bash
cd /app
export PYTHONPATH=./
export config=/app/bisheng/config.yaml
.venv/bin/python scripts/publish_authorization_model_change.py
```

确认报告中的`store_id`是生产原Store，`model_version`为`f048-v5`，以及`target_model_checksum`、`current_catalog_id`、`needs_catalog_cutover`、`service_account_marker_tuple_count`。marker数量是应有数量，不是缺失数量。若SQL CURRENT模型与OpenFGA校验不符，停止，不能新建Store替代。

人工审阅该次dry-run后，用其实际输出执行：

```bash
.venv/bin/python scripts/publish_authorization_model_change.py \
  --apply \
  --confirm-store-id <本次dry-run的store_id> \
  --confirm-target-model-checksum <本次dry-run的target_model_checksum> \
  --operator-id <真实管理员用户ID>
```

不能硬编码测试环境Store ID/checksum。退出码0且有`authorization_model_change_published`或`already_current`成功事件，并有`service_account_marker_tuples_verified`，才可继续。

退出码3是门禁阻断，4是执行错误。出现活跃心跳、在途权限操作、Catalog写栅栏、持久化`department.subtree_member`等阻断时，先定位并人工处理；不改脚本跳过条件、不随意删tuple。失败时保持停机；脚本按实际状态正向重试，不直接改SQL指针。执行耗时与资源数量及OpenFGA响应有关，不能以“没有即时输出”自行重复启动第二个apply。

完成后再次dry-run，确认目标checksum已成为CURRENT；SQL CURRENT Catalog唯一、所引用模型release ACTIVE、Store/model/checksum与OpenFGA匹配。表结构迁移与权限模型发布是两份独立成功证据。

### 第五步 更新启动配置与镜像

1. 备份原`backend-start-script`等真实启动ConfigMap，用配套909r1 entrypoint更新对应key；保留客户其他必要启动适配，逐项审阅差异。
2. 修改API、每个现有Worker及前端镜像为909r1精确引用；保持副本0。其他容器如网关/sidecar不跟着替换后端镜像。
3. 新建E+ Worker Deployment，基于已验证的default Worker模板只保留运行E+需要的资源、配置和挂载；镜像为909r1后端，命令`sh /app/entrypoint.sh eplus`。去掉Celery专用探针，重新设定适合独立长连接进程的探针，不拿不存在的HTTP `/health`探测它。
4. 生产首次E+上线先1个Worker，不开启HPA。支持多进程竞争机器人租约不代表需要一开始部署多副本；不能同时保留旧测试/探针连接订阅同一个生产Bot ID。
5. 不把临时诊断ConfigMap或测试debug override复制到生产。909r1已包含图片gzip处理、OCR配置读取、以及提前捕获连接peer的修复，无需再挂测试热补丁。

### 第六步 分阶段启动与验收

1. 先启动1个API，检查自动执行Alembic无新增失败、HTTP健康、权限运行时就绪及真实授权接口。**健康接口200不等于权限模型就绪。**
2. 启动普通业务Worker和前端，检查队列/错误日志；确认工作正常后按原副本数恢复，Beat/CronJob在任务处理端就绪后恢复。
3. 启动E+ Worker，助手页配置生产Bot、绑定空间并上线。只有机器人启用且助手上线才建立连接；保存草稿不应连。上线前核准群内分享绑定空间内容的业务授权。
4. 完成下节验收后再开放入口和外部写入。维护Job日志/清单、dry-run/apply结果、表结构和权限核验保存为上线证据。

## 4 E+和模型的配置检查

### 用户身份

网关从客户IAM读取人员，将原始`userid`原样推送到`external_user_id`，来源为`wecom`。机器人按这个外部ID找到未删除、在机器人所属租户有效的用户。不存在或不可用则回复“无权限使用”。

不需要重建用户、不修改已有user_id，也不能为绕过匹配问题批量创建管理员用户。核对网关推送、同步落库和E+消息中的`from.userid`三者一致。

### 助手和图片

- 一助手绑定一机器人，机器人可绑定多个空间；空间问答只用机器人绑定，不能按个人权限扩张；绑定空间内的单文件权限暂不参与过滤。群聊与单聊均适用。
- 模型和系统提示词沿用助手页面保存的配置；确认绑定模型的`llm_model.server_id`能找到`llm_server`，服务端模型名存在且凭据有效。
- 创建助手会使用后台自动生成名称/描述的模型，因此还要验证该系统模型，不能只验证机器人的问答模型。
- 当前图片走OCR/文字提取时，需要`knowledge.image_parser_enabled`及实际文档解析器可用；沿用客户已选的`loader_provider`和对应Paddle OCR/MinerU等配置，不将测试URL直接写入生产。
- 从E+ Worker Pod测试WebSocket DNS/TCP/TLS、图片下载目标、MinIO、OCR、模型和索引连通性。无需客户CA的公开可信TLS不上传证书，但不能关闭TLS验证。
- 返回E+仅文字流，不提供模型生成图片、富媒体或完整空间文件目录。首帧处理中、流式完成、同一消息不重跑均需现场验证。
- 每会话最多同时检索6个空间，不是全环境最多6个；并发会话会叠加索引/嵌入服务负载，需要看CPU、连接数、模型限流与首字延迟。

## 5 上线验收清单

| 类别 | 最低验收 |
| --- | --- |
| 数据 | 迁移头唯一正确，新表/列存在；模型、用户、助手、文件、Grant关键计数和关联未丢失 |
| 权限 | CURRENT Catalog及新模型绑定正确；普通用户可读已授权资源、不可读未授权资源，部门/子部门空间正常 |
| 老功能 | 登录、普通助手含历史、日常聊天、任务/工作流、知识检索、上传解析、下载和引用；创建助手不报模型404 |
| Open API | 已有密钥能按原授权调用；v2错误按实际HTTP状态处理，不能只判断HTTP200；PAT租户开关、现存期限和data scope保持 |
| 新问答API | 已批准时用生产独立测试密钥验证`POST /api/v2/filelib/answer`；旧`/filelib/retrieve`仍可用，不混淆纯检索与模型总结 |
| 匿名应用 | 如生产使用免登录链接，验证发布/上线状态、v3代理、guest开关、默认执行用户与其资源权限；不使用超管默认用户扩大访客可见范围 |
| E+文本 | 单聊、群聊@、连续追问、排队处理、非法用户“无权限使用”、下线上线、长连接重连 |
| E+图片 | 纯图片、图文混排、gzip下载/解密/OCR全链路、历史图片不重复解析；不能仅凭模型有文字回复判定OCR成功 |
| E+知识 | 跨绑定空间医学等已知文件、真实空间名/ID/文件归属、后续追问能召回正文、未绑定空间不可检索；答案不声称完整目录 |
| E+流式 | 初始等待提示、内容逐步更新、一次finish及ACK、完成后无后端二次执行；客户端重复打字按既有证据流程另行定位 |
| 运行 | 全部目标Pod使用909r1，无旧源码补丁覆盖、无CrashLoop、无权限checksum错误、无队列持续积压 |

不要在正式验收时用管理员身份代替所有普通用户权限测试。升级不自动开启PAT租户开关，也不自动改助手提示词；已有`initdb_config`的数据库配置以实际保存值为准，修改镜像里的初始化模板不能视为更新了生产配置。

## 6 失败处理和回退

- **只载入镜像、未迁移数据：**恢复原部署清单即可，原服务/数据尚未改变。
- **已做DDL或权限发布、尚未恢复业务写入：**优先修复原因并前滚；确需回0920，先保持所有业务停机，由DBA恢复同一升级前恢复点的业务库和OpenFGA数据库，恢复原配置和旧镜像，再验证旧版Catalog/模型/checksum一致。Redis状态按同一恢复方案处理，不执行全局flush。
- **已恢复生产写入：**不能直接覆盖为升级前备份，会丢失新数据；重新停写、备份当前状态，评估增量恢复或前滚修复，经业务负责人确认后执行。

**不提供一键downgrade作为生产回退方案。** Alembic downgrade不恢复权限发布和OpenFGA模型状态；只换回旧镜像或只恢复业务库，仍可能因Store最新模型与旧版期望checksum不一致导致权限不可用。

不删除模型服务商记录、不清理机器人历史、不跑PAT批量TTL修改，不执行历史遗留公共tuple清理。`clear_eplus_history.py`是按需维护工具，不是升级必跑脚本。

## 7 配套文件及依据

配套目录：[cofco-0920-to-909r1](upgrades/cofco-0920-to-909r1/)。对外离线包将本说明复制为`UPGRADE.md`；仓库只维护本说明这一份正文。

- `AGENT_PROMPT.md`：给客户Agent的预检、停止条件和经批准后的执行指引。
- `preflight.sql`：只读数据库基线和模型/权限关联检查；不含凭据正文。
- `entrypoint.sh`：909r1原始启动脚本，含eplus模式；替换客户ConfigMap前审阅。
- 离线包中的`SHA256SUMS`：配套文件校验，**不是镜像包校验**。

权限数据维护脚本直接使用909r1镜像内已有版本，不另复制旧脚本。原始依据：0920与909r1 Git树差异、4条新增Alembic revision、E+ ORM模型、[权限维护脚本说明](../src/backend/scripts/README.md)、[F053发布说明](../features/v3.0.0-beta1/053-openapi-auth-and-identity/release-and-deployment.md)、[机器人设计](../features/v3.0.0-beta1/073-eplus-robot-assistant/design.md)、[机器人调试边界](cofco-robot-debug-client.md)。

生产是否存在额外迁移、权限数据缺口或热补丁，以上线预检为准。本说明和配套SQL未对客户生产执行；不代表生产迁移演练已通过。Git迁移图已核对，真实DM8/OpenFGA执行须先用恢复副本完成演练。
