# 部署与运维

BiSheng 采用 Docker Compose 编排全部基础设施和应用服务。生产环境通过 `docker/docker-compose.yml` 一键拉起 9 个容器，覆盖数据库、缓存、向量存储、全文检索、对象存储、后端 API、异步 Worker 和前端。本地开发时可选择混合部署模式：存储层保留 Docker 容器运行，后端和前端从源码启动，避免每次代码变更都要重建镜像。配置系统支持多层合并（YAML 文件、环境变量、数据库配置、Redis 缓存），密码字段通过 Fernet 加密保护。

## 容器清单

`docker/docker-compose.yml` 定义了以下 9 个服务：

| 容器名 | 镜像 | 端口映射 | 职责 |
|--------|------|---------|------|
| `bisheng-mysql` | `mysql:8.0` | 3306:3306 | 关系型数据存储，默认密码 `1234`，数据库 `bisheng` |
| `bisheng-redis` | `redis:7.0.4` | 6379:6379 | 缓存、Celery Broker、会话存储 |
| `bisheng-backend` | `dataelement/bisheng-backend:v2.4.0` | 7860:7860 | FastAPI 后端 API，通过 `entrypoint.sh api` 启动 |
| `bisheng-backend-worker` | `dataelement/bisheng-backend:v2.4.0` | (无) | Celery 全部 Worker + Beat，通过 `entrypoint.sh worker` 启动 |
| `bisheng-frontend` | `dataelement/bisheng-frontend:v2.4.0` | 3001:3001 | Nginx 托管前端静态资源 |
| `bisheng-milvus-etcd` | `quay.io/coreos/etcd:v3.5.5` | (无) | Milvus 元数据存储（ETCD） |
| `bisheng-milvus-minio` | `minio/minio:RELEASE.2023-03-20T20-16-18Z` | 9100:9000, 9101:9001 | Milvus 数据存储（MinIO），同时作为业务对象存储 |
| `bisheng-milvus-standalone` | `milvusdb/milvus:v2.5.10` | 19530:19530, 9091:9091 | 向量数据库，依赖 ETCD 和 MinIO |
| `bisheng-es` | `bitnamilegacy/elasticsearch:8.12.0` | 9200:9200, 9300:9300 | 全文检索引擎 |

### 服务依赖关系

```
bisheng-backend
  ├── depends_on: mysql (healthy)
  └── depends_on: redis (healthy)

bisheng-backend-worker
  ├── depends_on: mysql (healthy)
  └── depends_on: redis (healthy)

bisheng-frontend
  └── depends_on: backend

bisheng-milvus-standalone
  ├── depends_on: etcd
  └── depends_on: minio
```

### 附加 Compose 文件

除主编排文件外，项目还提供三个可选编排文件，按需独立启动：

| 文件 | 容器名 | 镜像 | 端口 | 用途 |
|------|--------|------|------|------|
| `docker-compose-ft.yml` | `bisheng-ft-server` | `dataelement/bisheng-ft:v0.5.0` | 8000 | 模型微调服务，需要 GPU（nvidia driver） |
| `docker-compose-uns.yml` | `bisheng-unstructured` | `dataelement/bisheng-unstructured:v0.0.3.14` | 10001 | 非结构化文档解析服务 |
| `docker-compose-office.yml` | `bisheng-office` | `onlyoffice/documentserver:7.1.1` | 8701:80 | OnlyOffice 文档预览与编辑 |

## 配置系统

配置的加载与合并遵循多层优先级机制，最终生成运行时 `Settings` 对象。

```
                                  优先级（高→低）
                                  ─────────────
┌─────────────────┐
│  config.yaml    │  ← 基础配置文件（文件路径由环境变量 config 指定，默认 config.yaml）
│                 │     支持 !env ${VAR} 语法从环境变量注入值
└────────┬────────┘
         │ 加载
         v
┌─────────────────┐
│  BS_* 环境变量   │  ← Docker 环境变量覆盖，如 BS_MILVUS_CONNECTION_ARGS、BS_MINIO_ENDPOINT 等
│                 │     在 docker-compose.yml 的 environment 中设置
└────────┬────────┘
         │ 合并
         v
┌─────────────────┐
│  数据库配置      │  ← MySQL 中 initdb_config 记录，通过 Web 界面修改的运行时配置
│  (initdb_config)│     首次启动时从 initdb_config.yaml 初始化写入数据库
└────────┬────────┘
         │ 合并
         v
┌─────────────────┐
│  Redis 缓存     │  ← 配置读取结果缓存在 Redis 中，TTL 100 秒
│  (100s TTL)     │     避免每次请求都查询数据库
└─────────────────┘
```

