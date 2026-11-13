# BiSheng 全新部署

需要已启动的 Docker 和 Docker Compose。推荐 Compose V2；也支持具备 profiles 和完成依赖能力的 `docker-compose`。

从代码根目录执行：

```bash
bash docker/install.sh
```

脚本首次将 `.env.example` 复制为 `.env`，按提示隐藏输入本公司的五项中间件密码，自动生成外置密钥和加密配置，使用默认公共账号登录 `cr.dataelem.com`，拉取镜像并执行 `up -d`。默认不启用 Gateway，也不会询问是否启用。已有 `.env` 会保留，不自动覆盖或合并。部署需要 Bash 和常用系统命令，无需宿主机 Python。

账号在 `.env` 的 `CR_REGISTRY_USERNAME` / `CR_REGISTRY_PASSWORD` 中配置；默认使用提供的公共账号，密码通过 `--password-stdin` 传入 Docker。`--prepare-only` 首次只准备参数并校验 Compose 结构，不要求密码和工具镜像；不登录、不拉取、不启动服务。正式安装才进行凭据和新连接检查。

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

全新部署由客户提供 MySQL、Redis、MinIO、Elasticsearch、Milvus 密码，不内置可用默认密码。数据目录默认位于 `docker/` 下，由 `DOCKER_VOLUME_DIRECTORY` 控制。平台使用专用网络 `bisheng-network`（可通过 `BISHENG_NETWORK_NAME` 修改），沙箱使用 `bisheng-sandbox`。

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


## 中间件凭据配置（v3.1.0-beta2）

仍使用本文开头的原命令。首次在同一安装过程中输入并确认密码；密钥、加密配置、组件凭据文件和版本参数由安装器自动管理。再次执行复用已有配置，失败修复后也使用原命令重试，无需手动执行 keygen/prepare 或填写 bundle/key/revision。

标准单机部署默认将受限文件保存在 `docker/.generated/credential-security/`，`.env` 自动记录路径；纳入现有公司备份制度。密钥缺失时按提示提供匹配备份，不会生成新密钥覆盖。无需宿主机 Python，但需要含 credential_tool 的配套后端镜像及能访问本机路径的 Docker daemon。

发现已有中间件数据时，安装器先引导确认维护窗口，再从原后端容器读取现用配置、环境来源和旧密钥，准备新旧过渡密钥并备份、迁移组织同步/沙箱密文。停止本机标准应用容器之前完成文件预检；全部其他节点需由维护负责人停写。迁移失败保持应用停止，保留计划并在下次原命令中续跑；不会重建原生中间件、修改实际密码或自动启用认证。迁移成功仍不代表旧弱密码已经治理。

正常部署与失败处理见 [HTML 运维手册](../docs/中间件凭据运维手册.html)。无人值守仅需由自动化平台在 `.env` 配置 `BISHENG_CREDENTIAL_INPUTS_FILE` 指向受限密码文件清单，执行命令不变。辅助 `credentials.sh` 的显式路径参数保留用于专项维护。

原生文件按受限秘密文件管理，安装器仅给显式挂载文件设置受控组读权限，密钥文件保持私有。标准新装 ES 为单机 HTTP 策略；集群、TLS、自定义 ACL、外部数据库和多节点按专项方案部署，不能失败后关闭 TLS。真实私有镜像、UID/GID、全链路及双数据库验收边界见 [验证记录](../features/v3.1.0-beta2/003-middleware-credential-security/verification.md)。
