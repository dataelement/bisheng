# deploy.md — 本地开发环境一键启动

> 对应文件:[`Makefile`](Makefile)(仓库根目录)。
> 适用场景:开发者本机跑起**整套 BiSheng**——中间件容器 + 后端 API + Celery + 两个 SPA。
> 线上/客户环境装机不走这里,见 [`docs/architecture/08-deployment.md`](docs/architecture/08-deployment.md)。
>
> 本文内容于 2026-11-08 在 Apple Silicon Mac 上实测(见文末「验证记录」)。

---

## 1. 快速开始

```bash
make up        # 中间件 + 后端 + Celery(knowledge/workflow/beat) + platform + client
make wait      # 等到 /health、2 个 worker、两个前端都就绪
make status    # 一屏看完:pids / 端口 / HTTP / celery ping / 容器状态
```

停止:

```bash
make down        # 只停 make 起的应用进程,中间件继续跑
make infra-down  # 连中间件容器一起停(数据卷保留)
```

### 前置条件

| 依赖 | 说明 |
|------|------|
| Docker + `docker compose` | 中间件用 `docker/docker-compose.yml` + `docker/docker-compose.local-arm64.yml` |
| `docker/.env` | CR 镜像 tag 与凭据,compose 自动读取;缺失时 `make infra-up` 会直接报错退出 |
| `docker/.env.app` | 原生 `make up` 启动 backend / Celery 时 source 的**本机密钥**文件(`PADDLE_OCR_TOKEN` 等);git-ignored,缺失不报错。从 `docker/.env.app.example` 复制。compose/helm 形态不用它,走 `docker/.env` / `backend.extraEnv` |
| 后端 `.venv` | `src/backend/.venv`(uv 同步好,Python 3.11) |
| `pnpm` | workspace 内会由 corepack 解析到 `9.15.9`(workspace 要求 `>=9.15.9 <10`) |

---

## 2. 目标一览

### 2.1 聚合 / 生命周期

| 目标 | 作用 |
|------|------|
| `make up` | 基础组件 + 后端 + Celery(knowledge/workflow/beat/默认队列)+ 两个 SPA,全部后台启动 |
| `make up-backend` | 只起后端 + Celery(knowledge / workflow / beat) |
| `make up-frontend` | 只起 platform(:3001)+ client(:4001) |
| `make down` | 停掉所有由 make 起的进程(实测无残留,见 §5.4) |
| `make restart` | `down` + `up` |
| `make wait` | 阻塞到 `/health`、2 个 Celery worker、两个前端都就绪 |
| `make status` | 进程 / 端口 / HTTP / celery ping / 中间件容器状态 |
| `make logs` | `tail -f` 所有进程日志 |
| `make clean-logs` | 删除 `logs/dev/` |

### 2.2 中间件

| 目标 | 作用 |
|------|------|
| `make infra-up` | 核心组件 `mysql redis minio openfga`(自动带 `openfga-migrate` 一次性迁移容器) |
| `make infra-up-rag` | 在上面的基础上追加 `etcd milvus elasticsearch`——只有知识库 / RAG 链路需要,默认不起 |
| `make infra-down` | `docker compose down`,保留 `docker/` 下的数据卷 |
| `make infra-status` | 容器状态 |
| `make infra-logs` | 跟随中间件日志,`SVC=mysql` 可只看单个服务 |
| `make infra-pull` | 预拉 arm64 镜像(新机器首次较慢) |

### 2.3 单进程前台运行(日志直接打在终端,Ctrl-C 停止)

| 目标 | 进程 |
|------|------|
| `make backend` | FastAPI(`uvicorn bisheng.main:app`,:7860) |
| `make worker-knowledge` | `knowledge_celery` worker,`-c 20 -P threads` |
| `make worker-workflow` | `workflow_celery` worker,`-c 100 -P threads` |
| `make worker-beat` | Celery beat |
| `make worker-default` | 默认 `celery` 队列(telemetry + 管理台「立即同步」),**随 `up`/`up-backend` 一起启动** |
| `make worker-linsight` | Linsight agent worker(可选,后台) |
| `make platform` / `make client` | 两个 SPA(vite) |
| `make frontend` | 两个 SPA 后台启动 |

### 2.4 端口与进程对照

| 组件 | 端口 | 命令 |
|------|------|------|
| 后端 API | 7860 | `.venv/bin/uvicorn bisheng.main:app`(`config=config.yaml`) |
| platform SPA | 3001 | `pnpm dev -- --host 0.0.0.0` |
| client SPA | 4001 | `pnpm dev -- --host 0.0.0.0`(`/workspace` 基路径) |
| MySQL / Redis / MinIO / OpenFGA | 3306 / 6379 / 9100 / 8080-8081 | docker compose |

---

## 3. 日志与 pid

后台进程的状态全部落在 `logs/dev/`(命中 `.gitignore` 里已有的 `logs`、`*.log` 规则,不会污染 `git status`):

