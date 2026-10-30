# BiSheng 全新部署

需要已启动的 Docker 和 Docker Compose。推荐 Compose V2；也支持具备 profiles 和完成依赖能力的 `docker-compose`。

从代码根目录执行：

```bash
bash docker/install.sh
```

脚本首次将 `.env.example` 复制为 `.env`，校验配置，使用默认公共账号登录 `cr.dataelem.com`，拉取镜像并执行 `up -d`。默认不启用 Gateway，也不会询问是否启用。已有 `.env` 会保留，不自动覆盖或合并。部署需要 Bash 和常用系统命令，无需宿主机 Python。

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
