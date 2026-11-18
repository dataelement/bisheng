# BiSheng 全新部署

2026-11-14验收说明：原入口逐项改密及重复部署已在192.168.106.166独立全栈验证，登录、知识文件上传下载检索、权限和Worker回归通过。验收增量镜像仅本地构建，未发布到现有标签；DM与完整交付待验。详见[验证记录](../features/v3.1.0-beta2/003-middleware-credential-security/verification.md#11-原入口逐项改密增量验收2026-11-1314)。Redis秘密文件降权读取由配套入口自动处理，不需要运维手工修改权限。

需要已启动的 Docker 和 Docker Compose。推荐 Compose V2；也支持具备 profiles 和完成依赖能力的 `docker-compose`。

从代码根目录执行：

```bash
bash docker/install.sh
```

脚本首次将 `.env.example` 复制为 `.env`，按提示隐藏输入本公司的五项中间件密码，自动生成外置密钥和加密配置，使用默认公共账号登录 `cr.dataelem.com`，拉取镜像并执行 `up -d`。默认不启用 Gateway 和 FT，也不会询问是否启用。已有 `.env` 会保留，不自动覆盖或合并。部署需要 Bash 和常用系统命令，无需宿主机 Python。

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

## 模型微调 bisheng-ft（可选）

FT 默认关闭，通过同一 Compose 文件的 `ft` profile 部署。GPU 主机需要安装 NVIDIA 驱动和 NVIDIA Container Toolkit，确保 Docker 能使用 GPU。FT 使用独立版本 `cr.dataelem.com/dataelement/bisheng-ft:v0.5.0`，不要随平台版本修改；可在 `.env` 中用 `BISHENG_FT_IMAGE` 替换。2026-11-10 已只读确认该 CR tag 的 manifest 可获取，架构为 `linux/amd64`；本次未执行 GPU 训练验收。

```bash
# 仅准备配置（不拉取、不启动），也可直接省略 --prepare-only 部署：
bash docker/install.sh --ft --prepare-only
bash docker/install.sh --ft
```

已有 `.env` 无需覆盖：`--ft` 只将 `ft` 加入 `COMPOSE_PROFILES`，缺少 FT 新变量时使用上述镜像及端口 `8000`。需要自定义时，将 `BISHENG_FT_IMAGE`、`BISHENG_FT_PORT` 从 `.env.example` 补入已有 `.env`。后续无参数安装保留启用状态，Gateway 和 app-runtime 等其他 profile 也会保留。

挂载目录继续沿用旧版路径（相对于 `DOCKER_VOLUME_DIRECTORY`）：

- `bisheng-ft/config.yaml`：服务配置，默认连接同栈 Redis 的 DB 5。同栈 Redis 已启用密码（见下文“基础服务配置”），启用 FT 前须在此填入 Redis 账号和按 FT 镜像格式加密的密码。
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

全新部署由客户提供 MySQL、Redis、MinIO、Elasticsearch、Milvus 密码，不内置可用默认密码。MySQL、Redis、Elasticsearch、Milvus（及统计 ES）至少 6 位；MinIO 原生密钥至少 8 位；不要求数字、字母和符号组合，仍拒绝占位符。数据目录默认位于 `docker/` 下，由 `DOCKER_VOLUME_DIRECTORY` 控制。平台使用专用网络 `bisheng-network`（可通过 `BISHENG_NETWORK_NAME` 修改），沙箱使用 `bisheng-sandbox`。

端口和资源需要满足 Compose 配置；Elasticsearch 的宿主机配置、外部模型及文档服务按实际环境准备。首次启动后仍需注册用户、配置模型。

## 隔离执行与端口安全变更

中间件宿主机端口默认只绑定 `127.0.0.1`（`BISHENG_MIDDLEWARE_BIND_IP` / `BISHENG_MINIO_BIND_IP`）。远程维护走受保护的入口、防火墙和 TLS，不把 MySQL、Redis、Elasticsearch、Milvus、OpenFGA 直接暴露到公网。`install.sh` 会生成 32 字节私有 `SANDBOX_TOKEN`，并拒绝空值、公开默认值和过短值。代码节点不再回退到进程内本地执行器。

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

仍使用本文开头的原命令。首次在同一安装过程中输入并确认密码；密钥、加密配置、组件凭据文件和版本参数由安装器自动管理。再次执行逐项选择是否改密，直接回车保留；选中项按提示隐藏输入并确认维护。失败修复后仍用原命令续跑，无需手动执行 keygen/prepare 或填写 bundle/key/revision。

标准单机部署将受限文件保存在固定目录 `/opt/bisheng/.credential-security/`（目录不存在时自动创建，权限 0700），`.env` 自动记录其中的当前凭据包和密钥路径。代码目录下不再存放凭据。纳入现有公司备份制度。密钥缺失时按提示提供匹配备份，不会生成新密钥覆盖。无需宿主机 Python，但需要含 credential_tool 的配套后端镜像及能访问本机路径的 Docker daemon。

发现受管 v1 凭据包时，安装器提示维护确认，将原生文件、输入和历史材料转换为 v2 密文；验证连接、应用就绪和全部容器旧文件引用后，才清理已核验的旧文件。已有 ES 无认证时，原命令询问是否启用：回车或 n 保留当前状态，y 隐藏输入新密码并在维护窗口内保留原数据卷、索引和镜像完成切换；服务端已认证但客户端缺少凭据时引导录入现用 elastic 密码。未知状态、未经验证的原生旧布局、非单节点 8.12.0 或已有 TLS 升级路径明确拒绝，不猜测或关闭现有安全设置。失败保留加密状态与恢复备份，重新执行原命令恢复。多节点停写需要由维护负责人统一协调。

正常部署与失败处理见 [HTML 运维手册](中间件凭据运维手册.html)。无人值守仅需由自动化平台在 `.env` 配置 `BISHENG_CREDENTIAL_INPUTS_FILE` 指向受限密码文件清单，执行命令不变。辅助 `credentials.sh` 的显式路径参数保留用于专项维护。

应用配置中的受管密码字段加密保存，原生中间件文件以受限明文挂载。主密钥不写入代码或镜像，不可对所有人放开。普通部署账号需要 Docker 授权和文件访问权；rootless 和 Gateway 当前明确拒绝或不在通过范围。本次不修改 Helm Chart。Milvus 原生内部消息中的 Base64 凭据按用户确认保留例外，不视为加密。标准新装 ES 为单机 HTTP 策略；集群、TLS、外部组件和多节点按专项方案验证。

### 重新部署时修改密码

仍执行 `bash docker/install.sh` 或 `bash scripts/deploy.sh install`。每项 `[y/N]` 提示中回车保留，输入 y 后填写新密码；可选择任意子集。全部组件预检通过后统一确认维护窗口，脚本暂停应用、修改真实账号、保留原数据和原生配置、更新消费者并验证新旧密码。未选择的弱密码继续显示待治理，不影响其他已选项。

中断时保留 `.env`、整个 `/opt/bisheng/.credential-security`、现用密钥和原数据，修复后重新执行原命令，选择继续原计划并重新确认维护；不会反复猜密码。交互恢复可申请配对回退，仅在原材料、权限、账号和旧密码规则满足条件时执行，其他情况保持维护并交专人处理。

本地验收使用已经缓存的私有覆盖镜像时，可在新交付目录的 `.env` 设置 `BISHENG_IMAGE_PULL_POLICY=missing`，原命令只拉取不存在的镜像；默认值 `always` 沿用原镜像拉取行为。`never` 仅在明确要求完全离线且所需镜像均已缓存时使用。新交付目录会从当前同项目的 Compose 后端容器只读识别原凭据包和数据目录，不覆盖旧代码目录；若存在多个不同来源，停止并要求人工核对。

标准受管范围为 MySQL8.0.43、Redis default账号、MinIO root、已认证的 ES 与 Milvus root。外部/未知模式、当前运行的 Gateway/独立消费者、DM及独立统计ES尚无完整适配，改密前拒绝；不自动降级认证或 TLS。具体证据和待验证项见验证记录。

自动化平台可在 `.env` 设置 `BISHENG_CREDENTIAL_ROTATION_INPUTS_FILE` 为受限 version=1 输入清单，环境变量 `BISHENG_ALLOW_CREDENTIAL_ROTATION=yes` 表示本次维护授权。未提供请求时保持复用；同内容请求已完成后不重复改密。普通人工部署不需要新增参数。
