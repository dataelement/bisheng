# 应用工场部署与配置

> 面向运维 / 实施。**这一层默认不安装**——不装它，平台其余部分与 v2.x 完全一致。
> 本文覆盖"从零把它装起来"的全过程：装什么、配什么、怎么验、装错了什么症状。
>
> 平台整体部署（MySQL / Redis / Milvus / ES / MinIO / 后端 / 前端）见
> [`08-deployment.md`](08-deployment.md)，本文只讲**增量**。

## 这一层是什么

「应用工场」让开发者把本地写好的应用（Web 页面、表单、看板、小工具、后端服务）
用命令行一条 `bisheng deploy` 发布到平台上，成为与工作流、助手并列的第三种应用类型
——**托管应用**。发布后它跑在平台管的容器里，用户从 `/apps/{slug}` 访问，
登录态与可见范围由平台统一管，应用自己不做登录。

它由**两个互相独立的开关**控制，两个都默认关闭，任意组合都能正常启动：

| 开关 | config.yaml 键 | 关掉的后果 |
|------|---------------|-----------|
| **开放能力层** | `open_platform.enabled` | 密钥签发表单里没有 `model:invoke` / `identity:read` / `app:manage` 三个能力位，带这些位的请求被拒（错误码 26023）。命令行部署要用 `app:manage`，所以**用 CLI 就必须开** |
| **工场运行时层** | `app_runtime.enabled` | `/apps/{slug}` 渲染"本环境未启用应用工场"引导页；CLI 部署被 16207 明确拒绝（不是超时）；平台其余功能零变化 |

两者不是父子关系：只开 `open_platform` 可以让开发者拿到密钥调开放 API，
但发布不了托管应用；只开 `app_runtime` 时已有的托管应用能跑、能访问，
但没人能用 CLI 发新的。**要跑通完整闭环，两个都要开。**

## 组件与端口

运行时层在平台既有服务之外新增**两个进程**：

| 服务 | 端口 | 职责 | 需要 docker 权限 |
|------|------|------|-----------------|
| **runtime-manager** | 8091 | 编排器。构建镜像、拉起 / 停止 / 重建实例、容量准入、15 秒一轮的自愈对账、提供实例路由与日志 | **是**（唯一被允许访问容器编排面的组件） |
| **app-proxy** | 8090 | 统一入口。解析 `/apps/{slug}` → 向后端问一次访问判定 → 剥掉伪造的身份头 → 注入真实访问者身份 → 反向代理到实例 | 否（刻意不给） |

两个端口**都不对外暴露**：外部流量一律先进 nginx（3001），由 nginx 的
`location /apps/` 转给 app-proxy。三方之间的调用全部经 HMAC 签名，
且**后端自身不持有任何容器编排能力**——它只向 runtime-manager 下发"期望它变成什么样"
的意图，这是本层最重要的安全边界。

```
浏览器 ──► nginx :3001
             ├─ /                → platform 前端
             ├─ /workspace/      → client 前端
             ├─ /api/…           → backend :7860
             └─ /apps/{slug}/…   → app-proxy :8090
                                      │  ① 问判定 ──► backend :7860 （内部授权端点，HMAC）
                                      │  ② 问地址 ──► runtime-manager :8091 （HMAC）
                                      └──► 应用容器（bisheng-apps 网络内，不映射宿主端口）

backend :7860 ──（下发编排意图，HMAC）──► runtime-manager :8091 ──► dockerd
```

托管应用容器接在一个名为 `bisheng-apps` 的 bridge 网络上，**不映射任何宿主端口**
——它们只能被 app-proxy 访问到，这是「不绕过权限直连应用」的物理保证。

## 形态一：docker compose 单机

### 1. 准备数据目录

```bash
mkdir -p /opt/bisheng/app-data && chmod 755 /opt/bisheng/app-data
```

数据目录必须是**本机磁盘**。托管应用的内置数据库用 SQLite（WAL 模式），
放在 NFS / CIFS 等网络存储上会损坏。想换位置就设 `BISHENG_APP_DATA_ROOT`
（compose 用它同时决定卷的宿主侧路径和 `RTM_HOST_DATA_ROOT`，两者不会漂移）。

