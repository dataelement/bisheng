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

## 隔离执行与端口安全变更

用户可达的工作流 CodeNode、助手/工作流代码工具及灵思工具不再允许 `local` 后端。旧配置或未指定类型会明确报配置错误，不会自动回退到宿主机执行；请管理员选择并配置独立 `container` 或 `e2b` 执行器。`LOCAL_ISOLATION=off` 不能重新开放这些入口。此变更有意关闭共享后端主机执行能力，不能仅通过打开 CodeNode 开关恢复。

安装器在任何 Compose 配置展开前生成 32 字节随机 `SANDBOX_TOKEN`，替换空值、公开旧默认值和短值，保留已有足够长的配置；不输出令牌。直接使用 Compose 时必须显式提供该值。多节点/外部 runner 必须协调相同控制令牌和轮换时机。

MySQL、Redis、OpenFGA、Elasticsearch、Milvus 的宿主机映射默认只绑定 `127.0.0.1`；Docker 内部服务名访问不变。确有远程维护需要时，通过 `BISHENG_MIDDLEWARE_BIND_IP` 显式设置受控地址，并配置防火墙、认证及 TLS。不要无条件改为 `0.0.0.0`。MinIO 独立使用 `BISHENG_MINIO_BIND_IP`，默认也是 `127.0.0.1`；若浏览器预签名链接或外部 OnlyOffice 需要回源，应配置受保护的对象存储 ingress/TLS 与正确 sharepoint 后再显式开放，避免升级后误认为链接损坏而取消保护。前端3001和后端7860入口未在此变更中改绑。

独立 runner 仍有公共网络出站，并与后端在 sandbox 网络互通；它不是“完全无网络”的环境。backend/worker 的旧 `seccomp:unconfined` 尚需 Linux 镜像验证后加固。不要把禁用本机执行、令牌和端口变更称作所有隔离风险已解决；修改后的源码与实际运行镜像还需配套发布及部署验收。

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