### 代码节点开关

工作流「代码节点」默认关闭，由系统配置控制：

```yaml
workflow:
  code_node_enabled: false
```

该节点会执行用户填写的 Python 代码，当前版本**没有执行沙箱**，代码以后端进程的权限运行，可读取服务器文件、环境变量（含数据库与对象存储凭证）并访问内网。因此开启后，**所有能创建或编辑工作流的用户都等同于持有这台服务器的命令执行权限**——这与其在毕昇中的角色无关，也与是否部署在内网无关。仅在「所有能创建应用的人都可信」的环境下开启。

只有字面量 `true` 视为开启；写成 `"true"`、`1`、`yes` 一律按关闭处理。改动约 100 秒生效，无需重启。

关闭状态下运行到该节点的工作流会失败，失败原因中会指明需开启的配置项；编排页的代码节点上也有常驻提示。

> **升级注意**：存量工作流中的代码节点在管理员开启前不可运行。升级前可用以下语句评估影响面：
>
> ```sql
> SELECT COUNT(*) FROM flow WHERE data LIKE '%"type": "code"%';
> ```

执行沙箱正在开发中，届时本开关将不再是唯一防线。

### 密码加密

`config.yaml` 中的 `database_url` 和 `redis_url` 密码字段使用 Fernet 对称加密。加密密钥硬编码在 `src/backend/bisheng/core/config/settings.py` 的 `secret_key` 变量中。Settings 类在加载配置时自动解密：

- `database_url`：正则匹配 `:password@` 中的密码部分，调用 `decrypt_token()` 解密
- `redis_url`：支持字符串 URL 和字典两种格式，字典格式使用 `encrypt(...)` 包装标记加密值

### Settings 类主要字段

`Settings` 类定义在 `src/backend/bisheng/core/config/settings.py`，主要配置分组：

| 字段 | 类型 | 说明 |
|------|------|------|
| `database_url` | `str` | MySQL 连接字符串（密码加密） |
| `redis_url` | `str/dict` | Redis 连接配置 |
| `celery_redis_url` | `str/dict` | Celery Broker Redis 连接 |
| `vector_stores` | `VectorStores` | Milvus + Elasticsearch 配置 |
| `object_storage` | `ObjectStore` | MinIO 对象存储配置 |
| `celery_task` | `CeleryConf` | Celery 任务路由和定时任务 |
| `workflow_conf` | `WorkflowConf` | 工作流执行参数（max_steps=50, timeout=720min） |
| `linsight_conf` | `LinsightConf` | 灵思 Agent 参数（max_steps=200, retry_num=3） |
| `logger_conf` | `LoggerConf` | 日志级别与处理器 |
| `password_conf` | `PasswordConf` | 密码策略（有效期、错误锁定） |
| `cookie_conf` | `CookieConf` | JWT Cookie 配置（默认过期 86400s） |
| `jwt_secret` | `str` | 登录态 JWT 签名密钥。**代码无默认值**（F068）：yaml 配了就用；未配置 / 为空 / 等于历史内置默认值时，首次需要的进程随机生成并写入 `config` 表（键 `jwt_secret`），全部进程共用。轮换：改 yaml 或删该记录后重启，全员重登 |
| `system_login_method` | `SystemLoginMethod` | 登录方式（商业版标识、多端登录） |
| `mcp` | `McpConf` | MCP 协议配置 |
| `information_conf` | `IntelligenceCenterConf` | 情报中心配置 |
| `open_api` | `OpenApiConf` | 开放 API：个人密钥开关、`public_base_url`（对外地址，见下节） |

### 反向代理与对外地址

技能包脚本从**用户自己的电脑**回调平台，所以它需要「用户浏览器访问平台用的地址」。这个地址有两个来源：