`bisheng-apps` 网络**由部署方创建，runtime-manager 不会自己建**——一个会偷偷建网的
编排器会把"新机器上第一次发布必挂"这件事藏起来。compose 形态下这个"部署方"就是
`docker-compose.yml`（文件末尾已声明该网络并显式写死 `name: bisheng-apps`），
**不需要手工建**；只有不用 compose 的形态才要自己跑一次：

```bash
docker network create bisheng-apps        # 仅 systemd / 非 compose 形态需要
```

### 2. 生成三个密钥

```bash
export BISHENG_RTM_HMAC_SECRET=$(openssl rand -hex 32)
export BISHENG_APP_PROXY_HMAC_SECRET=$(openssl rand -hex 32)
export BISHENG_APP_OBO_SECRET=$(openssl rand -hex 32)
```

写进部署机的环境文件（compose 的 `.env` 或 systemd 的 `EnvironmentFile`），
**三个必须互不相同**，且 `BISHENG_APP_OBO_SECRET` 必须不同于平台的 `jwt_secret`
（相同时后端会拒绝签发身份令牌并打印告警——共用会让注入应用的临时令牌
能被当平台会话 cookie 用）。

### 3. 改 config.yaml

见下文「配置项详解」。**注意加键与发版的先后顺序**——见下文
「⚠️ 升级顺序（不可颠倒）」，顺序反了后端直接起不来。

### 4. 启动

两个服务挂在 compose 的 `app-runtime` profile 后面，不带 profile 就根本不创建：

```bash
cd docker/

# 平台本体（不含工场运行时层）——一如既往
docker compose up -d

# 追加工场运行时层：**每一条**相关的 compose 命令都要带 --profile
docker compose --profile app-runtime up -d runtime-manager app-proxy
```

漏掉 `--profile` 的症状是 `no such service`，不是静默不启动。

创建之后的日常运维用 `deploy.sh`，它会**自动补 `--profile`**，不用自己记：

```bash
./deploy.sh logs runtime-manager
./deploy.sh restart runtime-manager app-proxy
./deploy.sh exec app-proxy
```

（`deploy.sh` 只有 `logs` / `version` / `exec` / `update` / `restart` 五个命令，
**没有 `start`**——首次创建容器还是得用上面的 `docker compose up -d`。）

⚠️ 这两个服务在 compose 里是 **`build:` 而不是 `image:`**——它们从
`src/runtime-manager/` 与 `src/app-proxy/` 现场构建。所以部署机上必须有这两份源码，
且第一次 `up` 会花几分钟构建；纯拉镜像的离线环境需要先在有网机器上
`docker compose --profile app-runtime build` 再导出镜像。

### 5. 两个进程的环境变量

它们**不读 config.yaml**（独立包，不 import 平台代码），配置全部来自环境变量。
必须与 `config.yaml` 的 `app_runtime` 段一一对应，对不上的症状见文末「排障对照表」。

**runtime-manager**：

| 环境变量 | 必填 | 对应的 config.yaml 项 | 说明 |
|---------|:---:|----------------------|------|
| `RTM_HOST` / `RTM_PORT` | | | 容器内监听 `0.0.0.0:8091`；宿主 systemd 形态用 `127.0.0.1:8091` |
| `RTM_HMAC_SECRET` | ✅ | `app_runtime.manager_hmac_secret` | 不一致 = 所有编排请求被回 401 |
| `RTM_DATA_ROOT` | ✅ | `app_runtime.data_root` | **本进程看到的**数据目录路径 |
| `RTM_HOST_DATA_ROOT` | compose 必填 | — | **宿主 dockerd 看到的**同一个目录。容器化跑时两者不同（容器内 `/app-data`，宿主 `/opt/bisheng/app-data`），不设会让应用数据落到一个没人看的地方且**不报错** |
| `RTM_NETWORK` | | — | 默认 `bisheng-apps` |
| `RTM_RESERVE_MB` / `RTM_OVERCOMMIT_RATIO` / `RTM_BUILD_RESERVE_MB` | | 同名 `app_runtime.*` | 容量准入，见下 |
| `RTM_BUILD_INDEX_URL` | | `app_runtime.build_index_url` | 内网 pip 源 |
| `RTM_DOCKER_HOST` | | — | 留空 = 本机 `/var/run/docker.sock` |

