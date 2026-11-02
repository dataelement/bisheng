# Vibe runtime v2：安装、离线材料与维护

适用：F086 的 Docker 实现，F059 的 Kubernetes 执行器沿用同一 v2 控制合同。F114 本地实现已统一六动作与具体租户范围；真实部署 E2E、正式镜像发行及特性合入仍待完成，见 [F114 验证记录](../../features/v3.0.0/114-vibe-permission-actions/verification.md)。正式发行以通过 amd64、arm64 原生 CI 的镜像和目录产物为准。本开发分支的Docker主链路和双架构原生容器已验，完整验收和正式镜像发行仍未完成，见[F086真实记录](../../features/v3.0.0/086-vibe-runtime-delivery/live-validation.md)；下列完整安装步骤尚非客户现场安装证明。K8s 执行器继续由 F059 交付。

## 1. 服务与前置条件

| 组件 | 前置条件与职责 |
| --- | --- |
| backend / worker | 使用同一新版代码、SQL 结构和运行配置；MySQL 或 DM8、Redis、OpenFGA、平台原有 MinIO 可用。只有平台访问私有 `bisheng-apps` 桶 |
| runtime-manager | 独立进程和已发布镜像；能够访问 backend 与 Docker Engine API；有专属持久数据盘和执行资源。服务镜像不含 Docker CLI，不带 MinIO 凭据 |
| docker-socket-proxy | 唯一挂载 docker.sock；只与 manager 加入 `runtime-control` 内部网络，不发布端口。Engine API 仍有创建/挂载容器的高权限 |
| app-proxy / egress-proxy | 分别读取 backend 路由与短效出站策略；egress 使用 manager 镜像的另一入口。无 Engine 权限、MinIO 凭据或生产数据卷 |
| 应用镜像 | 精确匹配目标平台的 runtime 和 preparer 镜像。完整应用镜像无需 preparer；v2 source-image 仍需要共用模板基础镜像和构建依赖 |
| 制作工具 | 在有网的目标架构准备机上使用 Docker CLI；与 manager 服务自身的依赖不同 |

单 Engine 固定节点；节点失联不自动跨机接管 SQLite。应用没有宿主端口映射，各容器可同时监听 8080。正式入口仍是 nginx → app-proxy → 应用 IP。

## 2. 配置与镜像替换

复制 `docker/.env.example`，配置持久目录、各服务独立 HMAC 密钥和 Fernet payload key。payload key 必须由 backend 和 worker 共享并备份；恢复 SQL 而丢失该 key，无法解密已登记操作。不要将 key、会话 token 或包源密码放进代码包、补包、Git 或日志。

backend 的现有 `config.yaml` 还须包含以下 `app_runtime` 子键（密钥使用现有 `!env` 或加密配置机制）：

```yaml
app_runtime:
  enabled: true
  manager_base_url: http://runtime-manager:8091
  proxy_hmac_secret: !env BISHENG_APP_PROXY_HMAC_SECRET
  obo_secret: !env BISHENG_APP_OBO_SECRET
  entry_base_url: https://bisheng.example
```

OBO secret 必须独立于平台 JWT secret。manager/entry/egress/control 的 v2 服务身份由正式 Compose 的环境映射提供；为空会拒绝请求。backend `app_runtime.runtime_protocol_version`、manager/代理 `RTM_PROTOCOL_VERSION` 仅接受 2，省略时也默认 2；显式 1 或未知值在启动时拒绝。平台 `/api/v1`、`/api/v2` 和 manifest_version 不因此退役。

| 要替换的内容 | 修改位置 |
| --- | --- |
| manager / egress 服务镜像 | `.env` 的 `BISHENG_RUNTIME_MANAGER_IMAGE`；两个进程共用该镜像。`RTM_DATA_HELPER_IMAGE` 也引用它 |
| app-proxy 服务镜像 | `.env` 的 `BISHENG_APP_PROXY_IMAGE` |
| 新发布默认运行基础镜像 | 超管导入新的不可变 profile 修订，再通过默认映射 API CAS 切换；不修改 manager 镜像，也不修改 `RTM_IMAGE_PREFIX` |
| 单个源码应用的环境 | `bisheng-app.yaml` 的 `delivery.profile: python311-standard@<revision>`，按正常发布审批冻结 |
| 完整应用镜像 | `delivery.mode: image` 加仓库 digest 或本地 `sha256:<image-id>`；可指定 argv command，或沿用镜像 Entrypoint/Cmd。须满足非 root UID 10001、监听地址/端口、只读根和 `/data` 约定 |
| 网络依赖来源 | manager 的 `RTM_BUILD_INDEX_URL`、`RTM_BUILD_EXTRA_INDEX_URL`、`RTM_BUILD_NPM_REGISTRY`；严格离线时 `BISHENG_RUNTIME_OFFLINE=true` |