```
logs/dev/backend.log             logs/dev/backend.pid
logs/dev/worker-knowledge.log    logs/dev/worker-knowledge.pid
logs/dev/worker-workflow.log     logs/dev/worker-workflow.pid
logs/dev/worker-beat.log         logs/dev/worker-beat.pid
logs/dev/platform.log            logs/dev/platform.pid
logs/dev/client.log              logs/dev/client.pid
logs/dev/celerybeat-schedule     # beat 的调度文件(不放 src/backend)
```

---

## 4. 实现说明

- **中间件命令**是实测可跑的组合:

  ```bash
  docker compose --env-file docker/.env --env-file docker/.env.local \
    -f docker/docker-compose.yml -f docker/docker-compose.local-arm64.yml \
    up -d mysql redis minio openfga
  ```

  `.env` 由 compose 从 `docker/` 自动读取(project directory = 第一个 `-f` 文件所在目录)。arm64 override 把 CR 上的 AMD64 tag 换成每个组件的 Apple Silicon 构建。

- **后端用 `.venv/bin/{uvicorn,celery,python}`,不用 `uv run`**。与线上/实际在跑的进程一致,也避免每次启动前重新解析同步依赖(本机走系统代理时容易卡住)。

- **`config=config.yaml` 显式传给后端和 Celery**。该变量相对 `bisheng` 包目录解析,所以每个命令都先 `cd src/backend`。

- **`make down` 不会杀中间件**。MySQL/Redis/MinIO/OpenFGA 是长生命周期容器(本机已连续跑数天),停应用不该连带停它们;要一起停用 `make infra-down`。

- **端口已被占用时“收养”**。如果 3001/4001/7860 上已经有进程(例如你先手动起了 vite),`make up` 不会重复启动,而是把该 pid 写进 `logs/dev/<name>.pid`,并提示 `make down` 会一并停掉。

- **beat 的调度文件**通过 `-s logs/dev/celerybeat-schedule` 定向,不再在 `src/backend/` 留下 `celerybeat-schedule.db`。

- **`up` 只起核心中间件**,Milvus / ES / etcd 属于 RAG 链路,用 `make infra-up-rag` 单独起,避免每次开发都吃这份内存。

---

## 5. 常用场景

### 5.1 只改后端代码,重启 API

后端以 `--no-reload` 方式运行(与 AGENTS.md 一致),改代码后需要重启:

```bash
make down && make up-backend     # 或者单独 kill 掉 backend 再 make up-backend
```

### 5.2 需要知识库 / RAG

```bash
make infra-up-rag
```

### 5.3 Linsight worker

```bash
make worker-linsight   # linsight/agent 相关功能才需要
```

默认队列 worker(`make worker-default`)已随 `make up` 启动,它同时消费 telemetry 任务和管理台「组织同步 → 立即同步」投递的任务。

### 5.4 排障

| 现象 | 处理 |
|------|------|
| `missing docker/.env` | `cp docker/.env.example docker/.env` 并填 CR 凭据 |
| 端口被占 / 起了两份 | `make status` 看 pid,`make down` 收掉,再 `make up` |
| 后端起不来 | `tail -100 logs/dev/backend.log`;常见是 MySQL 未 healthy 或 `config.yaml` 缺键 |
| worker 不在线 | `logs/dev/worker-*.log`;确认 Redis 可达(本机 `redis://127.0.0.1:6379/2`) |
| 前端 3001/4001 起不来 | `logs/dev/platform.log` / `client.log`;确认 pnpm 解析到 9.15.9(`pnpm --version`) |
| 工作台(:4001/workspace)白屏 | 未登录。401 后按 `__APP_ENV__.PLATFORM_ORIGIN` 跳平台登录页(:3001),直接开 `http://localhost:4001/workspace/__dev/login` 登录最快 |
| 工作台输入框灰掉、无法输入文字 | 租户没配工作台模型:客户端在 `bsConfig.models` 为空时禁用输入框(`ChatView.tsx`),并在输入框上方提示「当前租户尚未配置工作台模型」(管理员带「去管理端配置」链接)。平台 → 模型管理 → **工作台模型** 选上模型保存即可;对应数据是 `tenant_system_model_config.linsight_llm.models`(为 `null` 即未配置) |
| arm64 镜像拉不动 | Docker Hub 直连不可用,依赖 `cr.dataelem.com` 的 arm64 tag;`make infra-pull` 预拉 |

> 换 MySQL 镜像版本前注意:**MySQL 不能跨版本降级**,需要清空 `docker/mysql/data` 后重新 `alembic upgrade head`。

---

## 6. 服务器部署：组件、端口与对外暴露

> 部署形态：单机 `docker compose`（`docker/docker-compose.yml`）。用户的唯一必需入口是 frontend 容器的 **3001/tcp**——容器内 nginx 同时托管两个 SPA，并反向代理 API、WebSocket、对象存储路径和托管应用。

### 6.1 对外必须开放