**app-proxy**：

| 环境变量 | 必填 | 对应的 config.yaml 项 |
|---------|:---:|----------------------|
| `APP_PROXY_HOST` / `APP_PROXY_PORT` | ✅ | — |
| `APP_PROXY_BACKEND_BASE` | ✅ | 平台 API 基地址（compose 下 `http://backend:7860`） |
| `APP_PROXY_MANAGER_BASE` | ✅ | `app_runtime.manager_base_url` |
| `APP_PROXY_BACKEND_SECRET` | ✅ | `app_runtime.proxy_hmac_secret` |
| `APP_PROXY_MANAGER_SECRET` | ✅ | `app_runtime.manager_hmac_secret` |
| `APP_PROXY_ENTRY_BASE_URL` | | `app_runtime.entry_base_url` |

⚠️ **这六项的默认值全是单机回环便利值**（`127.0.0.1` + 空密钥）。在容器里
`127.0.0.1` 指的是容器自己，空密钥是 fail-closed——进程照样启动、健康检查照样通过、
每一个请求都渲染兜底页。所以它们**必须显式设置**，不能靠默认值。

**两个服务都必须同时接在 `default` 与 `bisheng-apps` 两张网上**（compose 文件里已配好）：

- `default` —— nginx 靠服务名 `app-proxy` 解析上游，backend 靠服务名找 runtime-manager；
- `bisheng-apps` —— app-proxy 拿到的上游是应用容器在该网络上的 bridge IP，跨 bridge
  网络会被 docker 的隔离规则丢包；runtime-manager 的启动探活也是直接 HTTP 访问同一个 IP。

⚠️ compose 里只要给某个 service 写了 `networks:`，它就**不再自动接 default**，
所以两张网都得列上——漏一张的症状分别是"nginx 解析不到 app-proxy"和"应用永远探活不过"。

宿主 systemd 形态下两个进程都在宿主机上，宿主本身可达 bridge 网段，无需额外处理。

## 形态二：systemd（信创 / 无 compose 环境）

两个进程作为宿主机上的独立单元运行，其余与 compose 形态一致：

| 单元 | 监听 | 依赖 | 运行身份 |
|------|------|------|---------|
| `bisheng-runtime-manager.service` | `127.0.0.1:8091` | `After=docker.service` | root 或 docker 组（需访问 docker socket） |
| `bisheng-app-proxy.service` | `127.0.0.1:8090` | `After=bisheng-api.service` | 普通用户即可，**不要**给 docker 权限 |

与 compose 形态的差异只有三点：

1. `RTM_HOST_DATA_ROOT` **不用设**——进程与 dockerd 在同一个文件系统视图里，
   两个路径本来就是同一个。
2. `manager_base_url` / `APP_PROXY_BACKEND_BASE` 用回环地址而不是 service 名。
3. nginx 的 `location /apps/` 里 `proxy_pass` 指向 `127.0.0.1:8090`，
   `resolver` 那行不需要（见下）。

密钥经 `EnvironmentFile` 注入、不落配置文件：

```
/etc/bisheng/runtime-manager.env     # RTM_HMAC_SECRET / RTM_DATA_ROOT / RTM_NETWORK …
/etc/bisheng/app-proxy.env           # APP_PROXY_BACKEND_BASE / …_MANAGER_BASE / 两个 SECRET
```

单元文件模板在 `features/v3.0.0/054-app-domain-runtime/deploy/`
（`bisheng-runtime-manager.service` / `bisheng-app-proxy.service`），真身由各环境的
部署仓维护。装好后把两者加进平台 `bisheng.target` 的 `Wants=` 与部署脚本的服务清单。

两个单元都只监听 `127.0.0.1`：前面永远有 nginx，HMAC 是防篡改不是防暴露，
把编排端口挂到 `0.0.0.0` 等于把编排能力挂到网上。

## nginx：`location /apps/`

`docker/nginx/conf.d/default.conf` 已内置。自建 nginx 时照抄，注意三处：