正式 Compose 只有 `image:`。开发时可叠加 `scripts/dev/docker-compose.runtime-dev.yml` 的 `build:`；不将现场构建作为客户安装步骤。

## 3. 镜像与目录发行

`.github/workflows/runtime-images.yml` 在原生 amd64 和 arm64 分别构建、检查镜像内容并推送不可覆盖的版本标签到 Docker Hub 和 `cr.dataelem.com`；只有两侧成功才发布服务多架构索引及 `runtime-profiles.json`。已存在的标签不会被覆盖，发布失败后使用新 release 标识重试。

目录包含 Python 3.11、Node 20、static 的 runtime/preparer child digest、配置 Image ID、ABI、工具链和 UID/GID。官方 SDK 固定为镜像内的 0.1.1 wheel。镜像发布流水线保留镜像自身的架构、依赖导入及打包内容检查，不执行应用离线部署、复用和 SQLite 集成测试。部署、离线运行及 backend/审批/权限的完整验收由 QA 收到镜像后执行。

超管在平台可访问的位置导入真实 CI 目录（工具只接受 JSON；JSON 是 YAML 的子集）：

```bash
python src/runtime-manager/tools/runtime_materials.py import-profile \
  --base-url https://bisheng.example --file runtime-profiles.json --set-defaults
```

工具从安全环境变量 `BISHENG_MANAGEMENT_TOKEN` 读取当前自然人会话；不接受 SAK 代替新增管理权限。`--set-defaults` 先 GET 当前 generation，再 CAS 更新；导入同一修订同一内容幂等，改内容必须增 revision。默认变化只影响后续未冻结版本。

客户自定义目录沿用相同结构。后台校验的是身份、修订、摘要和平台元数据；自定义镜像是否真的满足运行契约，必须由该镜像的提供者完成原生安装/启动测试，发布预检仍会拒绝实际不兼容的组合。

## 4. 没有外网、没有仓库时

镜像与 Python/npm 材料是两份交付物。`docker save/load` 解决镜像可用；wheelhouse/npm cache 解决新增依赖可用；模型、检索和外部业务 API 是否可达需要另行确认。

1. 在目标架构有网机器取得所有服务、runtime、preparer 镜像，保留发行目录及镜像归档 SHA-256。`docker save` 打包后运入现场 `docker load`。
2. manager 通过配置 Image ID 查本地镜像，并核对 Engine 的 OS/架构及冻结 ID。默认 `RTM_IMAGE_PULL_POLICY=never`；缺失就前置失败，不回落公网。仅有同名 tag 不构成校验通过。
3. 现场导入相同目录及公开基础补包。业务包额外依赖由应用获授权编辑者提前制作私有补包；如果没有材料，首次发布或新增依赖会在审批前失败。

从 CI 目录在有网准备机导出精确 profile，不需要接入客户 SQL 或 MinIO：

```bash
python src/runtime-manager/tools/runtime_materials.py export-profile \
  --catalog runtime-profiles.json --reference python311-standard@<revision> \
  --platform linux/arm64 --output profile.json
python src/runtime-manager/tools/runtime_materials.py prepare-offline \
  --profile profile.json --image-id sha256:<preparer-image-id> \
  --source ./app-source --materials ./new-materials --output ./app-offline.tar.gz
python src/runtime-manager/tools/runtime_materials.py verify-offline \
  --profile profile.json --file ./app-offline.tar.gz
```

