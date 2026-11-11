# 毕昇与昆联集成：Docker / Docker Compose 部署手册

版本：2026-11-11 · 适用：单机 Linux、当前昆联集成分支、含商业 Gateway。

> **本文是部署操作手册，不是部署完成记录。本轮仅编写文档，没有登录服务器、拉取镜像、启动或变更服务。**
> 推荐使用 Docker Engine + Compose V2 插件统一部署，命令写作 `docker compose`。本套 overlay 使用 `!override`，要求 **Compose ≥ 2.24.4**；旧的 Python `docker-compose` V1 不适用。独立二进制 `docker-compose` 若是相同新版本可等价替换命令，不要同时维护两套编排。

## 目录

1. [适用范围与镜像基线](#1-适用范围与镜像基线)
2. [部署架构与准备清单](#2-部署架构与准备清单)
3. [安装 Docker 与 Compose](#3-安装-docker-与-compose)
4. [准备部署目录与镜像](#4-准备部署目录与镜像)
5. [基础服务及 Gateway 配置](#5-基础服务及-gateway-配置)
6. [昆联双端配置与秘密管理](#6-昆联双端配置与秘密管理)
7. [Nginx 与公开入口](#7-nginx-与公开入口)
8. [按顺序启动及启用 SSO](#8-按顺序启动及启用-sso)
9. [验收与三个不变量](#9-验收与三个不变量)
10. [日常操作、备份与回退](#10-日常操作备份与回退)
11. [常见故障](#11-常见故障)
12. [配置核对与交付记录](#12-配置核对与交付记录)

## 1. 适用范围与镜像基线

### 1.1 本次源码核对基线

| 仓库 | 分支 | 本地提交 |
| --- | --- | --- |
| bisheng | `feat/v3.0.0/118-kunlian-integration` | `02b22c810d` |
| bisheng-gateway | `feat/kunlian-integration` | `4e15750f` |

**重要：源码提交不等于镜像制品。** 本地毕昇 HEAD 尚有一个待推提交；另有未提交的目录解析兼容修复（处理上游 `organizations`、`positions`），不能假定 CI 镜像包含它。若正式目录仍返回这两个字段，必须先将修复经评审进入制品，或采用另行批准、带校验和的修复制品；不要靠临时删响应字段、忽略未知字段或挂载不受控源码绕过。

### 1.2 公网仓库与当前分支镜像地址

部署镜像仓库按用户提供的 telemetry 部署参考统一使用 **`cr.dataelem.com`**；仓库名及 tag 保留当前分支命名规则。**这些是本手册指定的公网交付引用，并非已核验的发布结果；本次未查询公网仓库确认各 tag 是否存在、是否包含对应 commit 或构建成功。** 交付方须先将当前分支制品发布或同步到以下引用，再供部署人员拉取。

| 用途 | 当前分支镜像引用 |
| --- | --- |
| API、Worker、Beat、Linsight | `cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration` |
| 前端 Platform + Client + Nginx | `cr.dataelem.com/dataelement/bisheng-frontend:feat_v3.0.0_118-kunlian-integration` |
| 代码沙箱（两个实例共用） | `cr.dataelem.com/dataelement/bisheng-sandbox:feat_v3.0.0_118-kunlian-integration` |
| Gateway AMD64 | `cr.dataelem.com/dataelement/gateway:feat_kunlian-integration` |
| Gateway ARM64（另一个 tag） | `cr.dataelem.com/dataelement/gateway:feat_kunlian-integration-arm64` |

毕昇三类镜像 tag 来自分支名 `/` 替换为 `_`；Gateway ARM64 另加 `-arm64`。毕昇三类流水线没有在本次核查中确认多架构构建，所以**优先使用 Linux AMD64**；ARM 主机必须逐个核验镜像架构，不能仅替换 Gateway。

分支 tag 会被后续构建覆盖，验收后应把 `.env` 中镜像锁定为 `仓库@sha256:...`，并保留同一批次的四类制品与提交记录。不要使用 `latest`，不要把默认旧测试镜像当本分支镜像。

交付方须提供公网镜像的 **引用、digest、架构、源码 commit、CI 构建号**。如果公网 tag 尚不存在，应先发布或同步对应分支镜像；不要让部署人员回退使用内网镜像地址或默认旧版本。不要为取得镜像随意创建普通 `v*` Git tag：Gateway 现有 tag 流水线包含远程部署步骤；功能分支 push 则不部署。

### 1.3 能力边界

- 本手册部署平台基础服务与昆联 SSO / 目录同步链路；配置成功仍需真实账号、映射、菜单及资源权限验收。
- 长任务、人工输入、反向运行控制、授权管理中仅有 Mock 证据的部分，仍按各特性记录判断。**没有一个配置开关可以把正式接口 TODO 变成正式可用。**
- F130 自动开通多租户与基础角色尚未实施。本手册采用现有**人工创建租户 + 显式映射 + 显式最小角色**，不是自动开通全租户。
- 应用工场 `app-runtime`、OnlyOffice、外部模型和文档解析服务不在本手册默认启用范围。需要时另行配置；部署本套服务不会自动获得模型供应商凭据。

## 2. 部署架构与准备清单

```text
浏览器 / 昆联门户
  → 公开 HTTPS 入口（客户反向代理 / 负载均衡）
  → frontend:3001（Nginx，两个 SPA）
  → gateway:8080（License、SSO、HTTP / WebSocket 转发）
  → backend:7860
      ├─ MySQL（bisheng、bisheng_gateway、openfga 三库）
      ├─ Redis（平台 db1 / Celery db2 / Gateway db3）
      ├─ OpenFGA（统一资源权限）
      ├─ MinIO + Milvus + etcd + Elasticsearch
      ├─ backend_worker（队列 Worker + Linsight + 单个 Beat）
      └─ code-runner-1 / 2（独立沙箱网络）

浏览器 → 昆联 authorize / logout
Gateway → 昆联 discovery / token / JWKS
Backend / Worker → 昆联 discovery / JWKS / introspect / 用户目录
```

### 2.1 资源和网络

- 推荐起点：**8 vCPU、32 GiB RAM、200 GiB 可用 SSD**，这是容量规划建议，不是经压测的最低规格或 SLA；按数据量、并发和模型另做容量验证。GPU / 本地模型不包含在这里。
- Linux x86_64；时钟与可信 NTP 同步（签名、Token、目录时效都依赖时间）。检查 `date -Is`、`timedatectl status`。
- 服务器可达镜像仓库、昆联服务；浏览器也必须可达昆联登录与退出端点。
- 公开入口只开放 HTTPS 443（或经批准的业务端口）；模板将中间件与后端端口收敛到 `127.0.0.1`。Docker 发布端口可能绕过简单 UFW 规则，须用宿主防火墙 / 云安全组和实际外网探测复核。
- 使用客户域名示例 `https://workflow.example.com`、IdP 示例 `https://idp.example.com`；必须替换，示例域名不能用于验收。
- 新建独立部署；已有环境不能整份覆盖 Compose、配置和数据目录，先做差异与备份审查。

### 2.2 向双方收集的材料

| 材料 | 提供方 / 要求 |
| --- | --- |
| 四类镜像、digest、架构、构建号 | 毕昇交付方，需包含当前分支相应功能 |
| 有效商业 License 文件 | 毕昇授权方；按其要求提供服务器指纹，本文不复制参考文档中不一致的指纹脚本 |
| client_id、client_secret | 昆联；当前客户端使用 `client_secret_basic`、PKCE S256、`openid profile` |
| issuer、固定端点、RS256 JWKS | 昆联；端点与登记完全一致，不依赖 301 重定向 |
| 允许的 tenant / Workspace、测试 subject | 昆联；全租户目录 Key **不等于** 全租户登录授权 |
| 全租户只读目录 X-API-Key、到期时间 | 昆联；单独保存与轮换，不写入 Git / 手册 |
| 用户与租户 ACTIVE / 停用语义 | 双方确认 `state_semantics_revision` |
| 精确登录 / 退出回调白名单 | 昆联；包含公网协议、域名、非默认端口及固定路径 |
| 最大目录陈旧时间、轮询时间 | 双方运营策略；示例 600 / 300 秒，不是昆联 SLA |

## 3. 安装 Docker 与 Compose

> 以下命令供部署人员在目标服务器执行；本次未执行。安装包来源和系统版本须经过客户准入。命令以 Ubuntu 为完整示例，其他发行版按实际系统选用，不能混用 apt 与 dnf。变更 Docker daemon 配置或重启 Docker 会影响该主机其他容器，须申请窗口。

### 3.1 检查系统和已安装版本

```bash
uname -m
cat /etc/os-release
command -v docker || true
docker --version
docker compose version
```

若已有 Docker / containerd，先确认由谁管理以及有无业务容器，不直接卸载系统包。需要 Compose ≥ 2.24.4；新版本应先通过公司的兼容验证。

### 3.2 Ubuntu：官方软件源方式

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg openssl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf '%s\n' "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
# 先查看可用版本；正式交付按批准版本锁定，而不是无条件跟随升级。
apt-cache madison docker-ce
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

Ubuntu 衍生发行版必须确认对应的上游 Ubuntu codename。Debian 应使用 Docker Debian 软件源，不把上述 URL 原样套用。

### 3.3 RHEL / Rocky / AlmaLinux 与离线安装

RHEL 系列应使用客户批准、匹配发行版的 Docker CE RPM 源或离线 RPM 包。需要安装的组件为 `docker-ce`、`docker-ce-cli`、`containerd.io`、`docker-buildx-plugin`、`docker-compose-plugin`。不要对麒麟 / 统信 / ARM 主机直接套用 CentOS 二进制。

离线环境：在同发行版 / 架构的联网主机准备软件包及全部依赖、校验和，完成软件准入后导入；禁止执行来源不明的一键脚本。若只缺 Compose，可将批准的官方 Compose CLI 插件二进制安装到 `/usr/local/lib/docker/cli-plugins/docker-compose`，赋予执行权限，再用 `docker compose version` 确认。独立二进制也必须满足本手册版本要求。

```bash
sudo systemctl enable --now docker
sudo docker info
sudo docker compose version
# 联网允许时才运行，离线环境可省略此公共镜像测试：
sudo docker run --rm hello-world
```

后续示例假定操作账号已具备 Docker 权限；否则统一在 `docker` 命令前加 `sudo`。将账号加入 `docker` 组等同授予主机 root 级能力，不应对普通业务用户开放。

### 3.4 宿主机参数与镜像仓库

Elasticsearch 通常要求提高 `vm.max_map_count`，示例：

```bash
sudo sysctl -w vm.max_map_count=262144
# 持久化前检查现有同名设置，合并而非覆盖整个 sysctl 配置。
printf 'vm.max_map_count=262144\n' | sudo tee /etc/sysctl.d/90-bisheng-es.conf
sudo sysctl --system
```

按参考文档，部署端统一使用公网镜像仓库 **`cr.dataelem.com`**，通过 HTTPS 登录和拉取。部署人员无需访问 CI 内网仓库，也**无需为本部署添加 `insecure-registries` 或关闭 TLS 校验**。

若访问失败，检查服务器 DNS、出站 HTTPS 443、代理和仓库账号权限；如客户网络使用受控代理 CA，按客户证书策略安装可信 CA，不通过改用 HTTP 解决。公网地址可访问不代表匿名开放，仍可能需要交付账号授权。

镜像登录不在文档写密码，也不使用 `docker login -p`：

```bash
read -r -p '仓库用户名: ' REGISTRY_USER
read -r -s -p '仓库密码: ' REGISTRY_PASSWORD; printf '\n'
printf '%s' "$REGISTRY_PASSWORD" | docker login cr.dataelem.com --username "$REGISTRY_USER" --password-stdin
unset REGISTRY_PASSWORD
# 也可使用交互方式：docker login cr.dataelem.com
# 本手册业务镜像和默认基础镜像均使用此公网仓库，无需登录内网仓库。
```

## 4. 准备部署目录与镜像

### 4.1 目录准备

取得**与交付制品对应**的源码 / 部署配置归档，校验提交或归档 SHA256。本文假定放在 `/opt/bisheng-kunlian/source`，后续相对路径都以其下 `docker/` 为根。

```bash
cd /opt/bisheng-kunlian/source
# 仅对新环境；已有 .env 不覆盖：
test -f docker/.env || cp docker/.env.example docker/.env
chmod 600 docker/.env
install -d -m 700 docker/secrets
# 新增 overlay；其相对路径由第一个 Compose 文件目录解析。
cp docs/deployment-kunlian/compose.kunlian.yml docker/compose.kunlian.yml
cp docs/deployment-kunlian/kunlian-protocol-proxy.inc docker/nginx/kunlian-protocol-proxy.inc
cd docker
```

保留完整目录结构（尤其 `bisheng/entrypoint.sh`、`mysql/conf/`、`redis/`、`nginx/`、`gateway/init.*`）。配置挂载的宿主文件必须先存在，避免 Docker 将本应是文件的路径创建成目录。`DOCKER_VOLUME_DIRECTORY=.` 意味着数据位于当前部署 `docker/` 下；如改成绝对路径，要连同配置子目录一起准备，不只创建一个空数据目录。

### 4.2 修改 `.env` 的镜像及基础变量

编辑已有条目，不在文件末尾反复追加同名键。保持未使用的可选镜像变量有合法值（主 Compose 使用必填插值），但不要启用 `app-runtime` profile。

```dotenv
BISHENG_BACKEND_IMAGE=cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration
BISHENG_FRONTEND_IMAGE=cr.dataelem.com/dataelement/bisheng-frontend:feat_v3.0.0_118-kunlian-integration
BISHENG_SANDBOX_IMAGE=cr.dataelem.com/dataelement/bisheng-sandbox:feat_v3.0.0_118-kunlian-integration
BISHENG_GATEWAY_IMAGE=cr.dataelem.com/dataelement/gateway:feat_kunlian-integration
COMPOSE_PROJECT_NAME=bisheng-kunlian
BISHENG_NETWORK_NAME=bisheng-kunlian-network
COMPOSE_PROFILES=gateway
BISHENG_PRO=true
BISHENG_PUBLIC_URL=https://workflow.example.com
DOCKER_VOLUME_DIRECTORY=.
SANDBOX_CPUS=2
LOCAL_ISOLATION=uid
# 下列值用实际生成值替换，不保留 REPLACE：
MYSQL_ROOT_PASSWORD=REPLACE_RANDOM_HEX
OPENFGA_DATASTORE_URI=root:REPLACE_SAME_MYSQL_PASSWORD@tcp(mysql:3306)/openfga?parseTime=true
MINIO_ROOT_USER=REPLACE_ACCESS_KEY
MINIO_ROOT_PASSWORD=REPLACE_RANDOM_SECRET
SANDBOX_TOKEN=REPLACE_RANDOM_SECRET
```

基础镜像按已核对模板：MySQL 8.0、Redis 7.0.4、OpenFGA v1.15.2-dm、Elasticsearch 8.12.0、etcd v3.5.5、MinIO RELEASE.2023-03-20T20-16-18Z、Milvus v2.5.10；完整引用已在仓库 [.env.example](../../docker/.env.example)。实际交付需确认这些旧版本符合客户安全准入，不能静默升级数据引擎。

每个秘密分别使用 `openssl rand -hex 32` 生成。建议数据库密码用 hex，避免 DSN 特殊字符转义。MinIO 用户名也用独立随机值；MinIO、后端、Worker、Milvus 由主 Compose 统一取同一份凭据。已有数据的 MySQL / MinIO **不能仅改环境变量就当作完成密码轮换**：MySQL 初始化变量不修改既有账号。

### 4.3 预拉取、验证架构及固化镜像

配置 overlay 的 env 文件还未创建前，先单独拉取上述四类镜像，确认不存在 `manifest unknown`、权限或架构错误。示例：

```bash
docker pull cr.dataelem.com/dataelement/bisheng-backend:feat_v3.0.0_118-kunlian-integration
docker pull cr.dataelem.com/dataelement/bisheng-frontend:feat_v3.0.0_118-kunlian-integration
docker pull cr.dataelem.com/dataelement/bisheng-sandbox:feat_v3.0.0_118-kunlian-integration
docker pull cr.dataelem.com/dataelement/gateway:feat_kunlian-integration
docker image inspect cr.dataelem.com/dataelement/gateway:feat_kunlian-integration \
  --format '{{.Os}}/{{.Architecture}} {{json .RepoDigests}}'
```

对四类镜像逐个 inspect，填写交付表，再把 `.env` 引用替换为所核验 digest。镜像无 commit label 时必须向 CI 取得构建来源，不能把拉取时间当作源码证明。

离线交付：在可信、同架构联网主机对**所有启用服务**拉取后 `docker save -o bisheng-images.tar <全部镜像引用>`，生成 SHA256；拷贝后 `sha256sum -c`、`docker load -i`。`save`/`load` 不含数据库、配置、卷与 License，须独立交付。离线启动阶段不要再执行会联网的 `pull`。

## 5. 基础服务及 Gateway 配置

### 5.1 Compose 变量与应用配置不是同一层

| 配置 | 读取方 | 作用 |
| --- | --- | --- |
| `docker/.env` | Compose CLI | 镜像、profile、变量插值；**不会把全部变量自动注入容器** |
| `secrets/kunlian-backend.env` | API / Worker `env_file` | 后端昆联五个秘密 |
| `secrets/kunlian-gateway.env` | Gateway `env_file` | 网关昆联三个秘密 |
| `bisheng/config/config.yaml` | 后端 `/app/bisheng/config.yaml` | SQL / Redis / OpenFGA / SSO 等；只读挂载 |
| `gateway/config/application.yml` | Gateway `/application.yml` | Spring / 路由 / License / 昆联；只读挂载 |
| `nginx/conf.d` 或生成目录 | 前端 Nginx | 页面、API、WebSocket、SSO 协议路由 |

后端 `!env ${VAR}` 是 YAML 的环境变量标签；昆联 `env:VAR` 是**秘密引用字符串**。二者不能互换。后端旧镜像遇到不认识的顶层键可能直接拒启，先确认镜像支持 F118，才合入新增节点。

### 5.2 MySQL、Redis、OpenFGA

1. 修改后端配置的 `database_url`，用户名 / 库名使用本环境实际值。该字段密码段要求**项目 `encrypt_token` 生成的密文**，不能填明文，也不能用本手册新生成的昆联 Fernet key 加密。可用交付后端镜像在隔离运行中生成（不连接业务服务）：

```bash
# 用已拉取的后端完整镜像引用或 digest 替换 IMAGE；交互输入不进历史。
docker run --rm -it --network none --entrypoint python IMAGE -c \
 'import getpass; from bisheng.core.config.settings import encrypt_token; print(encrypt_token(getpass.getpass("MySQL password: ")).decode())'
```

将输出填入：

```yaml
database_url: "mysql+pymysql://root:REPLACE_ENCRYPTED_PASSWORD@mysql:3306/bisheng?charset=utf8mb4"
redis_url: "redis://redis:6379/1"
celery_redis_url: "redis://redis:6379/2"
openfga:
  enabled: true
  api_url: "http://openfga:8080"
```

项目内置密码密文只能视为兼容存储格式，并非独立秘密保险箱；配置文件仍按敏感文件保护。生产宜由 DBA 提供最小权限账号，不能未经验证直接撤销迁移所需 DDL 权限。

2. `.env` 中的 `MYSQL_ROOT_PASSWORD`、`OPENFGA_DATASTORE_URI` 与后端解密后的数据库密码须一致。overlay 同时覆盖主 Compose 中的旧默认密码、OpenFGA 与网关初始化连接；**只写 MYSQL_ROOT_PASSWORD 但不使用 overlay 不会覆盖模板硬编码值**。
3. Redis 当前模板是同机私网、无密码方式，已由 overlay 限制宿主端口为回环。需要 Redis ACL / 密码时，须同步 Redis 配置、健康检查、后端两条 URL（按项目要求加密密码）及 Gateway `spring.data.redis.password`（原始密码 / 环境引用），然后逐项验证。不能只改其中一个。
4. OpenFGA 必须运行且完成 migrate / 权限模型初始化。容器启动不证明权限可用，务必用非管理员验证列表与详情；不要为消除报错关闭 OpenFGA。

### 5.3 MinIO、检索与沙箱

主 Compose 将 MinIO / ES / Milvus 容器内地址注入 API、Worker；同网络服务地址为 `mysql`、`redis`、`openfga`、`minio`、`milvus`、`elasticsearch`，**不是 `127.0.0.1`**。`127.0.0.1` 在容器里表示该容器自身。

- MinIO 数据 API `9000`，宿主回环 `9100`；控制台 `9001` 不发布。公网下载由前端代理；如外部 Office / 文档服务需取文件，另行配置可达的 `BS_MINIO_SHAREPOINT` 与 TLS，不直接公开管理台。
- 沙箱是同一镜像的 `code-runner-1` / `code-runner-2`，各用独立 `/sessions` 目录；后端与 Worker 的 token 必须与 runner 一致。`SANDBOX_CPUS` 不得超过宿主机 CPU 数。
- 沙箱不发布端口、不加入中间件网络；保留只读根目录、能力收敛与资源限制，不为排障改为 `privileged` 或挂载 Docker socket。
- 不依赖应用工场的 Workflow 场景，不启用 `app-runtime`。

### 5.4 Gateway 的 License 和基础字段

采用毕昇主仓统一 Compose 的 `gateway` profile，**不要另启 Gateway 仓库旧版 Compose**，否则会撞容器名、网络或错误使用 `v1.0.0` 镜像。

先准备批准的 License（示例 `/opt/bisheng-kunlian/secrets/license.txt`，权限 0600）。在源码根目录只生成配置，不启动：

```bash
cd /opt/bisheng-kunlian/source
bash docker/install.sh --prepare-only --gateway \
  --license-file /opt/bisheng-kunlian/secrets/license.txt \
  --public-url https://workflow.example.com
cd docker
```

该操作会生成 Gateway DB 密码与 HMAC、将 License 文本写入 `.env` 的 `BISHENG_GATEWAY_LICENSE`，并生成专属 Nginx 目录。后续不要再次无参数运行安装脚本以替代本文启动命令：它不自动叠加本文 overlay，也可能重新生成 Nginx 目录。

确认以下配置已生成：

```dotenv
COMPOSE_PROFILES=gateway
BISHENG_PRO=true
BISHENG_GATEWAY_LICENSE_FILE=/opt/bisheng-kunlian/secrets/license.txt
BISHENG_GATEWAY_LICENSE=REPLACE_REAL_LICENSE_FROM_PREPARE
BISHENG_GATEWAY_HMAC_SECRET=REPLACE_GENERATED_SECRET
BISHENG_GATEWAY_DB_PASSWORD=REPLACE_GENERATED_SECRET
BISHENG_PUBLIC_URL=https://workflow.example.com
BISHENG_NGINX_CONF_DIR=REPLACE_GENERATED_ABSOLUTE_DIRECTORY
```

不要把占位符覆盖掉脚本生成的真实值。`BISHENG_LICENSE` 是**容器内**变量，由主 Compose 从 `BISHENG_GATEWAY_LICENSE` 注入；源码读取 `bisheng.license`，仅挂 License 文件而不注入内容不够。空 / 过期 / 无效 License 可能返回 **HTTP 200 + 业务码 11001**，不要误判为 SSO 正常。

保留基础 Gateway 配置的以下关系：

- HTTP route → `http://backend:7860`；WebSocket route → `ws://backend:7860`。
- `bisheng.bisheng-api-url` → `http://backend:7860`；昆联 `backend-base-url` 是另一独立字段，也要相同可达。
- `spring.datasource.url` → `jdbc:mysql://mysql:3306/bisheng_gateway?...`，用户 `bisheng_gateway`，密码 `${GATEWAY_DATABASE_PASSWORD}`。
- `spring.data.redis.host=redis`、`port=6379`、`database=3`。
- `SPRING_CONFIG_LOCATION=file:/application.yml` 已由 Compose 指定，因此外部配置是完整入口，不自动继承 JAR 内部示例配置。
- 统一的 [Gateway 初始化 SQL](../../docker/gateway/init.sql) 已含基础表、拦截记录及部门表；不要再照旧版网关文档重复执行不带库名的更新脚本。
- `BISHENG_GATEWAY_HMAC_SECRET` 是旧 Gateway 同步链路的共享密钥；它**不等于**昆联内部签名密钥。

本套统一外部配置没有新版 DSH 专用路由；纯昆联不受此项阻碍。若同时启用 DSH 内容安全，需要另行合并当前 Gateway 分支专用 route，不能据本文宣称网关所有可选能力均已覆盖。

## 6. 昆联双端配置与秘密管理

### 6.1 生成秘密并显式注入

需要的容器环境变量：

| 变量 | 后端 / Worker | Gateway | 来源与格式 |
| --- | --- | --- | --- |
| `KUNLIAN_CLIENT_SECRET` | 是 | 是 | 昆联提供；两端相同 |
| `KUNLIAN_SYNC_API_KEY` | 是 | 否 | 昆联提供全租户只读目录 Key |
| `KUNLIAN_INTERNAL_SECRET` | 是 | 是 | 毕昇生成，`openssl rand -hex 32`，两端相同 |
| `KUNLIAN_BACKEND_CSRF_SECRET` | 是 | 否 | 独立 `openssl rand -hex 32` |
| `KUNLIAN_BACKEND_FERNET_KEY` | 是 | 否 | URL-safe Base64 的 Fernet key，解码 32 字节 |
| `KUNLIAN_GATEWAY_TRANSACTION_KEY` | 否 | 是 | **标准 Base64**，解码恰好 32 字节，`openssl rand -base64 32` |

每个用途用不同的随机值。API 与全部 Worker 必须共享同一后端 Fernet key；全部网关共享同一事务密钥与 Redis 库。两端共享字段一致，其余秘密不得复用；不要把 License、密码密文或旧 HMAC 拿来顶替。

创建以下两个文件（使用受控编辑器 / 密钥系统写入，不将真实值粘贴到工单）：

```dotenv
# docker/secrets/kunlian-backend.env
KUNLIAN_CLIENT_SECRET=REPLACE_FROM_KUNLIAN
KUNLIAN_SYNC_API_KEY=REPLACE_FROM_KUNLIAN
KUNLIAN_INTERNAL_SECRET=REPLACE_SHARED_RANDOM_HEX
KUNLIAN_BACKEND_CSRF_SECRET=REPLACE_DISTINCT_RANDOM_HEX
KUNLIAN_BACKEND_FERNET_KEY=REPLACE_URLSAFE_BASE64_32_BYTES
```

```dotenv
# docker/secrets/kunlian-gateway.env
KUNLIAN_CLIENT_SECRET=REPLACE_SAME_CLIENT_SECRET
KUNLIAN_INTERNAL_SECRET=REPLACE_SAME_INTERNAL_SECRET
KUNLIAN_GATEWAY_TRANSACTION_KEY=REPLACE_STANDARD_BASE64_32_BYTES
```

生成后端 Fernet key 可用已拉取后端镜像，不安装宿主 Python：

```bash
docker run --rm --network none --entrypoint python IMAGE -c \
 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
chmod 600 .env secrets/kunlian-backend.env secrets/kunlian-gateway.env
```

Env 文件遇到 `$`、`#`、引号等特殊字符须按 Compose env_file 规则转义 / 单引号引用，部署前核对值未被插值改变，但不要打印秘密。env_file 是容器环境注入，不是加密保险箱；Docker 管理员可 inspect 环境，须控制主机和 Docker 权限。不要执行 `source` 未审查的外部 env 文件。

### 6.2 后端配置

将 [后端片段](backend-kunlian.fragment.yaml) **逐项合并**到现有后端配置，不直接用片段覆盖整个文件；已有 `sso_sync` / `multi_tenant` 时只补子键。初始化保持 `directory_enabled=true`、`login_enabled=false`，策略从读取到的当前值递增；全新环境示例为 revision 1。

### 6.3 Gateway 配置

将 [网关片段](gateway-kunlian.fragment.yaml) 合并到现有 Spring 配置。新环境可增加 `custom.kunlian`，已有 `custom` 则同层合并。无需复制空 `wxoauth` / `ssoconfig` / `ldap`，这些不是昆联前置，空节点还可能触发旧配置解析失败。

初始化保持 `custom.kunlian.enabled=false`。当前分支网关没有需要宿主 JDK 的额外步骤，镜像内 Java 17 直接启动 JAR；不需要在宿主执行 Maven。

### 6.4 必须填写且双端一致的参数

| 后端键（`sso_sync.kunlian`） | 网关键（`custom.kunlian`） | 要求 |
| --- | --- | --- |
| `connection_id` | `connection-id` | 同一个稳定本地连接标识，不随重启改变 |
| `issuer` | `issuer` | 昆联登记的规范 Origin，discovery 返回 issuer 必须一致 |
| `client_id` | `client-id` | 同一客户端 |
| `allowed_tenant_id` | `allowed-tenant-id` | **当前实现是单个允许租户**，不是自动接受所有目录租户 |
| `allowed_workspace_ids` | `allowed-workspace-ids` | 昆联确认的允许范围，两端一致 |
| `public_origin` | `public-origin` | 浏览器最终入口，协议 + 小写域名 + 必要非默认端口；无路径、结尾 `/`、query |
| `redirect_uri` | `redirect-uri` | `PUBLIC_ORIGIN/api/kunlian/callback` |
| `logout_redirect_uri` | `logout-redirect-uri` | `PUBLIC_ORIGIN/api/kunlian/logout/callback` |
| `internal_key_id` | `internal-key-id` | 同一 KeyID，字符 `[A-Za-z0-9._-]`，长度 1–64 |
| `internal_secret_reference` | `internal-secret-reference` | `env:KUNLIAN_INTERNAL_SECRET` |

**其余关键参数：**

- 后端 `endpoint_allowlist`：discovery、JWKS、introspect、用户分页、单用户模板路径；网关列表为 discovery、authorize、token、JWKS、logout。路径不能随意缩短成域名白名单，实际值见两个片段。
- 网关 `backend-base-url=http://backend:7860`，HTTP 私网服务 Origin 还须列入 `approved-service-origins`。
- 正式环境 HTTPS、`approved_test_origins` / `approved-test-origins` 为空；若获批 HTTP 测试，**两端都要**精确加入 IdP 和站点 HTTP Origin（含非默认端口）。不要加 `*`、整个网段或生产 HTTP 例外。
- 浏览器会规范化默认端口，Origin 不显式写 HTTPS `:443` / HTTP `:80`。示例生产域名使用证书受信的 HTTPS；不是把协议改成 https 就算完成证书部署。
- 后端 `state_semantics_revision` 填双方确认的状态规则版本，不填 `REPLACE`。`sync_interval_seconds=300`、`page_size=20` 为当前样例；`max_directory_age_seconds=600` 是拒绝阈值，不是上游保证。
- 后端 `trusted_gateway_networks` 必须是后端实际看到的 Gateway 对端地址；不要信任整个 Docker 网段。全新启动前可临时保留片段中的保留地址（此时登录关闭，无法放行实际来源），待网关建立后检查并替换为实际 `/32`：

```bash
docker inspect bisheng-gateway --format '{{json .NetworkSettings.Networks}}'
```

若网关有多网络，选择与后端共用网络的地址，并结合实际请求来源复核；重建 Gateway 后必须再次检查。不要对既有自动分配网段擅自加静态地址（Docker 可能拒绝），也不要为固定一个 IP 重建共享网络。

## 7. Nginx 与公开入口

### 7.1 普通 API 与 WebSocket

安装器生成的 Gateway 专用 Nginx 配置应把普通 API 和 WebSocket 代理指向 `gateway:8080`，而非继续直通后端。`/workspace/api/...` 先剥去 `/workspace`；对外不增加 `/gw` 或 `/ws` 前缀。

公开入口可以由外层负载均衡终止 TLS，转发到宿主 3001；应保留 `Host`（含公开非默认端口）、原始协议与 WebSocket Upgrade。仅允许可信外层代理访问此端口，清洗客户端伪造的转发头。需要避免直连时，可在主 Compose 的部署副本中把前端端口改为 `127.0.0.1:3001:3001`（外层反代同机）或绑定指定私网 IP。

### 7.2 四个协议入口与日志保护

将 [SSO Nginx location 片段](nginx-kunlian-locations.conf) 插入 `.env` 中 `BISHENG_NGINX_CONF_DIR` 指向的 `default.conf` 的 **`server { listen 3001; ... }` 内部**；不能放在 http 顶层，也不能替换整份配置。代理公共片段由 [Compose overlay](compose.kunlian.yml) 挂载到 `/etc/nginx/kunlian-protocol-proxy.inc`。

四个精确路径：

| 方法 | 路径 | 处理方 |
| --- | --- | --- |
| GET | `/api/oauth2/kunlian` | Gateway 发起授权 |
| GET | `/api/kunlian/callback` | Gateway 处理登录回调 |
| POST | `/api/kunlian/logout` | Gateway 处理已签发的一次性退出票据 |
| GET | `/api/kunlian/logout/callback` | Gateway 处理退出回调 |

这些端点不能转发到后端普通 `/api/v1` 路由；不能添尾斜杠。禁止在任何边缘代理、WAF、APM / Nginx access/error log 中记录这些请求的 query / body（含 code、state、ticket），也不打开 Spring HTTP wire DEBUG 日志。提供的片段对四入口关闭访问日志并丢弃 Nginx 错误日志，故障诊断改用稳定错误码、时间和关联 ID，不记录协议原文。

`POST logout` 由应用的统一退出流程产生同源请求与票据，不用 GET 链接或 JWT 代替；`Origin` 必须精确匹配公网 Origin。需要回滚 SSO 时也应保留退出协议处理能力。

## 8. 按顺序启动及启用 SSO

### 8.1 统一 Compose 命令入口

以下均在 `source/docker` 执行。每次都带主文件和 overlay，避免遗漏秘密注入 / 端口收敛。可在同一个 Bash 会话定义：

```bash
DC=(docker compose --env-file .env -f docker-compose.yml -f compose.kunlian.yml)
"${DC[@]}" config --quiet
"${DC[@]}" config --services
"${DC[@]}" config --images
```

`config --quiet` 只检查编排，不检查真实秘密格式、License、IdP 网络或数据库权限。不要把完整 `compose config` / `docker inspect`（含环境秘密）公开上传；`config --images` 仅用于核对引用。

### 8.2 启动基础服务、迁移与 API

```bash
# 联网环境：先拉齐全部依赖镜像，失败就停止，不自动降级旧版本。
"${DC[@]}" pull
"${DC[@]}" up -d mysql redis etcd minio elasticsearch
"${DC[@]}" ps
# 一次性 migrate 预期正常退出0，不要求一直Running。
"${DC[@]}" up -d openfga
"${DC[@]}" logs --tail=100 openfga-migrate openfga
"${DC[@]}" up -d milvus
"${DC[@]}" up -d backend
"${DC[@]}" logs --tail=100 backend
curl --fail --silent --show-error http://127.0.0.1:7860/health
```

API 入口脚本先 `alembic upgrade head`，失败即拒绝启动。升级前先备份，不直接照日志建议在生产执行 `alembic merge heads`；发现多 heads 应由研发产出受审查迁移，而非运维现场改历史。

确认 API 迁移完成后再启动 Worker：

```bash
"${DC[@]}" up -d backend_worker
"${DC[@]}" logs --tail=100 backend_worker
"${DC[@]}" up -d code-runner-1 code-runner-2
```

默认 `backend_worker` 是组合启动模式（含 Worker、Linsight、Beat），**只运行一个 Beat**。不能用复制两个组合容器的方式做高可用，否则会重复调度；跨 Worker 验收需要专门拆分队列消费者与独立 Beat。

### 8.3 启动 Gateway、复核来源、启动前端

```bash
"${DC[@]}" up -d gateway
"${DC[@]}" ps -a
"${DC[@]}" logs --tail=100 gateway-db-init gateway
# 查看网关实际peer IP并更新后端 trusted_gateway_networks；仍保持双端登录关闭。
docker inspect bisheng-gateway --format '{{json .NetworkSettings.Networks}}'
# 修改配置后重建API和Worker；env_file更改仅restart不会加载新环境。
"${DC[@]}" up -d --force-recreate backend backend_worker
# 先用一次性容器检查配置（不发布业务端口），避免错误配置令前端反复退出。
"${DC[@]}" run --rm --no-deps --entrypoint nginx frontend -t
"${DC[@]}" up -d frontend
"${DC[@]}" exec frontend nginx -t
```

Gateway 没有镜像健康检查，`Up` 不能视为就绪；查看 License、SQL / Redis 连接和协议运行时日志。Gateway DB 初始化容器预期 `Exited (0)`；失败时停止排查，不跳过表初始化。

### 8.4 人工租户映射、目录同步、最小权限

以本地全局管理员从 `/admin-login` 登录。管理员用于控制面，**验收业务时换普通昆联用户**。

1. 通过现有租户管理功能创建本次独立本地租户，记录实际正整数 ID；不复用文档里的历史 ID，不把默认租户历史资产迁走。
2. 通过现有管理 API 显式绑定允许的外部租户。控制面前缀为 `/api/v1/identity-integrations/kunlian`，要求当前全局管理员身份。
3. 新绑定 `expected_revision=null`；更新已有绑定时先 GET，使用返回的 revision 乐观并发校验，不能盲写。

示例（用受限 Cookie jar 替换占位符，不把 Token 写命令历史；Cookie 来源于正常本地管理员登录）：

```bash
# COOKIE_JAR 文件须0600，且仅用于受控管理机；PUBLIC_ORIGIN与ID替换为实际值。
curl --silent --show-error --cookie "$COOKIE_JAR" \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/tenant-bindings/$EXTERNAL_TENANT_ID"
curl --silent --show-error --cookie "$COOKIE_JAR" -X PUT \
  -H 'Content-Type: application/json' \
  --data '{"local_tenant_id":2,"expected_revision":null,"enabled":true}' \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/tenant-bindings/$EXTERNAL_TENANT_ID"
curl --silent --show-error --cookie "$COOKIE_JAR" -X POST \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/sync"
curl --silent --show-error --cookie "$COOKIE_JAR" \
  "$PUBLIC_ORIGIN/api/v1/identity-integrations/kunlian/status"
```

示例 `2` 必须换成第 1 步实际创建的本地租户 ID；这不是预置值。HTTP 202 仅表示同步已请求，等待 Worker、完整目录批次 `PUBLISHED` 与目标映射 `materialized=true`、目标用户投影 `SUCCEEDED`，不能只看请求返回。

4. 对目标影子用户通过既有角色 / 菜单管理显式授予工作流管理入口与新建资格（常见菜单为 `admin`、`build`、`create_app`）；其中 `admin` 仅表示后台入口菜单，**不授予全局超级管理员身份**。查看、编辑、发布、运行等资源动作仍按现有权限独立判断。
5. 全租户目录存在未映射用户时整体诊断可能 `UNMAPPED`，不得为消除告警把全部租户自动映射。应明确目标试点绑定与用户就绪；与全量目录的未映射范围分别记录。

### 8.5 开放登录：先后端策略，再 Gateway

- 先读取 status / 当前 SQL 政策的 `policy_revision`。全新示例由 1 提升为 2；已有环境使用**当前值 + 1**，不固定回写 2。
- 后端 `login_enabled=true` 且提升 `policy_revision`，所有 API / Worker 使用同一配置；重建后通过控制面请求同步 / 等待调度，使更高策略进入权威状态并再次核验。
- 确认目录、映射、用户、最小菜单、FGA 均满足，再设 Gateway `custom.kunlian.enabled=true`，重建 Gateway。
- 重建 Gateway 后再次复核 IP，必要时更新后端可信 `/32` 并重建 API / Worker，之后才引流。

```bash
"${DC[@]}" up -d --force-recreate backend backend_worker
# 控制面执行同步并核验新策略与投影后：
"${DC[@]}" up -d --force-recreate gateway
# 复核网关peer；Nginx静态上游在网关重建后应重新解析：
"${DC[@]}" exec frontend nginx -t
"${DC[@]}" exec frontend nginx -s reload
curl --silent --show-error "$PUBLIC_ORIGIN/api/oauth2/list"
```

列表出现 `kunlian` 只证明网关配置和客户端对象已构建，不证明后端目录、网络与权限已全部就绪。

## 9. 验收与三个不变量

### 9.1 基础与 SSO 验收

| 检查 | 预期 / 记录 |
| --- | --- |
| 容器状态 | 基础服务运行，迁移 / 初始化容器退出 0；API health 成功 |
| 普通用户权限 | 非管理员能看列表且能读自有详情，不是“列表200但为空” |
| 原管理员 | `/admin-login` 正常，不破坏默认租户 |
| 管理页直达 | 新浏览器打开 `/build/workflows`，完成昆联认证回原页 |
| 编辑页直达 | `/flow/<id>?from=workflow-management&entry=kunlian` 保留有权访问的目标 |
| 身份 | 实际 subject / 本地用户 / 本地租户正确，`is_global_super=false` |
| 隔离 | 不能读取、编辑他人 / 其他租户资源；不泄露内容 |
| 新建 | 在目标本地租户创建自己的 Workflow，记录 ID，不默认删除验收资产 |
| 定时同步 | 等待至少一轮调度，批次版本推进，目录年龄符合政策 |
| 统一退出 | 应用正规退出流程完成双方回调，旧 Cookie 重放被拒 |
| 停用 / 撤权 | 分别测试上游停用、当前用户资格或资源撤权；未执行保持 NOT_RUN |
| 凭据泄漏 | 边缘和应用日志不含 code / state / ticket / Token / client_secret |

### 9.2 每批必须复验的三个 Workflow 不变量

这些是**受控环境验收步骤**，不是本文已完成测试。正式接口未装配时只能标 Mock 范围，不把正式运行写成 PASS。

1. **固定版本 V1**：发布并启动 V1，保存 run / dispatch / version 标识；发布 V2 后让旧运行继续与重连，检查旧运行仍绑定 V1，新运行才按明确选定版本执行。
2. **跨 Worker 接管**：在独立 Worker A / B 测试拓扑、共享 SQL / Redis 下，启动可恢复任务并记录派发 ID；故障注入退出 A，让 B 接手，核对**同一个派发 ID**、不重启远端 Run。不要在生产用 `kill` 做探测，也不要复制含 Beat 的组合 Worker 来模拟双 Worker。
3. **下游只输出一次**：在隔离测试注入落库事务回滚与通知丢失，等待重试 / 对账，按同一 dispatch 与下游业务键核对最终仅有一条落库结果；仅看 UI 一条消息不足以证明幂等。

记录图 / 发布版本、run ID、派发 ID、A/B 日志关联、注入点、数据库计数与结果。缺少正式适配、双 Worker 或故障夹具时写 `NOT_RUN`，不要以健康检查、单进程 Mock 或一次成功代替。

## 10. 日常操作、备份与回退

### 10.1 查看状态与重载

```bash
# 同一 Bash 会话保留DC数组；新会话按8.1重定义。
"${DC[@]}" ps -a
"${DC[@]}" logs --tail=100 backend backend_worker gateway
"${DC[@]}" logs --tail=100 mysql redis openfga
"${DC[@]}" exec frontend nginx -t
"${DC[@]}" exec frontend nginx -s reload
```

配置挂载内容更改需按读取机制重启 / 重建；环境文件、镜像或 Compose 更改需 `up -d --force-recreate <service>`，不是单纯 `restart`。只读文件挂载若用编辑器原子替换，容器可能仍看到旧 inode，应重建对应容器。后台组合 Worker 的某个子进程异常不一定使容器退出，须看队列、Beat 与同步进度，而非只看 `Up`。

### 10.2 备份

升级 / 开放 SSO 前，备份：

- `.env`、两个秘密 env、License、后端与网关完整配置、生成后的 Nginx、Compose 与 overlay；目录 0700、文件 0600，不进入 Git 或交付公共附件。
- MySQL 三个库（业务、Gateway、OpenFGA）的一致性备份；OpenFGA 只备业务库不够。建议由 DBA 通过受限 defaults 文件执行 `mysqldump --single-transaction --routines --triggers`；避免在命令行 `-p<password>`。含非事务表 / DDL 并发时需额外一致性方案。
- Redis 按 RDB / AOF 策略一致性备份（含会话与任务状态），MinIO / Milvus / etcd / ES 按各引擎支持的备份方式处理；不能直接在线复制活跃数据库目录当作可恢复备份。
- 四类镜像 digest、镜像归档、数据目录容量与权限，以及恢复演练记录。

恢复必须演练，不把“导出成功”写成“可恢复验证通过”。备份包含身份和业务秘密，应加密与限定访问。

### 10.3 升级及回退

- 升级前先拉齐新镜像、检查完整配置兼容性与数据库迁移，再安排窗口切换；不要拉取到一半就重建部分服务。
- 分支 tag 必须记录切换前后 digest。多实例启动迁移需按运维方案串行，不能临时让多台 API 竞争 Schema 变更。
- 普通容器停止可用 `"${DC[@]}" stop <service>`，不会删除数据。不要执行 `down -v`、`docker system prune --volumes` 或直接删除数据目录。
- SSO 安全回退：先在入口**仅阻断新登录 GET `/api/oauth2/kunlian`**或停止新登录引流，以**更高后端策略版本**关闭登录、确认权威状态禁用且旧会话被拒。退出窗口内保持 Gateway `custom.kunlian.enabled=true`、现有退出路由与秘密，让退出和回调仍可处理；窗口结束后才按批准方案停用整个网关昆联运行时。当前网关四个协议入口共用一个运行时，直接设 `enabled=false` 会连退出端点一起关闭，不能声称仍保留退出能力，也不能只改文件就声称旧会话失效。
- 不直接降到不识别昆联身份的旧镜像；不随意关闭多租户；不删除新用户、人工授权、映射和 Workflow。涉及 Schema 降级或全库恢复必须另行评审，避免覆盖部署后的新数据。
- 密钥轮换会影响已有密文与事务：后端 Fernet key 变更影响持久会话解密，Gateway 事务 key 变更影响进行中授权；须按停流 / 撤销 / 重新登录方案执行，不擅自声称支持无缝多 key 轮换。

## 11. 常见故障

| 现象 | 优先检查 / 处理 |
| --- | --- |
| `manifest unknown` / 403 | 分支 tag 尚未构建、目标仓库未同步或账号权限不足；停止，不自动用旧镜像代替 |
| `server gave HTTP response to HTTPS client` / TLS 错误 | 本手册仓库应为 `cr.dataelem.com` 的 HTTPS；检查地址、代理和证书配置，不添加内网 HTTP 仓库或全局关闭 TLS |
| `exec format error` | 架构不匹配；逐个核对四类与基础镜像，不只看 Gateway 后缀 |
| Compose 不识别 `!override` | 版本低于 2.24.4；升级批准的 Compose，不删除端口保护标签后直接上线 |
| 挂载失败 `not a directory` | 宿主配置不存在 / 被建成目录；检查绝对路径，不盲删数据 |
| 后端反复重启 / KeyError | 新配置配旧镜像、秘密缺失或迁移失败；看精确错误，不关闭校验 |
| Gateway HTTP 200 但业务 11001 | License 空、失效或无效；检查文本实际注入而非仅挂文件 |
| Gateway 连接 `127.0.0.1:7861` | 沿用网关旧模板；统一设置 route / bisheng-api-url / Kunlian backend-base-url |
| `/api/oauth2/list` 无 kunlian | Gateway enabled、三个秘密格式 / 差异、客户端配置；出现也不代表完整网络就绪 |
| 回调返回 SPA 页面 / 404 | 协议未进 Gateway、错误 location 作用域或错误路径；检查实际 Nginx 加载配置 |
| 19324 / 依赖未就绪 | 配置与秘密、公开 Host / Origin、SQL / Redis / IdP、后端装配；不把日志降级成“正常” |
| `DIRECTORY_NOT_READY` / 陈旧 | Beat / Celery、目录 Key、时钟、批次完整性、映射和投影；不是清缓存即可解决 |
| `INVALID_DIRECTORY` 且含 organizations / positions | 当前镜像可能未含本地兼容修复；重新交付受审查制品，不去掉严格校验 |
| 内部签名失败 | KeyID / 内部 secret 两端一致、系统时间、nonce Redis、网关真实peer `/32`；不扩大可信网段 |
| 新用户无法登录 / 缺菜单 | 当前不是自动开通版本，核查显式本地映射、用户投影与最小角色 |
| 列表能看、详情403 | 用普通用户核查 OpenFGA 运行时 / 可见性投影，不能以超管结果代表权限正常 |
| 任务排队不执行 | Worker 队列以 `workflow_celery` 开头、实际子进程存活、Beat 单实例、SQL / Redis一致 |
| 沙箱不可用 | Token 一致、两个 endpoint、镜像架构、CPU限制、目录权限；不放宽容器权限掩盖问题 |
| 改 `.env` 无效 | Compose未自动注入全部变量，检查environment / env_file；变更后重建而非只restart |

## 12. 配置核对与交付记录

### 12.1 部署前检查表

- [ ] 已批准本次服务器、窗口、备份与回退；本文不构成远程部署授权。
- [ ] Engine 可用、Compose ≥ 2.24.4、架构与四类镜像一致。
- [ ] 镜像全部可拉取 / 已离线导入；源码、CI号与 digest 对应，目录兼容修复已进入制品。
- [ ] 默认旧镜像、测试密码、示例域名 / ID / 保留peer地址已替换。
- [ ] `.env`、License 与秘密文件权限受控；没有秘密进入 Git / 工单。
- [ ] 双端 issuer / client / tenant / Workspace / 公网Origin / 回调 / KeyID一致。
- [ ] 三套签名 / 加密用途分离，两个相应共享秘密一致；实际peer `/32`已核实。
- [ ] 公开端只通入口；中间件、后端与沙箱没有意外暴露。
- [ ] Nginx四协议路由正确，全部代理层日志不会泄漏协议材料。
- [ ] 先目录与人工映射 / 权限就绪，再更高策略开启登录。

### 12.2 验收记录表（由实际执行人填写）

| 项目 | 结果 / 证据 |
| --- | --- |
| 服务器 / OS / 架构 / Engine / Compose | 待填写 |
| 四类镜像 tag / digest / commit / CI号 | 待填写 |
| 基础服务及数据库迁移 | NOT_RUN |
| SSO / 目录 / 人工映射 / 普通用户权限 | NOT_RUN |
| 定时同步、退出后旧会话拒绝 | NOT_RUN |
| V1固定版本、跨Worker、下游单次输出 | NOT_RUN（注明Mock / 正式） |
| 双用户共享 / 撤权、上游停用 / 恢复 | NOT_RUN |
| MySQL / DM8 双库完整验收 | NOT_RUN（本文示例仅MySQL） |
| 备份恢复与回退演练 | NOT_RUN |

### 12.3 编写依据及本次文档验证

本次依据当前分支的 [主 Compose](../../docker/docker-compose.yml)、[环境变量模板](../../docker/.env.example)、[安装器](../../docker/install.sh)、[后端配置](../../docker/bisheng/config/config.yaml)、[入口脚本](../../docker/bisheng/entrypoint.sh)、[网关基础配置](../../docker/gateway/config/application.yml)、[毕昇 Drone](../../.drone.yml)、Gateway 分支 Dockerfile / Drone / 昆联配置校验源码整理。参考用户提供的 [telemetry 部署文档](</Users/wenruli/Downloads/bisheng-telemetry 服务部署.md>) 的“登录仓库 → 拉取镜像 → 宿主配置挂载 → 启动”结构，但未复制其账号、密码或授权内容。

Docker 安装步骤采用常规软件源流程；[Docker Ubuntu 官方说明](https://docs.docker.com/engine/install/ubuntu/)本次访问受网络限制，未在线复核最新发行版支持矩阵，应由实际部署人员在客户网络确认。Compose `!override` 语法以本机 Compose v5.1.2 静态解析验证为准，不代表已在目标服务器运行。

完整真实试点的历史范围见 [2026-11-11 联调记录](../../features/v3.0.0/118-kunlian-sso-user-sync/联调部署与验证记录-20261111.md)，其中曾采用源码 / 静态目录更新，不能据此推出本手册分支镜像已包含该修复，也不能复制历史服务器私网 IP、用户 ID 或凭据到新环境。

文档静态核对与最终交付状态见 [verification.md](verification.md)；文档任务范围见 [tasks.md](tasks.md)。