```nginx
location /apps/ {
    # ① compose 形态必须用「变量 + resolver 延迟解析」
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $bisheng_app_proxy http://app-proxy:8090;
    proxy_pass $bisheng_app_proxy$request_uri;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    # ② 应用可能流式输出，缓冲会把流攒成一坨
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    client_max_body_size 1024m;

    # ③ 只兜 nginx 自己产生的错误（上游连不上）
    error_page 502 503 504 = @apps_unavailable;
}

location @apps_unavailable {
    rewrite ^ /api/v1/apps/_unavailable break;
    proxy_pass http://backend_server;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

- **① 为什么不能写成 `proxy_pass http://app-proxy:8090;`**：nginx 在**加载配置时**
  解析静态 `proxy_pass` 里的主机名。整层不装时 app-proxy 容器不存在、主机名解析不了，
  **整个 nginx 起不来**——症状是升级后前端全站白屏，而不是"托管应用打不开"。
  变量式写法把解析推迟到请求期，解析失败只影响这一个 location。
  变量式 `proxy_pass` 不会自动带上原始 URI，所以要显式拼 `$request_uri`。
  systemd 形态指向 `127.0.0.1:8090`（IP 无需解析），可以写静态形式。
- **③ 刻意不开 `proxy_intercept_errors`**：开了会把应用自己返回的 502/503 也换成平台
  兜底页，那是在替应用说谎。

宿主 systemd 形态下，环境里有几份 nginx 配置就要改几份（对外端口那份也要）。

## 配置项详解

模板见 `docker/bisheng/config/config.yaml` 文件末尾的「应用工场」段。
**所有键都是进程级配置，改完必须重启后端**（不是数据库里的热配置，界面上改不了）。
**没有 `BS_*` 环境变量覆盖机制**——`app_runtime` / `open_platform` 只能写在
config.yaml 里；要避免明文密钥，用 `!env ${VAR}` 语法从环境变量取值。

> ⚠️ `!env ${VAR}` 在**环境变量不存在时会直接报错拒启**。要么保证部署脚本一定注入，
> 要么把整行注释掉。

### `open_platform` / `open_api`

| 键 | 默认值 | 含义 |
|----|-------|------|
| `open_platform.enabled` | `false` | 见上文开关表 |
| `open_api.service_account_idle_days` | `90` | 多少天无调用后在密钥列表里标记"闲置" |
| `open_api.credential_cache_ttl_seconds` | `3` | 凭据校验的正缓存秒数。**硬上限 5**，配更大不会报错，按 5 生效 |

### `app_runtime`

| 键 | 默认值 | 怎么取值 |
|----|-------|---------|
| `enabled` | `false` | 本机是否安装了运行时层 |
| `manager_base_url` | `http://127.0.0.1:8091` | systemd 形态保持默认；compose 形态改 `http://runtime-manager:8091` |
| `manager_hmac_secret` | `""` | `openssl rand -hex 32`，与 `RTM_HMAC_SECRET` 一致 |
| `proxy_hmac_secret` | `""` | `openssl rand -hex 32`，与 `APP_PROXY_BACKEND_SECRET` 一致 |
| `obo_secret` | `""` | `openssl rand -hex 32`，**必须不等于 `jwt_secret`** |
| `obo_ttl_seconds` | `900` | 注入应用的身份令牌寿命（秒），最小 60 |
| `entry_base_url` | `""` | 用户实际访问平台的对外基地址，如 `https://bisheng.example.com`（不带结尾斜杠）。**强烈建议配**：留空时应用地址只能给出相对路径 `/apps/{slug}`，浏览器里能用，但二维码、CLI 回显、外发链接都是残缺的 |
| `ws_max_lifetime_seconds` | `28800` | 单条被反代 WebSocket 的授权寿命上限（秒）。能力后置，当前占位 |
| `data_root` | `/opt/bisheng/app-data` | 每应用数据目录的父目录。**必须本机磁盘**（SQLite WAL） |
| `reserve_mb` | `2048` | 容量准入闸①，见下 |
| `overcommit_ratio` | `0.8` | 容量准入闸②，取值 (0, 1] |
| `build_reserve_mb` | `2048` | 构建过闸时按这个数字预留内存 |
| `build_index_url` | `""` | 构建期注入容器的 pip 索引地址；内网 / 离线环境填私有镜像源，留空 = 镜像内默认源 |
| `max_package_mb` | `50` | 上传包体积上限（MB） |
| `max_unpacked_mb` | `200` | 解包后总体积上限（MB），防解压炸弹 |
| `max_package_entries` | `20000` | 包内条目数上限，防海量小文件 |
| `default_tiers` | 不配 | 出厂资源档位覆盖，见下 |
| `preview_ttl_days` | `7` | 审核人临时预览实例存活天数。能力后置，当前占位 |

