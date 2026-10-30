# Compose 部署入口

范围：现有 `docker/` MySQL 单机部署的简化入口，不修改业务 API 或数据库模型。
用户要求默认配置可直接复制为 `.env`，使用国内镜像及旧版 MinIO 默认密码，
由 Compose 创建专用命名网络；Gateway 同文件 profile 可选，宿主机不依赖 Python。

| AC | 验收条件 |
| --- | --- |
| AC-01 | 默认 `.env.example` 直接复制即可通过 Compose 配置解析；所有镜像默认 `cr.dataelem.com`，MinIO 默认 `minioadmin/minioadmin`。 |
| AC-02 | 普通安装只在 `.env` 不存在时复制，保留已有配置、凭据和镜像；首次无参数部署不询问是否启用 Gateway，默认不启用；重复执行保留已有 profile。不自动合并或推导镜像地址，不执行 env 内容。 |
| AC-03 | 普通安装执行 config、pull、up -d；镜像失败停止，不自动构建或换版本，不宣称容器启动等于产品就绪。 |
| AC-04 | Gateway 与数据库初始化服务同属 gateway profile；启用要求用户提供可读取的 license 文件路径及平台地址；未知路径则跳过 Gateway，即使已有 license 文本；无效指定路径报错；独立生成缺少的 HMAC/数据库密码，复用现有值。 |
| AC-05 | Compose 依赖链保证数据库健康后初始化 schema 和专用账号，再启动 Gateway；保留已有表；缺少数据库密码时初始化失败。 |
| AC-06 | 启用 Gateway 时生成浏览器 API/WebSocket 转发；内部、应用及 MinIO 路由不变；关闭时恢复直连、保留其他 profile 和数据。 |
| AC-07 | 主网络实际名称为 bisheng-network，沙箱为 bisheng-sandbox；保留应用运行时网络隔离。 |
| AC-08 | 支持 docker compose/docker-compose 两种入口；prepare-only 不拉取或启动；入口与流程测试无需宿主机 Python/jq。 |
| AC-09 | VibeApp 发布流水线保留 v* tag/手动触发；AMD64、ARM64 原生构建通过现有检查后默认推送 Docker Hub 与 CR，复用 backend 的 CR secrets；拒绝覆盖已有 tag，认证/推送失败不得生成成功清单。 |
| AC-10 | 两个仓库分别记录真实 digest，生成 4 个服务多架构索引和双架构应用运行时清单；Hub 原 artifact 名称保留，CR 独立输出，CR 清单不引用 Hub 镜像。 |

ARM 采用显式填写镜像地址：多架构 tag 由 Docker 选择，单架构 tag 必须使用已发布
的对应版本。未授权访问仓库不能确认 tag 或架构；沙箱暂用用户指定 `cr.dataelem.com/dataelement/bisheng-sandbox:feat_3.0.0`，本轮只测 AMD64。
Gateway 授权有效性由 Gateway 自身验证，脚本不再解析授权状态 JSON。
