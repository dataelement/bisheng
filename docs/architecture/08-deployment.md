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
| `system_login_method` | `SystemLoginMethod` | 登录方式（商业版标识、多端登录） |
| `mcp` | `McpConf` | MCP 协议配置 |
| `information_conf` | `IntelligenceCenterConf` | 情报中心配置 |

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

## 相关文档

- 系统架构总览 -- `docs/architecture/01-architecture-overview.md`
- 配置系统详解 -- Settings 类定义在 `src/backend/bisheng/core/config/settings.py`
- 开发指南 -- `docs/architecture/09-development-guide.md`