1. **配置命令里的浏览器地址（优先）**：「AI 助手接入」弹窗的一键复制命令是 `search.py --configure --base-url <浏览器地址> --api-key <密钥>`，地址取自浏览器的 `window.location.origin`，写入用户本机凭据文件后成为默认地址。浏览器看到的就是正确的协议、域名和端口，也天然适配「内网 IP / 域名 / VPN 多入口」。
2. **包内烘焙地址（兜底）**：下载 zip 时后端现场渲染，推导顺序在 `bisheng/open_api/api/public_base_url.py`：
   1. `config.yaml` 的 `open_api.public_base_url`（`scheme://host[:port][/prefix]`，启动期校验）；
   2. 反向代理传来的 `X-Forwarded-Proto` / `X-Forwarded-Host`（取逗号链首值），退而取 `Host`；
   3. 进程绑定的 socket。
   落到第 2 步的 `Host` 或第 3 步时，后端按进程记一次 warning；管理员打开「AI 助手接入」弹窗时，若包内地址与浏览器地址不一致会看到提示。

仓库自带的 nginx（`docker/nginx/conf.d/*.conf`、镜像内 `src/frontend/nginx.conf`）已通过 `map` 传这两个转发头：外层代理已带头则透传，否则用本机 `$scheme` 与含端口的 `$http_host`。部署时按形态核对：

| 形态 | 包内地址会不会对 | 建议 |
|---|---|---|
| 单机 compose，浏览器直连 nginx | 对 | 无需配置 |
| TLS 在 nginx 之前终结（云负载均衡、外层反代） | 外层不传 `X-Forwarded-Proto` 时会变成 `http://` | 外层转发 `X-Forwarded-Proto/Host`，或配 `open_api.public_base_url` |
| k8s ingress | ingress-nginx 默认 `use-forwarded-headers: false`，会用自己看到的协议覆盖外层头 | 前面还有 TLS 终结时开启 `use-forwarded-headers`，或配配置项 |
| 商业版网关，前面有仓库 nginx | 对：网关追加而非覆盖转发头，首值仍是 nginx 给的浏览器地址（105 实测） | 无需配置 |
| 商业版网关直接对外 | 对：网关虽改写 `Host`，但会补上 `X-Forwarded-Host`（用户访问网关用的地址）与协议（105 实测） | 网关之前若还有 TLS 终结，需转发 `X-Forwarded-Proto` 或配配置项 |
| compose 多节点 | 每台机器各读自己的 `config.yaml` | 配置项要在所有节点一致 |
| 路径前缀部署 | 只能靠配置项 | 配 `open_api.public_base_url` |

两点取舍：

- 配置项会让**所有人**的包内地址都是同一个值；多入口访问的平台若配了它，某些网络下包内地址反而连不上。这时依赖第 1 个来源即可，包内地址只是兜底。
- 仓库 nginx 未配 `server_name`，接受任意 `Host`。公网暴露的实例建议配置 `open_api.public_base_url` 或限定 `server_name`，避免包内地址与出站白名单被伪造的 `Host` 带偏。

`open_api.public_base_url` 是 `open_api` 段的子键，只对已认识该段的镜像（3.0.0-beta1+）安全；不要给老镜像的 `config.yaml` 加未注释的 `open_api:` 顶层键。

## 本地混合开发部署

混合部署模式下，存储服务运行在 Docker 中，后端和前端从本地源码启动。这种模式下需要先停止 Docker 中的后端和前端容器以释放端口。

```
本地源码运行                          Docker 容器运行
──────────────                        ──────────────
FastAPI 后端     :7860                MySQL 8.0        :3306
Celery Workers   (无独立端口)          Redis 7.0        :6379
Vite Dev Server  :3001                Milvus 2.5       :19530
                                      Elasticsearch    :9200
                                      MinIO            :9100 (映射到容器内 9000)
```

### 启动步骤

```bash
# 1. 启动全部 Docker 容器
cd docker && docker compose -p bisheng up -d

# 2. 停止与本地服务冲突的容器
docker stop bisheng-backend bisheng-backend-worker bisheng-frontend

# 3. 启动本地后端
cd src/backend
.venv/bin/uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log

# 4. 启动 Celery Workers（各开一个终端）
.venv/bin/celery -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery -n knowledge@%h
.venv/bin/celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h
.venv/bin/celery -A bisheng.worker.main beat -l info

# 5. 启动前端开发服务器
cd src/frontend/platform
npm start -- --host 0.0.0.0   # 端口 3001，API 代理到 localhost:7860
```