`prepare-offline` 使用空输出目录和临时源码副本，先联网下载，再在 `--network none` 容器安装验证；只打包下载材料，不把 `node_modules`、源码相关安装结果或包源登录文件当作公共可复用包。命令参数中的 `<...>` 必须换成真实发行值。联网准备机可配置受批准的内部镜像/网络；当前工具不从宿主自动传递私有包源账号，需由受控准备环境提供无账号镜像或单独供应 wheel/cache。

Python 接受常规 PEP 508 requirements、`-r` / `-c` 和 sha256 hash；包含文件必须在源码根内。联网阶段拒绝 VCS、直接依赖 URL 和任意 pip 参数，以免安装元数据执行代码取得源凭据。需要源码编译的第三方包应由受控准备机先构建目标平台 wheel；显式离线源码包需要完整构建后端/系统库。Node 以 package-lock/npm cache 为材料；VCS、外部本地路径和脚本的在线补下载不受支持。`postinstall`、Python 构建钩子和前端编译在禁网阶段执行；缺材料就失败。

持该应用 `edit` 的已登录人员导入应用私有补包：

```bash
python src/runtime-manager/tools/runtime_materials.py import-app-pack \
  --base-url https://bisheng.example --app-id <app-id> \
  --profile-reference python311-standard@<revision> --platform linux/arm64 \
  --file ./app-offline.tar.gz
```

导入成功后材料仍绑定原应用及其固定归属人；持当前 `edit` 的人员可导入、读取及 PATCH `/api/v1/apps/{app}/runtime/materials/{artifact}` 的 `enabled`，只影响未来 prepare。清单显式填写 `offline_artifacts` 也以真实调用主体的 `edit` 判定，SA 仍须通过既有 S 模式、`app:manage`、F113 资格及相应发布组合动作；不能借归属人权限。工具上传前从平台应用状态响应读取实际具体租户并冻结 `X-Management-Tenant`；范围缺失、失效或冲突就失败，不静默重试到另一个租户。公开基础集合与全局 profile 继续由原平台运维资格维护。

`offline.json` 格式：`schema_version:1`、`profile_id`、`profile_digest`、`platform`、`abi` 和 `files:{path:{sha256,size}}`。导入检查完整性、范围和兼容元数据；真正的禁网依赖物化验证发生在 prepare，不能把导入 verified 当成所有应用已通过运行验收。

## 5. 数据与恢复

`BISHENG_APP_DATA_ROOT` 必须为绝对宿主路径，并与 manager 的宿主 bind 路径完全相同。生产数据库为 `apps/{app_id}/db/app.db`；代码/环境目录只读；预览位于 `previews/{operation_id}/apps/{app_id}/db`。使用支持 SQLite 本地文件锁和原子 rename 的文件系统，不以普通 NFS 目录假定等价。

升级共享 SQLite 前：容量预占 → 平台维护路由确认 → 停止旧写入者 → SQLite Backup API → backend 内容/SQL 确认 → 受控 DDL → 启动探活 → 平台业务事务切换。迁移日志和 DDL 在同一 SQLite 事务内，重试不会重复执行破坏性计划。DDL 后启动失败保留维护状态；不会自动用旧快照覆盖新数据。

恢复前，获授权操作者先 GET `/api/v1/apps/{app}/runtime/state` 取得当前 `generation`、当前代码版本与操作 ID，作为 CAS 输入；未登记 v2 归属时 generation 为0，不能直接恢复。恢复 API：`POST /api/v1/apps/{app}/runtime/restore`，参数为 `snapshot_id`、`expected_current_generation`、`acknowledge_data_loss:true` 和独立 `idempotency_key`。恢复数据要求该应用 `edit`；若恢复后包含启动正式实例，还必须有 `publish`。F048 判定真实主体，不再按原创建人或其账号状态加限制。浏览器管理写携带从实际响应取得的 `X-Management-Tenant`，该头不能赋权。返回 202 后查 `/runtime/operations/{id}`。先保护当前 DB，再原子替换目标快照；停用应用恢复后仍停用，在线应用恢复需重新探活。恢复不变更代码版本。审计动作是 `app.data_restore`。