三个密钥的对应关系一览（**配错的症状全是"看起来在跑但什么都进不去"**，务必核对）：

| config.yaml | 对端环境变量 | 配错的症状 |
|-------------|-------------|-----------|
| `app_runtime.manager_hmac_secret` | runtime-manager 的 `RTM_HMAC_SECRET`<br>app-proxy 的 `APP_PROXY_MANAGER_SECRET` | 所有编排动作返回 16121「应用运行时不可用」，容易被误判成 dockerd 挂了 |
| `app_runtime.proxy_hmac_secret` | app-proxy 的 `APP_PROXY_BACKEND_SECRET` | 每次访问 `/apps/{slug}` 都是兜底页；后端日志里是 401 |
| `app_runtime.obo_secret` | —（只在后端签名，app-proxy 不持有） | 留空只是不注入身份令牌（有告警日志，不影响访问）；与 `jwt_secret` 相同则后端拒绝签发并告警 |

空密钥是 **fail-closed**（拒绝一切调用），不是"免鉴权"。

### 资源档位

不配 `default_tiers` 时用内置三档：**轻量 1C/2G · 标准 2C/4G · 性能 4C/8G**。

⚠️ **档位只在首次启动播种时写库**，之后改 config.yaml 无效（播种按 code 幂等）。
内存吃紧的机器**必须在第一次启动前**就配好，否则只能事后到超管界面逐个改。
配置会**整体替换**内置三档而不是合并——只写两档就只有两档。

```yaml
app_runtime:
  default_tiers:
    light:
      name: "轻量"
      cpu_millicores: 500    # 单位是毫核：500 = 0.5 核
      memory_mb: 512
      description: "内部工具、表单、看板类应用"
      sort_order: 0
    standard:
      name: "标准"
      cpu_millicores: 1000
      memory_mb: 1024
      sort_order: 1
```

### 容量准入：按**实际可用内存**配，不是按总内存

启动实例和构建镜像都要过两道闸，任一不过就返回 16125「运行环境容量不足」，
应用停在「待上线（资源不足）」状态。

- **闸①（此刻真有多少）**：`MemAvailable - reserve_mb ≥ 本次所需`。
  `MemAvailable` 是 `/proc/meminfo` 里内核自己的估算，也就是 `free -m` 的
  **available 列**（不是 free 列，后者会把页缓存算成"已用"而误拒健康的机器）。
  `reserve_mb` 是留给平台本体（uvicorn、三个 celery worker、灵思 worker、
  商业版的 JVM）抖动的余量，**不是保险系数**。
- **闸②（已经许诺出去多少）**：`已运行实例的规格之和 + 本次 ≤ 总内存 × overcommit_ratio`，
  CPU 同理按 `nproc × overcommit_ratio`。挡的是"十个刚起来的应用各用 40MB 都过了闸①、
  等它们热起来机器就没了"。

**构建也走同一道门**（按 `build_reserve_mb` 计），因为 `pip install` 一个没有 wheel 的
包正是那种"什么都还没在跑就把机器压垮"的内存尖峰。

怎么定这几个数：

1. 在目标机器上跑 `free -m`，看 **available** 那一列，记为 A。
2. `reserve_mb` 取 A 的 20%~30%，且不低于 2048。
3. 用 `A - reserve_mb` 除以最常用档位的内存，得到大致能跑几个应用。
4. **轻量档 1C/2G 是安全的**；**性能档 4C/8G 会实打实挤压平台本体**——
   在只有 16GB 且同机跑着 MySQL / ES / Milvus 的机器上，一个性能档实例就足以
   让知识库解析开始 OOM。这类机器建议用 `default_tiers` 把档位整体调小，
   而不是靠调低 `reserve_mb` 硬塞。