| 端口 | 组件 | 承载内容 |
|---|---|---|
| **3001/tcp** | `bisheng-frontend`（容器内 nginx） | `/` 管理端、`/workspace/` 工作台、`/api/v1`·`/api/v2`·`/workspace/api`（→ `backend:7860`）、`/apps/`（→ `app-proxy`）、`/bisheng`·`/tmp-dir`（→ `minio:9000`）、WebSocket |
| 443/tcp（建议） | 外层 LB / Nginx | TLS 终结后转发到 3001；仓库自带 nginx 只监听 3001，不监听 80/443 |

因为 API 也走 3001，**不需要**把 7860 暴露给用户；直接暴露等于绕过 nginx 的鉴权边界与限流。

### 6.2 按需对外

| 端口 | 组件 | 何时需要 |
|---|---|---|
| 9100/tcp | `bisheng-milvus-minio`（9000 数据面） | 启用 OnlyOffice（文档服务是独立 compose，解析不到容器名 `minio`），或需要浏览器直连对象 URL 时。否则保持关闭，并置于 TLS/内网之后 |
| 8701/tcp | `bisheng-office`（可选 `docker-compose-office.yml`） | 启用文档在线预览/编辑时，浏览器需要能访问 |
| 8443/tcp | nginx `websocket.conf` | 配置里有独立 WS server（`/api` → backend/gateway），但 compose **未发布**该端口，默认不可达；只有需要单独 WS 入口时才映射 |

### 6.3 只应内网 / 本机访问

| 端口 | 服务 | 说明 |
|---|---|---|
| 7860 | `bisheng-backend`（FastAPI） | nginx 的上游 |
| 3306 | `bisheng-mysql` | 业务库 + OpenFGA 库 |
| 6379 | `bisheng-redis` | 缓存、Celery broker、会话 |
| 8080 / 8081 / 2112 | `bisheng-openfga` | HTTP / gRPC / metrics |
| 9200 / 9300 | `bisheng-es` | 全文检索（业务 + 遥测） |
| 19530 / 9091 | `bisheng-milvus` | gRPC / metrics |
| 无宿主端口 | `backend_worker`、`etcd`、`gateway`（网关形态）、`runtime-manager`、`egress-proxy`、`app-proxy`、`code-runner-1/2` | 仅容器网络内通信 |

### 6.4 现状与加固建议

compose 默认把上表端口都发布到 `0.0.0.0`。服务器上二选一：

1. **安全组 / 防火墙**：只放行 3001（及按需的 9100 / 8701），其余仅内网可达；
2. **改绑定回环**：把映射改成 `- "127.0.0.1:3306:3306"` 这类形式，需要调试时再临时放开。

其余注意点：

- **`BS_MINIO_SHAREPOINT` 必须是浏览器/文档服务可达的地址**（镜像默认是容器内的 `minio:9000`），否则预签名 URL 打不开；配套的 9100 映射按需开放。详见 [`docs/architecture/08-deployment.md`](docs/architecture/08-deployment.md) §对象存储凭证与端口。
- **商业网关形态**（`bash docker/install.sh --gateway ...`）只改 nginx 上游（`/api` → `gateway:8080`），对外端口仍是 3001；gateway 自身不映射宿主端口，需要 license。
- **应用工场**（`app-runtime` profile）的 `runtime-manager` / `egress-proxy` / `app-proxy` 全部无宿主端口。
- **登录态按 host 隔离**：`localhost`、`127.0.0.1`、域名、IP 各自独立，对外请固定使用一个域名。
- 只暴露 3001 时，`9101`（MinIO 管理台）本来就没映射；需要时用 `ssh -L 9001:localhost:9001` 隧道。

### 6.5 速查

```text
对外：3001（必须）  9100（?）  8701（?）  443（建议由外层终结）
内网：7860 3306 6379 8080 8081 2112 9200 9300 19530 9091
无宿主端口：backend_worker etcd gateway runtime-manager egress-proxy app-proxy code-runner-*
```

---

## 7. 验证记录(2026-11-08,Apple Silicon Mac)

```text
$ make up
  backend: started (pid …) → logs/dev/backend.log
  worker-knowledge: started (pid …)
  worker-workflow: started (pid …)
  worker-beat: started (pid …)
  platform: started (pid …)
  client: started (pid …)

$ make wait
waiting for backend /health ✓
waiting for celery workers ✓ (2 nodes online)
waiting for SPAs ✓ (3001 + 4001)

$ make status
== processes ==   backend / client / platform / worker-beat / worker-knowledge / worker-workflow  running
== http ==        backend /health {"status":"OK"} (200) · platform 200 · client 200
== celery ==      workflow@… OK · knowledge@… OK · 2 nodes online
== middleware ==  minio / mysql / openfga / redis  Up (healthy)

$ make down
  backend: stopped · client: stopped · platform: stopped
  worker-beat: stopped · worker-knowledge: stopped · worker-workflow: stopped
# 复查:7860 / 3001 / 4001 均无监听,无残留进程
```