## 远程开发工作流

项目支持本地编辑、远程运行的开发模式。代码在本地 Mac 编辑，通过 rsync 同步到远程服务器执行。

### 同步脚本

项目根目录的 `bisheng-sync.sh` 提供三种同步模式：

| 命令 | 说明 |
|------|------|
| `./bisheng-sync.sh up` | 本地代码推送到远程服务器 |
| `./bisheng-sync.sh down` | 远程代码拉取到本地 |
| `./bisheng-sync.sh watch` | 监听本地文件变化，自动推送到远程 |

### 日常流程

1. 终端 A 常驻 `./bisheng-sync.sh watch`，监听文件变化自动同步
2. 本地 IDE（Claude Code / Cursor 等）编辑 `/Users/lilu/Projects/bisheng` 下的代码
3. 改动自动推送到远程服务器，远程进程加载新代码
4. 浏览器通过 `http://192.168.106.114:8860` 访问（Nginx 反向代理）

注意：如果未开启 watch 模式，修改代码后需手动执行 `./bisheng-sync.sh up` 推送到远程。

## Celery Worker 启动模式

`docker/bisheng/entrypoint.sh` 通过第一个参数控制启动模式，支持 7 种运行方式：

| 模式 | 命令 | 队列 | 并发数 | 说明 |
|------|------|------|--------|------|
| `api` | `uvicorn bisheng.main:app` | -- | 8 workers | FastAPI 服务器（默认模式） |
| `knowledge` | `celery ... worker -Q knowledge_celery` | `knowledge_celery` | 20 线程 | 知识库文档解析、Embedding 生成 |
| `workflow` | `celery ... worker -Q workflow_celery` | `workflow_celery` | 100 线程 | 工作流 DAG 执行 |
| `beat` | `celery ... beat` | -- | -- | 定时任务调度器 |
| `default` | `celery ... worker -Q celery` | `celery` | 100 线程 | 遥测统计等默认任务 |
| `linsight` | `python bisheng/linsight/worker.py` | -- | 4 worker / 5 并发 | 灵思 Agent 独立进程 |
| `worker` | 以上全部（除 api） | 全部 | -- | 一次性启动全部 Worker + Beat |

### 定时任务（Beat Schedule）

在 `CeleryConf`（`src/backend/bisheng/core/config/settings.py`）中定义的默认定时任务：

| 任务标识 | Celery Task 路径 | 调度时间 | 说明 |
|---------|-----------------|---------|------|
| `telemetry_mid_user_increment` | `bisheng.worker.telemetry.mid_table.sync_mid_user_increment` | 每日 00:30 | 用户增量遥测统计 |
| `telemetry_mid_knowledge_increment` | `bisheng.worker.telemetry.mid_table.sync_mid_knowledge_increment` | 每日 00:30 | 知识库增量遥测统计 |
| `telemetry_sync_mid_app_increment` | `bisheng.worker.telemetry.mid_table.sync_mid_app_increment` | 每日 00:30 | 应用增量遥测统计 |
| `telemetry_sync_mid_user_interact_dtl` | `bisheng.worker.telemetry.mid_table.sync_mid_user_interact_dtl` | 每日 00:30 | 用户交互明细统计 |
| `sync_information_article` | `bisheng.worker.information.article.sync_information_article` | 每日 05:30 | 同步情报中心文章 |

## 运维管理脚本

`docker/deploy.sh` 提供常用运维操作的快捷命令：

| 命令 | 用法 | 说明 |
|------|------|------|
| `logs` | `./deploy.sh logs backend [-n 200]` | 实时跟踪容器日志 |
| `version` | `./deploy.sh version [v3.0.0]` | 查看或修改镜像版本号 |
| `exec` | `./deploy.sh exec backend` | 进入容器 Shell |
| `update` | `./deploy.sh update [backend]` | 拉取最新镜像并重启 |
| `restart` | `./deploy.sh restart [backend worker]` | 重启指定服务 |

支持的 service 别名：`backend`、`worker`（backend_worker）、`frontend`、`mysql`、`redis`、`es`（elasticsearch）、`minio`、`milvus`、`etcd`。

## 升级 checklist