## ⚠️ 升级顺序（不可颠倒）

**先发代码 → 再往 config.yaml 加键 → 再全量重启。**

后端加载 config.yaml 时，对**不认识的顶层键直接抛 `KeyError` 拒绝启动**
（`bisheng/common/services/config_service.py` 的 `load_settings_from_yaml`）。
所以把 `app_runtime:` / `open_platform:` 加到还没升级到 v3.0 的镜像上，
后端**起不来**——症状是容器反复重启，日志里一行 `Key app_runtime not found in settings`，
看起来像"升级把平台搞坏了"，实际只是顺序反了。

标准升级步骤：

```bash
# 1. 先把代码 / 镜像升到 v3.0（此时 config.yaml 还是老的，键都认识，能正常起）
cd docker/ && ./deploy.sh update

# 2. 确认后端已经是新版本再改配置
docker compose logs backend | tail -20        # 起来了、健康检查过了

# 3. 加键（app_runtime / open_platform）
vi bisheng/config/config.yaml

# 4. 全量重启：API、三个 celery worker、beat、灵思 worker 一个都不能漏
./deploy.sh restart backend backend_worker

# 5. 起运行时层（compose 会自己建 bisheng-apps 网络）
docker compose --profile app-runtime up -d runtime-manager app-proxy
```

第 4 步**必须是全量重启**：`app_runtime` 是进程级配置，只重启 API 会让 celery
侧仍然认为这一层没装，表现为界面上能操作但后台动作静默不生效。

**回退**：把 `app_runtime.enabled` 改回 `false`、重启后端、
`docker compose --profile app-runtime stop runtime-manager app-proxy` 即可
（**`stop` 也要带 `--profile`**，否则 compose 会说 `no such service`）。
键本身可以留着（新代码认识它），只有降级回 v2.x 镜像时才必须把两块整体删掉或注释掉。

## 整层不装

「不装」是产品明确支持的形态，不需要任何额外操作：

- config.yaml 里两个 `enabled` 保持 `false`（或整块不写）；
- compose 启动时不带 `--profile app-runtime`，两个容器根本不创建；
- nginx 的 `location /apps/` 可以留着——变量式 `proxy_pass` 在上游不存在时
  只让这一个 location 出错，回落到后端渲染的引导页，不影响 nginx 其余部分。

此时的用户可见行为：访问 `/apps/任意` 得到"本环境未启用应用工场"引导页；
CLI 部署被 16207 拒绝并说明原因（不是超时、不是 500）。

## 上线自检

按顺序核对，每一步都能独立定位问题：

```bash
# 1. 两个开关是否透出来（匿名可读）
curl -s http://<host>:3001/api/v1/env | python3 -m json.tool | grep -E 'app_runtime|open_platform'
#    期望：app_runtime_enabled: true, open_platform_enabled: true

# 2. 运行时层自检（需登录态，超管账号）
curl -s -b "access_token_cookie=<token>" http://<host>:3001/api/v1/apps/runtime-status
```

`runtime-status` 返回四类信息，逐条看：

- `backend_available` — 编排后端（dockerd）是否可达；
- `supported_runtimes` — 本部署实际装了哪些运行时模板，v3.0 首发为 `["python3.11"]`；
- `capacity` — 当前容量快照：`total_mb` / `mem_available_mb` / `committed_mb` / `cpu` /
  `committed_cpu` / `reserve_mb` / `overcommit_ratio` / `instances`。`readable=false` 表示
  这台机器的 `/proc/meminfo` 读不到——那本身就是要修的事，不会被折叠成 500；
- `preflight[]` — 五项部署自检，每项直接给出**修复动作**而不是症状：

| 检查项 | 不过的含义 |
|--------|-----------|
| `orchestration_backend` | 连不上 dockerd。检查 socket 挂载 / 运行身份 |
| `application_network` | `bisheng-apps` 网络不存在 → `docker network create bisheng-apps` |
| `data_root_writable` | 数据目录不可写 → 检查 `data_root` / `RTM_DATA_ROOT` 与目录权限 |
| `runtime_templates` | 一个运行时模板都没装（镜像不完整） |
| `base_images` | 基础镜像不在本地。离线环境要**先手动 pull**，否则第一次构建会挂很久然后失败 |

