# F001 统一离线下载与部署设计

## 1. 基线与确认

基线 `origin/feat/3.1.0-offline-bundle`：`cf8de9c0dc`。方案已在本会话中确认并授权实施；Gateway 的来源按用户最新要求使用发行包的 `docker/docker-compose.yml` 解析结果（仓库实际扩展名为 `.yml`）。不改业务接口、数据库或权限。Constitution C6：凭据使用 CI Secret / 环境变量或终端输入，不硬编码、不写入交付目录。

## 2. 流程

构建 `make-bundle.sh` → `prepare-offline-delivery.sh` 完成可选 Gateway 及索引 → `nexus-upload.sh` 文件校验上传 → 最后发布版本 `download.json` → 电脑 `deploy.sh download` → 拷贝整目录 → Linux `deploy.sh install`。

## 3. 决策

- 一个根目录 `deploy.sh` 作为用户入口，Bash 调度嵌入的 Python 标准库逻辑，curl 使用 stdin 配置接收认证。无额外运行时 `.py` 文件。跨端脚本若将来提供原生 Windows 可执行程序再重审 Bash 前提。
- 固定版本索引代替枚举 Nexus 或逐个探测分卷；清单包含准确顺序、字节数和 SHA256，不使用 latest。发行路径 `deploy/bisheng/<version>/<arch>/download.json`。
- Gateway 单独保存为可选组件，版本从同一发行 docker 目录的 `.env.example` 与 Compose 实际解析结果读取；由 `docker pull --platform`、image inspect 和 RepoDigest 校验后归档。不假设 ARM 后缀；需要其他镜像时先改发行 Compose 配置。
- `install` 复用 `install.sh --prepare-only` 生成配置，自己完成受校验的镜像导入与 `compose up --pull never --no-build`，避免当前 `--offline --gateway` 互斥限制；不触发 install.sh 的在线登录和 pull。
- 分卷以连续流解 tar，解到临时目录并验证内层归档后原子移动。重复安装保留已展开的 docker 配置与数据，不重新覆盖 `.env` 或轮换运行时密钥。

## 4.1 数据流

Nexus 下载凭据仅在电脑内存/进程环境中使用；curl 凭据由 stdin 传入，不进入 argv。所有选定文件先校验，随后生成本地 SHA256SUMS.download。服务器不需要 Nexus 账号、curl 下载或网络访问。同一交付目录通过 `.delivery.lock` 拒绝并发下载/安装，正常退出删除锁；异常终止遗留锁时提示人工确认无任务后清理，不自动抢占。Linux 架构校验后，对全部已选文件重新计算校验，拒绝链接与越界归档成员；最后检查 Compose 全部启用镜像都已在本地。

## 4.2 文件契约

`download.json`：`schema_version=1`、`product=bisheng`、`version`（不带v）、`arch`、`bundle`、`files[]`，可选 `gateway`。

`files[]`：`name` 为 Nexus 版本目录内相对源文件名；`path` 为本地交付目录内目标路径；`component` 为 base/gateway；`size`、`sha256` 为大小及摘要。base 包含 `deploy.sh` 和 `packages/<bundle>.tar` 或连续 `part.00..NN`；gateway 包含 `gateway-addon/images.tar.zst`、`gateway-addon/manifest.json`。Gateway manifest 记录 image、arch、digest。不允许重复/绝对/父目录路径。

构建 dist 中基础 tar 保持原有平铺文件名，下载器按 path 放入 packages；新索引清单与 legacy 上传路径兼容。上传脚本使用索引精确选择新产物，旧无索引产物保留原行为。

## 4.3 职责

- `deploy.sh`：命令解析、认证下载、精确清单校验、流式安全解包、离线配置与启动。
- `scripts/make-bundle.sh`：原有基础镜像归档，末尾生成交付材料；`--with-gateway` 选择构建 Gateway 组件。
- `scripts/prepare-offline-delivery.sh`：Compose Gateway 镜像归档、复制统一脚本、固定版本清单。
- `scripts/nexus-upload.sh`：逐文件校验/上传，固定清单最后发布，成功后才更新可选 latest 指针。
- CI：GitHub 原生双架构与 Drone amd64 均启用 `--with-gateway`；quality 工作流在 Ubuntu/macOS 运行 CLI 和既有回归。

## 5. 已知坑

| 行为 | 后果与处理 |
| --- | --- |
| Python 源码通过 stdin heredoc 运行 | Python 的 stdin 不是交互终端；用户名/密码提示由外层 Bash 在进入 heredoc 前完成 |
| macOS tar 自动产生 AppleDouble 元数据 | 顶层额外文件不符合发行布局；构建时 COPYFILE_DISABLE=1，解包继续拒绝越界/链接 |
| macOS sha256sum 对格式错误的校验行可能返回0 | 回归用合法长度但摘要错误的数据验证失败路径；新统一脚本使用 Python 流式 SHA256 精确匹配 |
| Nexus REST 上传嵌套 Gateway 文件 | raw.directory 使用子目录，raw.asset filename 只传 basename，GET/PUT 使用完整相对路径 |

## 6. 依赖与边界

Incoming：固定版本 docker 目录、已发布平台镜像与 Compose 指定的 Gateway 镜像、CI Secret。Outgoing：Nexus raw 版本目录及交付文件；服务器侧仅本地 Docker/Compose，不调用 backend API。系统工具须预装或另行交付匹配 OS 的离线介质，当前不安装宿主软件。模型和任意应用的运行镜像/依赖不因基础包交付而自动齐备。

## 修订历史

2026-11-27：落实已确认单脚本方案与 Compose Gateway 来源要求，记录文件协议及验证边界。