> 跨版本升级时，除 `alembic upgrade head`（DDL）外，部分版本还引入了**一次性数据迁移 / backfill 脚本**。这类数据操作按约定不放进 Alembic（见 `src/backend/CLAUDE.md`「Migration vs. script」），需在升级后**手动按序执行**。脚本均**默认 dry-run、可重复执行（幂等）**，建议先空跑看摘要再加 `--apply`。脚本详细说明见 `src/backend/scripts/README.md`。

### v2.6 · 灵思任务模式迁移（F035）

从 < v2.6 升级到 v2.6（自研 ReAct → deepagents）涉及 4 件事。其中**步骤 2/3 在服务首次启动时自动执行**（`main.lifespan` 里的幂等 backfill，对齐 F034 先例：失败只记日志、绝不阻塞启动，下次启动自愈），运维**无需手动跑**——对应脚本仅在需要时供手动补跑 / dry-run 核对。**步骤 1 由部署流程执行、步骤 4 需手动执行。**

| # | 步骤 | 触发方式 | 命令（手动补跑 / 核对，从 `src/backend/`） | 不执行的后果 |
|---|------|---------|------------------------------------------|-------------|
| 1 | **建表**（DDL，先决条件） | 🔧 部署流程 | `uv run alembic upgrade head` | 后续 backfill / 脚本所依赖的 `linsight_skill` 等表不存在 |
| 2 | **灵思执行模型收敛**（Track E） | ✅ 启动自动 | `python scripts/migrate_linsight_task_model_to_default.py` → `--apply` | `task_model` / `linsight_executor_mode` 残留，新内核取不到 `linsight_default_model_id`，灵思无可用执行模型 |
| 3 | **任务模式菜单权限**（WEB_MENU） | ✅ 启动自动 | `python scripts/backfill_linsight_task_mode_web_menu.py` → `--apply` | 存量角色丢失 `linsight_task_mode` 菜单，路由守卫拦截，看不到任务模式入口 |
| 4 | **存量 SOP → Skill**（Track G） | ✋ 手动 | `bash scripts/migrate_sop_to_skill.sh` → `bash scripts/migrate_sop_to_skill.sh apply` | 存量 `linsight_sop` 不会转为可用 Skill，管理页 / 技能选择器为空 |

要点：

- **为什么 2/3 自动、4 手动**：2/3 是纯 DB、幂等、轻量的 backfill，失败只影响菜单 / 模型配置且可自愈，适合放进启动 lifespan；步骤 4 要写技能正文、数据量可能大、需人工核对迁移摘要，副作用重，故保持手动运维脚本（详见 `src/backend/CLAUDE.md`「Migration vs. script」与 PRD 决策）。
- **步骤 4 说明**：需要完整 app context（写技能 bundle）。**不调用 LLM**——技能描述取 SOP 原描述，缺失时用 SOP 名称兜底（技能描述为必填，不会留空）。产出 JSON 迁移摘要（成功/跳过/失败，**运维产物，无管理页报告界面**），失败 / 超大 SOP 项需人工处理（拆分后经管理页重建）。`linsight_sop` 原表保留归档、不删。
- **幂等**：四步均可安全重跑。步骤 2/3 重复启动是 no-op；步骤 4 借 `metadata.sop-id` 识别已迁移项并覆盖自身 bundle，不会重复产生带后缀的技能。
- 步骤 4 单租户灰度可加 `--tenant-id <id>`。

### v3.0 · 灵思技能 bundle 迁至对象存储

技能正文/脚本/附件此前以**节点本地文件系统**（`SKILLS_ROOT`）为权威存储，DB 只存元数据。单机
compose 下 `backend` 与 `backend_worker` 恰好 bind-mount 同一个 `/app/data` 才让它工作；一旦两者
不在同一台宿主机，A 机上传的技能在 B 机 worker 上读不到，而失败是**静默**的——任务照跑，只是技能
不生效。现改为对象存储（MinIO）为唯一权威 + 节点本地按内容哈希缓存。

| # | 步骤 | 触发方式 | 命令（从 `src/backend/`） | 不执行的后果 |
|---|------|---------|--------------------------|-------------|
| 1 | **加 `linsight_skill.content_hash` 列** | 🔧 部署流程 | `uv run alembic upgrade head` | 后端起不来（缺列） |
| 2 | **发布本机残留的技能 bundle** | ✅ 启动自动（窄） | `python scripts/migrate_skills_to_object_storage.py` → `--apply` | 存量的**用户自建/导入**技能不生效 |
| 3 | **内置技能重新发布** | ✅ 启动自动 | —（seeder 按内容哈希幂等） | 三个官方技能不生效 |