数据表/行操作经 backend 既有权限检查后调用 manager v2。为防业务文件链接跨出应用目录，manager 使用**相同 manager 镜像的短命禁网数据容器**，只挂载一个应用的数据库和一次性导出目录；最多两个，每个 128 MiB/100mCPU、30 秒。不是新增常驻进程；系统保留资源至少 256 MiB，镜像必须本地可用。停写备份/迁移仍由 manager 本地执行，并拒绝主文件和 WAL/SHM/journal 链接。

停用保留 DB、附件、快照和版本；删除经 F048 `delete`、用户二次确认及旧写入者停止确认后清理本地 DB、附件和数据库快照。历史代码/版本引用继续保留；不以缓存清理代替数据删除。

## 6. 存量升级与故障处理

当前仅支持运行控制协议 v2，不再提供协议 1 兼容模式、旧 inventory/import、绑定 upgrade/rebind API 或自动收养。代码仍保留供 v2 source-image、SQLite/helper 复用的工具；旧控制方法不可调用，不据文件名删除共用工具。

升级前只读核对数据库节点/路由/operation 与真实执行体标签、不可变镜像和存储归属。原生 v2 的正式实例及凭据不会仅因协议收敛自动重建。旧 v1 或缺少授权来源的在途操作不能继续新增用户效果；先停新受理，用旧版本完成所有旧预览回收并确认旧写入者停止，备份后按专门批准的维护计划重新发布为 v2，保留原数据库和附件。这里没有可以直接执行的旧导入命令，也不授权处理任何既有环境。

新用户操作保存服务器产生的授权来源，后端在准备、维护前、数据步骤、启动及路由切换时重新校验。manager 必须先取得短效阶段许可，平台确认维护路由后才停止旧 writer；超时或回复未知不能当作允许。系统自愈只恢复当前批准版本/原运行意图，依据真实观测重新验证，不依赖历史提交者仍然持权。

管理预览要求当前 `edit`，审批预览要求当前有效任务；显式用途分别为 `management`、`approval`。两者只注入声明名和空密钥值，独立会话/数据库/附件/凭据在同一事务登记，提交后唤醒，ready 后才开放入口。结束/过期只吊销该预览凭据，原生产凭据保持；运行时仍逐次校验当前用途、任务或动作及可信 OBO。管理范围必须为一个具体租户，不能选择全平台；个人审批、SDK 及内部调用不借浏览器选择赋权。

manager 重启不撤销平台已提交路由；入口/出口读取 backend，平台授权失联后按 TTL 拒绝。未知执行体不自动释放额度或跨节点接管。正常任务清理不触及生产库/保护快照；无法确认停止时保留预占并报告 cleanup pending。节点替换、Engine ID 变化或物理磁盘丢失需人工维护恢复。

验收及当前证据见 [F086 验证记录](../../features/v3.0.0/086-vibe-runtime-delivery/validation.json) 和 [E2E 清单](../../features/v3.0.0/086-vibe-runtime-delivery/e2e-checklist.md)。


旧模板 Engine build 在调用前持久标记 started，只有读到完整结束流才记 finished。中断且不能确认 daemon build 已退出时，报告 legacy_build_stop_unconfirmed 并保留容量，不因容器列表为空就清理/重建。该状态需要专门维护窗口核对并停止未知构建；不能仅通过用户 cancel 或修改缓存让资源重新可用。原生构建中断与恢复仍须在专用 Engine 故障验收中验证。

协议2默认每5秒心跳/对账，平台节点新鲜度上限15秒；自定义调大interval时需给网络/处理延迟留余量。材料导入上限读取backend app_runtime.artifact_max_mb；代理默认2GiB，修改平台上限时同步评估代理限制。


依赖失败的 diagnostic_tail 先在manager按包源/代理/密钥及URL参数脱敏，再由backend限制16KiB写入operation/fact；临时容器回收后仍可定位缺失包。backend app_runtime.runtime_diagnostic_days默认7天，过期终态在下一轮node plan按100条批量清除诊断尾部，保留阶段/归属/摘要等控制事实。manager离线时顺延至恢复对账；未声明固定日历时刻必定擦除SQL。任务deadline通过BISHENG_RUNTIME_TASK_TIMEOUT_SECONDS同时提供给backend和manager；nonce120秒及严格小于60秒窗口是协议常量，不另设无效配置副本。