再走一遍端到端：用**非管理员账号**访问一个已上线应用的 `/apps/{slug}`
（管理员会短路权限判定，用管理员验等于没验）。

## 排障对照表

| 症状 | 最可能的原因 |
|------|------------|
| 后端反复重启，日志 `Key app_runtime not found in settings` | 顺序反了：先加的键、后发的代码。见「⚠️ 升级顺序（不可颠倒）」 |
| 升级后**前端全站白屏**（不只是应用打不开） | nginx 里 `location /apps/` 写成了静态 `proxy_pass http://app-proxy:8090`，而 app-proxy 没起 → nginx 整个加载失败 |
| 访问 `/apps/{slug}` 得到"本环境未启用应用工场" | `app_runtime.enabled` 仍是 `false`，或后端没重启 |
| 访问 `/apps/{slug}` 一直是"应用暂时不可用"兜底页 | ①`proxy_hmac_secret` 与 `APP_PROXY_BACKEND_SECRET` 不一致（后端日志 401）；②`APP_PROXY_BACKEND_BASE` 指向了 `127.0.0.1`（在容器里就是它自己） |
| 裸访问 `/apps/{slug}`（不带结尾斜杠）白屏 | 缺 308 跳转，相对路径资源解析到了别的应用。确认 app-proxy 是当前版本 |
| 所有上线 / 下线动作返回 16121「应用运行时不可用」 | `manager_hmac_secret` 与 `RTM_HMAC_SECRET` 不一致（**不是** dockerd 挂了，先查这个） |
| 上线卡在「待上线（资源不足）」 | 容量准入没过。看 `runtime-status` 的 `capacity`，调 `reserve_mb` 或改用更小的档位 |
| 构建一直失败在拉包 | 内网无外网出口 → 配 `build_index_url` 指向私有 pip 源 |
| 应用能跑，但重启后数据没了 | compose 形态漏配 `RTM_HOST_DATA_ROOT`，数据落在了容器内路径对应的宿主目录之外 |
| CLI `bisheng deploy` 报 16207 | 该环境没装运行时层（或 `enabled` 是 false） |
| CLI 拿不到 `app:manage` 能力位 | `open_platform.enabled` 是 `false` |
| 点上线 / 下线"没反应"约 10 秒 | 停容器有固定的 10 秒优雅停机窗口，属正常；不要在这期间重复点 |

日志位置：

```bash
./deploy.sh logs runtime-manager              # 等价于 docker compose --profile app-runtime logs -f
./deploy.sh logs app-proxy
journalctl -u bisheng-runtime-manager -f      # systemd 形态
tail -f /tmp/bisheng-app-proxy.log            # systemd 形态（单元模板里的落盘位置）
```

托管应用自身的日志经平台界面（应用详情 → 日志）与 CLI 查看，保留窗口 =
容器日志轮转窗口（每应用 30MB），产品口径是"最近的运行日志"，不承诺永久留存。

## 备份

除平台本体的备份外，运行时层多这几处（**只有第一行真正需要备份**）：

| 内容 | 位置 | 说明 |
|------|------|------|
| 应用数据 | `{data_root}/apps/{app_id}/db/` | 每个应用的持久化数据，**要备份** |
| 期望态文件 | `{data_root}/state/desired-state.json` | 可丢：进程启动时会从容器标签重建 |
| 构建上下文 | `{data_root}/builds/` | 可丢，纯临时产物 |
| 应用代码包 | MinIO | 随平台对象存储一起备份 |

## 相关文档

- 平台整体部署与升级 -- [`08-deployment.md`](08-deployment.md)
- 系统架构总览 -- [`01-architecture-overview.md`](01-architecture-overview.md)
- 权限体系（谁能看到 / 进入一个托管应用）-- [`10-permission-rbac.md`](10-permission-rbac.md)
- 商业版网关（它只认 `/api`，`/apps` 必须在它前面的 nginx 层直达）-- [`11-gateway.md`](11-gateway.md)
- 配置模板 -- `docker/bisheng/config/config.yaml`
- 配置模型定义 -- `src/backend/bisheng/core/config/app_runtime.py` · `open_platform.py`