要点：

- **步骤 2 的启动自愈是刻意做窄的**：只发布本机确实持有、且字节数与 DB 记录一致的 bundle。多副本
  同时启动时各自看到不同的本地盘，若谁都能发布自己那份，胜出者就是随机的——那正是本次要消除的
  多节点不一致。凡不满足条件的，日志会**按技能名列出**，这就是「去持有该 bundle 的那台机器上跑一次
  脚本」的信号。
- **每台曾经跑过 API 的机器都要跑一次**步骤 2 的脚本。某台机器盘上没有的，它会报告出来。
- **内置技能不需要迁移**：seeder 直接从镜像重新发布，比任何一台机器的磁盘都更权威。
- **回滚**：新版本期间创建/编辑的技能只存在于对象存储中，旧代码只读本地盘，会**静默失效**。若确需
  回滚，先在每台目标机器上跑 `python scripts/restore_skills_to_local.py --apply` 把 bundle 写回
  `SKILLS_ROOT`。
- 配置项 `linsight.skills_root` 已降级为「迁移脚本读取本地遗留 bundle 的来源」，运行期不再使用；
  本地缓存目录由 `linsight.skills_cache_dir` 指定（留空 = 进程缓存目录下的 `linsight_skills`）。
  **不要**把缓存目录指向共享卷。

### v3.0 · 登录态 JWT 签名密钥不再内置（F068）

< v3.0.0-beta2 的代码里带有一个公开的 `jwt_secret` 默认值，默认部署从未覆盖它，任何人都能用它伪造超管登录态（NVDB 报告）。升级后：

| 情况 | 升级后行为 | 用户影响 |
|------|-----------|---------|
| `config.yaml` 从未配置 `jwt_secret`（绝大多数） | 首次启动自动生成随机密钥写入 `config.jwt_secret`，所有 api / worker 进程共用 | 全员重新登录一次 |
| `config.yaml` 配了自己的私有值 | 继续使用 | 无感 |
| `config.yaml` 抄了老代码里的默认值 | 命中黑名单，等同未配置 | 全员重新登录一次 |

无需手动步骤。个人访问令牌与开放 API 凭据不走这把密钥，不受影响。要主动轮换：改 yaml 的值，或 `DELETE FROM config WHERE key='jwt_secret'` 后重启全部后端进程。

## 多节点部署

官方 `docker/docker-compose.yml` 是**单机单副本**编排，但组件本身按多节点设计（`entrypoint.sh` 中
workflow worker 明确标注「支持多节点运行」，灵思 worker 用 hostname 级 `node_id` + 心跳 + 任务
ownership）。横向扩容时按下表核对。

| 组件 | 可否多副本 | 注意事项 |
|------|-----------|---------|
| `backend`（FastAPI） | ✅ | 无状态。启动期 backfill/seeder 幂等，多副本同启安全 |
| `backend_worker`（Celery + 灵思 worker + Beat） | ⚠️ | Celery worker 可多节点，队列名需按 `entrypoint.sh` 注释约定；**Beat 只能有一个实例**，否则定时任务重复触发 |
| MySQL / Redis / MinIO / Milvus / ES / OpenFGA | — | 有状态，按各自方案做高可用 |

**关键约束：不要用共享卷在节点间传递业务数据。** 权威存储只有 MySQL/DM8、Redis、MinIO 三处；节点
本地磁盘（`/app/data`、进程缓存目录）一律视为可随时丢弃的缓存。这条已写入架构宪法
[C8](../constitution.md#c8-no-shared-state-on-the-local-filesystem)。单机 compose 下 `backend` 与
`backend_worker` 共享同一个 `/app/data`，会让「跨进程传文件」看起来能用——这是巧合，不是保证。

## 相关文档

- 系统架构总览 -- `docs/architecture/01-architecture-overview.md`
- 配置系统详解 -- Settings 类定义在 `src/backend/bisheng/core/config/settings.py`
- 开发指南 -- `docs/architecture/09-development-guide.md`
