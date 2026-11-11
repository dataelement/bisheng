# BiSheng 全新部署

需要已启动的 Docker 和 Docker Compose。推荐 Compose V2；也支持具备 profiles 和完成依赖能力的 `docker-compose`。

从代码根目录执行：

```bash
bash docker/install.sh
```

脚本首次将 `.env.example` 复制为 `.env`，校验配置，使用默认公共账号登录 `cr.dataelem.com`，拉取镜像并执行 `up -d`。默认不启用 Gateway 和 FT，也不会询问是否启用。已有 `.env` 会保留，不自动覆盖或合并。部署需要 Bash 和常用系统命令，无需宿主机 Python。

账号在 `.env` 的 `CR_REGISTRY_USERNAME` / `CR_REGISTRY_PASSWORD` 中配置；默认使用提供的公共账号，密码通过 `--password-stdin` 传入 Docker。`--prepare-only` 只生成、校验配置，不登录、不拉取、不启动服务。

## Gateway（可选）

准备可读、非空的 license 文件后执行：

```bash
bash docker/install.sh --gateway \
  --license-file /secure/path/license.txt \
  --public-url http://服务器IP:3001
```

Gateway 与基础服务位于同一个 Compose 文件，通过 `gateway` profile 启用。脚本配置 license、共享密钥、数据库初始化及 Nginx 的 API/WebSocket 转发。没有 license 文件路径则跳过 Gateway；提供了不存在、不可读或空文件则停止。license 的有效性和期限由 Gateway 校验。

后续重复执行会保留 `.env` 中的 Gateway 配置。使用 `--no-gateway` 可恢复直接转发；该选项不会删除数据，也不停止已经运行的 Gateway。

## 镜像与部署配置

所有镜像地址集中在 `.env.example`，默认使用 `cr.dataelem.com`。需要修改镜像时，先执行 `bash docker/install.sh --prepare-only`，编辑生成的 `.env` 中完整的 `*_IMAGE` 地址，再执行安装脚本。下载源码不会重新构建镜像。

ARM 主机需要将每个启用服务的镜像替换为兼容 ARM 的 tag 或多架构镜像。Gateway ARM tag 为 `v1.8.0-arm64`。Socket proxy 的 AMD64 tag 为 `0.3.0`，ARM64 部署需设置 `DOCKER_SOCKET_PROXY_IMAGE=cr.dataelem.com/tecnativa/docker-socket-proxy:0.3.0-arm64`；沙箱必须使用可用的对应架构镜像。

## 模型微调 bisheng-ft（可选）

FT 默认关闭，通过同一 Compose 文件的 `ft` profile 部署。GPU 主机需要安装 NVIDIA 驱动和 NVIDIA Container Toolkit，确保 Docker 能使用 GPU。FT 使用独立版本 `cr.dataelem.com/dataelement/bisheng-ft:v0.5.0`，不要随平台版本修改；可在 `.env` 中用 `BISHENG_FT_IMAGE` 替换。2026-11-10 已只读确认该 CR tag 的 manifest 可获取，架构为 `linux/amd64`；本次未执行 GPU 训练验收。

```bash
# 仅准备配置（不拉取、不启动），也可直接省略 --prepare-only 部署：
bash docker/install.sh --ft --prepare-only
bash docker/install.sh --ft
```

已有 `.env` 无需覆盖：`--ft` 只将 `ft` 加入 `COMPOSE_PROFILES`，缺少 FT 新变量时使用上述镜像及端口 `8000`。需要自定义时，将 `BISHENG_FT_IMAGE`、`BISHENG_FT_PORT` 从 `.env.example` 补入已有 `.env`。后续无参数安装保留启用状态，Gateway 和 app-runtime 等其他 profile 也会保留。

挂载目录继续沿用旧版路径（相对于 `DOCKER_VOLUME_DIRECTORY`）：

- `bisheng-ft/config.yaml`：服务配置，默认连接同栈 Redis 的 DB 5；外部 Redis 或启用密码时同步修改。
- `data/llm`：基座模型，需提前准备 FT 支持的模型文件。
- `data/finetune_output`：训练日志、中间结果及微调模型，必须与基座模型目录分开。

在平台“模型管理 → 模型微调 → FT服务管理”登记 FT 地址。同栈 backend 使用 `ft_server:8000`；部署在其他主机时，填写 backend/worker 可访问的 `GPU主机IP:8000`（修改发布端口后使用对应端口）。地址格式为 `IP或主机名:端口`。仅启动容器不会自动登记服务或准备基座模型。

```bash
cd docker
docker compose --profile ft ps ft_server
docker compose --profile ft logs -f ft_server
curl -f http://127.0.0.1:8000/health
# 按需更新或重启 FT：
bash ../scripts/deploy.sh update ft
bash ../scripts/deploy.sh restart ft
# 取消以后安装时的启用状态；已运行容器需显式停止：
bash install.sh --no-ft --prepare-only
docker compose --profile ft stop ft_server
```

旧版 `docker-compose-ft.yml` 的部署入口改为主文件的 `--profile ft`，服务名仍为 `ft_server`、容器名仍为 `bisheng-ft-server`。基础部署不依赖 FT，也不会申请 GPU。

## 基础服务配置

MinIO 默认账号密码为 `minioadmin/minioadmin`，MySQL 沿用 `1234`。数据目录默认位于 `docker/` 下，由 `DOCKER_VOLUME_DIRECTORY` 控制。平台使用专用网络 `bisheng-network`（可通过 `BISHENG_NETWORK_NAME` 修改），沙箱使用 `bisheng-sandbox`。

端口和资源需要满足 Compose 配置；Elasticsearch 的宿主机配置、外部模型及文档服务按实际环境准备。首次启动后仍需注册用户、配置模型。

## 查看启动状态

```bash
cd docker
docker compose ps
docker compose logs -f backend backend_worker
# 启用 Gateway 时检查授权结果：
docker compose logs gateway
```

`up -d` 返回表示已执行后台启动，服务是否就绪需查看状态和日志。默认入口为 `http://服务器IP:3001`。

## 其他部署方式

- VibeApp 运行环境是独立的 `app-runtime` profile，需要额外配置，见[应用工场部署说明](../docs/architecture/14-app-factory-deployment.md)。
- Kubernetes 部署见 [Helm 说明](helm/README.md)。
- Office 可选服务使用 `docker-compose-office.yml`。
