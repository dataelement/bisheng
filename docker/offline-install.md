# BiSheng 离线包部署

流程：**联网电脑下载 → 拷贝整个目录 → 隔离服务器部署**。以下版本号仅为示例，以实际已发布版本为准。

## 1. 在自己的电脑上下载

先取得交付提供的 `deploy.sh`（也可从 Nexus 指定版本目录下载该文件）。电脑需有 Bash、curl、Python 3，不需要 Docker；Windows 使用 WSL 或 Git Bash。

```bash
bash deploy.sh download --version 3.1.0 --arch amd64
```

需要 Gateway 时增加 `--gateway`：

```bash
bash deploy.sh download --version 3.1.0 --arch amd64 --gateway
```

版本号可带或不带 `v`。架构填写**部署服务器**的架构：x86_64 对应 `amd64`，aarch64 对应 `arm64`，与电脑架构无关。

命令会提示 Nexus 下载账号和密码，也可提前设置环境变量 `NEXUS_USER`、`NEXUS_PASS`。使用交付提供的只读下载账号。默认 Nexus 地址为 `https://nexus.dataelem.com`；内部地址不同可增加 `--base-url`。

脚本从 `raw-hosted/deploy/bisheng/<版本>/<架构>/download.json` 自动识别完整包或全部分卷，下载并校验。重复执行会跳过已校验文件；提示完成后得到 `bisheng-delivery-<版本>-<架构>/`，内含安装脚本、清单和包文件。自动入口要求所选版本已通过新打包流程发布该索引。

Gateway 镜像由该发行版本 `docker/docker-compose.yml` 及 `.env.example` 的实际配置确定，构建时拉取并归档；用户无需另选 Gateway 版本。

## 2. 拷贝到隔离服务器

将生成的 `bisheng-delivery-3.1.0-amd64/` **整个目录**通过 U 盘、移动硬盘或内网拷贝到服务器，不需要先合并分卷或解包。下载账号密码不会写入交付目录。

服务器需提前安装 Docker、Docker Compose V2、Bash、Python 3、zstd 和 SHA256 工具；未安装时另行准备匹配服务器操作系统的离线安装介质。

## 3. 在隔离服务器部署

```bash
cd bisheng-delivery-3.1.0-amd64
bash deploy.sh install
```

需要 Gateway 时，使用下载了 Gateway 组件的目录，另准备 license 文件，替换实际路径和对外地址后执行：

```bash
cd bisheng-delivery-3.1.0-amd64
bash deploy.sh install --gateway \
  --license-file /opt/bisheng-secrets/license.txt \
  --public-url http://服务器IP:3001
```

脚本自动校验拷贝后的文件、识别完整包或分卷并直接解包，导入镜像、配置并启动服务。安装阶段不下载文件、不登录仓库、不拉取镜像；license 文件部署后需保留。

浏览器访问 `http://服务器IP:3001`。脚本结束时输出实际 `docker/` 部署目录，在该目录可查看状态和日志：

```bash
docker compose ps -a
docker compose logs --tail=100 backend backend_worker frontend
# 启用 Gateway 时额外检查初始化与授权结果
docker compose logs --tail=100 gateway-db-init gateway
```

本说明用于全新部署。模型、文档服务及任意 Vibe App 的额外镜像/依赖材料需按需另行离线准备；安装脚本将应用运行时配置为离线模式，缺少材料不会自动使用公网。
