# MVP-114 纵切：在 114 上跑通「表单问卷」托管应用

> **定位**：v3.0.0 应用工场的**首个端到端可演示纵切**。目标一句话：在 114 服务器（compose 单机形态）上，开发者用 CLI 把一个表单问卷小应用导入纳管、经平台预置审批流上线、设可见范围为全员，**所有已登录用户都能从应用广场打开并提交问卷**。
> **性质**：它不是新的 Feature，而是横切 F049 / F053 / F054 / F055 / F056 五个 Feature 的**首波任务集合**——各 Feature 的 tasks.md 里以 `[MVP-114]` 标记属于本纵切的任务，纵切外的任务照常存在于 tasks.md（release 仍要全做），只是排在纵切之后。
> **决策依据**：2026-08-17 用户授权全自动模式后确定；技术路线锚点取《3.0 附录：纳管应用技术路线与架构选型调研》（以下简称《调研》）与《3.0 应用工场 产品方案》§4；需求真相仍是 PRD-1 v2.0 / 伴生 PRD v2.1，本纵切只做「先做哪些」的裁剪、不改需求口径。

---

## 1. 演示剧本（验收即此剧本跑通）

| 步 | 角色 / 位置 | 动作 | 平台行为 | 承接 Feature |
|---|---|---|---|---|
| 1 | 租户管理员 · platform 管理后台「服务账号」 | 新建服务账号（名称 / 描述 / **资源归属人 = 开发者本人**）→ 签发密钥，勾 **`app:manage`**（「本地开发工具包」分组，开放能力层开关 = 开） | 一次性展示明文，此后只见掩码；密钥落底座（哈希）| F049 |
| 2 | 开发者 · 本地终端 | `bisheng login https://114 --api-key bs-sak-…` | 校验密钥（模式 S），凭据落本地用户目录；`skills sync` 自动执行（纵切内可为空包） | F053 |
| 3 | 开发者 · 本地 | 一个表单问卷小应用（python3.11 + FastAPI/Streamlit 二选一，用标准库读平台注入的 SQLite 连接环境变量）+ `bisheng-app.yaml`（name / description / runtime: python3.11 / port / tier: 轻量）→ `bisheng deploy` | 打包上传 → **托管预检**（manifest 校验 → 平台 Dockerfile 模板构建 → 启动探活）→ **密钥扫描** → 生成**版本记录 + 快照** → 生成审批单（**平台预置流程**：owner 主部门的部门管理员 ∪ 租户管理员，或签；单租户回退超管） | F055（管线）/ F054（构建 / 探活能力）/ F053（命令） |
| 4 | 审批人 · client 审批中心 | 通过 | 上线终检（运行环境容量）→ runtime-manager 拉起容器（轻量档限额、restart policy、healthcheck）→ app-proxy 路由 `/apps/{slug}` 上线；应用态 → 已上线 | F055 / F054 |
| 5 | 开发者（owner）· platform 构建 → 应用 → 该卡片 ⚙️「管理权限」 | 授予**全员**（根部门或全员用户组） | 平台通用授权弹窗（`app` 资源类型）；变更即时生效、不经审批、计审计 | F054（类型注册）/ F056（交互） |
| 6 | 任意已登录用户 · client 应用广场 | 看到该托管应用卡片 → 点击 | 跳 `/apps/{slug}` → app-proxy 验平台会话 → 注入 `X-BiSheng-User-*` → 反代到容器 → 问卷页面 → 提交 → 数据落 per-app SQLite | F056（广场）/ F054（入口 + 注入） |
| 7 | 未登录 / 无权限用户 | 直接访问 `/apps/{slug}` | 未登录 → 重定向平台登录页、登录后回跳；无权限 → 统一「无权限」页 | F054 |
| 8 | owner · platform 应用详情页 | 看运行日志、看数据面里的问卷提交记录（可选）；下线 → 广场与入口呈已下线页 | F054 |

**成功判据**：步 1–7 全部在 114 上按上表行为跑通，且步 6 由**非管理员普通用户**验证（admin 短路 ReBAC，不能拿它当证据）。

---

## 2. 各 Feature 的纵切首波（`[MVP-114]`）与纵切外

| Feature | `[MVP-114]` 首波（tasks.md 里排最前） | 纵切外（release 仍必做，排后） |
|---|---|---|
| **F049** openapi-auth-baseline | 凭据底座（生成 / 哈希 / 校验 / 软撤销 / 掩码 / 一次性展示）；服务账号主体（类型标识、租户直写、**资源归属人必填**、登录守卫的公共守卫 1 处、`/user/list` 数据层排除）；权限位清单含三扩展位 + **开放能力层部署开关**；管理界面：服务账号列表 / 新建 / 详情「API 密钥」tab（签发 / 编辑 / 撤销 / 批量撤销）；鉴权依赖（`Depends`）供 F053 / F055 新端点使用；`app:manage` 位判定 | 36 个既有 v2 端点接入 + 2 WS + share-token 通道；「资源授权」主体侧页与回授逻辑；四处既有缺陷修复；`default_operator` / `enable_guest_access` 移除与文档修订；对账豁免测试矩阵；服务账号不得授角色的管理接口拒绝；密钥审计事件全覆盖 |
| **F053** dev-cli-skills | CLI 包工程 + `login`（存凭据）+ `deploy`（打包 → 上传 → 触发管线 → 轮询状态并输出预检 / 扫描 / 审批结果）+ `logs`（可选）；CLI 安装件由平台分发（wheel + 下载端点） | `skills sync` 两包内容、`dev`（迷你代理注入 + 本地 sqlite）、接入信息区与一键复制、`login` 拒 `delegate`、非 Claude 引擎 AGENTS.md 引用 |
| **F054** app-domain-runtime | App / AppVersion / AppInstance 领域模型与状态机子集（草稿 / 已上线 / 已下线 / 待上线 / 已删除）；**GOV-01 `app` 资源类型注册**（后端 12 处 + 前端 3 处 + Catalog 范围表存量生效手段）；**runtime-manager**（独立进程、唯一持 docker socket、意图式 RPC：build / start / stop / status / logs；平台 Dockerfile 模板 python3.11 → 镜像；容器 restart policy + healthcheck + 轻量档限额 + unhealthy 轮询重建；本机卷挂 SQLite）；**app-proxy**（`/apps/{slug}` 验平台会话 → 归一化剥离客户端伪造头 → 注入身份头 → 反代 HTTP；未登录重定向、无权限 / 已停用 / 不存在 / 未部署四类页）；nginx `/apps/` → app-proxy 接线；构建页「托管应用」类型筛选与卡片（含 ⚙️ 菜单按类型裁剪）；应用详情页壳（发布 tab 最小：应用态徽标 + 入口链接；可见范围区内容归 F056；运行日志 tab）；GOV-10 工场运行时层开关 | k8s（F059）；egress 双层白名单与 UDP 封禁、gVisor 档位、docker-socket-proxy（可在纵切后紧接）；RT-08 完整自愈验收与「发布中 / 恢复中」过渡态；附件存储；数据面 WB-06 可编辑网格；显式删除前置状态闸；GOV-03 档位→限额的三档全覆盖 |
| **F055** app-publish-pipeline | 发布管线端点：接收包 → 版本记录 + 快照入 MinIO → 托管预检（调 F054 build / 探活）→ 密钥扫描规则集（含 `bs-sak-` 前缀）→ **GOV-02 预置审批流**（「应用发布」场景 seed、`tenant_admin` 来源改真租户管理员、Root 租户回退超管、新建租户 seed 钩子）→ 上线终检 → 拉起并切流量；GOV-03 三档 seed + `bisheng-app.yaml` 选档 / 默认轻量；应用态流转；WB-14 发布面最小（审批状态与驳回理由、撤回、可见范围区、入口链接）；元信息随 deploy 更新 | 审批人审读视图（文件树 / 代码 / 差异）与临时预览实例；能力总线注入通道（模型 / 知识库）与收回错误态；应用运行期凭据自动签发 / 回收；结构演进（改删列确认 + 迁移前快照）；WB-15 版本差异；资源档位管理 tab（超管改规格）；下线态提交 / 重新上线叠加容量校验；`withdraw` 终态守卫；事件触达全表 |
| **F056** app-square-governance | client 应用广场接入「托管应用」（卡片 + 按可见范围过滤 + 点击进 `/apps/{slug}`）；卡片 ⚙️「管理权限」对 `app` 类型可用（复用 PermissionDialog）+ 发布面可见范围区（状态 + 设置按钮 + 「仅 owner 可见」提示）；发布 / 上线 / 可见范围变更三类审计事件 | 审计查询面「对象应用」筛选与导出、超管租户筛选；GOV-07 ⚙️ 菜单裁剪的回归验证（实现归 F054）；`create_app` 复用验收；事件触达接线；标签体系接入验收 |
| F050 / F051 / F052 / F057 / F058 / F059 | **不在纵切上**（表单问卷不用平台能力、不走委托、不需 MCP / 模型面 / SDK / k8s） | 全部随各自 spec / design / tasks 正常推进 |

---

## 3. 114 环境事实与技术路线锚点（design 必读）

- **114 = 个人远程开发机**：真 git 检出 + systemd 管理后端进程 + `bash /opt/bisheng-ops/deploy.sh` 一条命令部署（memory `reference_remote_dev`）；docker 可用（onlyoffice 等容器已在跑）；MySQL / Redis / MinIO / ES / Milvus / OpenFGA 齐备且 F048 权限模型已实装（3.0.0-beta1 已完整部署，见 memory `project_114_full_deploy_30beta1` 的三陷阱：rsync 孤儿撞表 / pkill 按 cgroup 过滤 / 两端 `LC_ALL=C`）。**⚠️ health 200 会骗人（admin 短路 ReBAC）**——步 6 必须用非管理员账号验证。
- **compose 单机形态**（GOV-10）：runtime-manager 与 app-proxy 各为独立进程（systemd 服务，与 backend 同机），**backend 零 docker 依赖**（`scripts/arch-guard.sh` 应能守住：backend 代码不得 import docker SDK / 直连 socket）；runtime-manager 唯一持 socket，纵切内可直连 dockerd、纵切后加 `docker-socket-proxy` 端点白名单（《调研》§2.6 要点 3）。
- **构建路线**：平台持有 Dockerfile 模板 + 基础镜像矩阵（`runtime: python3.11 | node20 | static`），开发者与 AI 不写 Dockerfile；依赖经自托管镜像源（114 上先用可达的 PyPI 镜像，air-gap 的 devpi / verdaccio 纵切后补）（《调研》§2.5，Railpack / Nixpacks 已否决）。
- **崩溃自愈**：下沉 docker restart policy（指数退避内置）；runtime-manager 只补「unhealthy-but-alive」轮询重建与部署切流量（Dokku CHECKS 语义：新容器 health gate 通过才切上游、旧容器宽限退休）（《调研》§2.6 要点 1/2/4）。
- **app-proxy**：自研（不套 oauth2-proxy）；**剥离客户端伪造的 `X-BiSheng-*` 头必须按下划线 / 连字符 / 大小写归一化等价类匹配**（oauth2-proxy CVE-2025-64484，《调研》§2.3 设计前提级红线）；WS 长连接三条不变量（握手定死有效期 / 吊销事件主动断连 / 前端重握手常态）纵切内至少落第一条（《调研》§2.9）。
- **per-app 数据库**：小档 SQLite-per-app 绑定「单实例 + 本机卷」硬约束（WAL 不上网络存储）；快照走 tar 上 MinIO（《调研》§2.7）；纵切只做 SQLite 小档，Postgres schema-per-app 中档纵切后。
- **沙箱档位**：114 为 x86_64 虚机 → 默认 Docker 加固档（read-only rootfs + no-new-privileges + 出站白名单）即可；gVisor-systrap 为推荐档，纵切后评估（《调研》§2.4 / §3）。
- **入口路由**：114 的 nginx 静态 conf 增 `/apps/` → app-proxy 一条 location；client 广场卡片跳转 `/apps/{slug}`；平台 cookie path=/ host-only → 同源免二次登录零后端改造（discovery §2.9）。
- **权限**：`app` 资源类型注册进 F048 权限体系（catalog + OpenFGA 模型 + 前端 `ResourceType` union）；**存量环境「只写一次」缺口**——Catalog 范围表变更需新写运维脚本或扩展变更类型（discovery §5 风险 1），114 是存量环境、必须前置演练；授权走既有 `PermissionDialog`。
- **审批**：`approver_resolver` `tenant_admin` 分支须改用 `TenantAdminService.list_tenant_admins`；Root 租户恒空 → 回退平台超管；`_init_default_approval_scenarios` 参数化 `tenant_id` 并挂到 `tenant_mount_service`（PRD-1 §3.3 锚点表 ⚠️ 阻塞前置）。114 若为单租户形态则命中「回退超管」分支——演示前先确认 114 的多租户开关状态。
- **114 实测环境事实（2026-08-17 只读预检，实现与部署直接按此）**：
  - **docker 28.3.3**（Server），6 个容器在跑。⚠️ 关键：28.x 仍是 **iptables 后端，`DOCKER-USER` 链可用**——《调研》§2.8 说的「Docker 29.0.0 nftables 后端无 DOCKER-USER 链」在 114 上**不命中**，出站白名单的 L2 兜底可直接按 iptables 方案做。
  - **8 核 / 31G 内存，已用 18G、available ≈ 12G**——容量准入阈值必须按**实际 available** 配（不是总量）；轻量档 1C/2G 可同时跑 2–3 个演示应用，性能档 4C/8G 只够一个且会挤压平台本体（RT-08「平台必须正常」在这台机器上是真约束）。
  - **nginx**：`/etc/nginx/conf.d/bisheng-lilu.conf` 是本环境入口 conf，`/apps/` location 加这里（另有 `bisheng-external-13000.conf` 外网快照入口，外网演示需同步改）。
  - **运维脚本**：`/opt/bisheng-ops/` 下有 `deploy.sh`、`smoke.sh`、`stop-legacy.sh`、`systemd/`——runtime-manager 与 app-proxy 的新 systemd 单元放 `systemd/`，部署增量改 `deploy.sh`。
- **UI 参考**：`000-prd1-discovery/ui-demo/`（Claude Design 交互稿 `应用工场 v2.dc.html` / `服务账号管理.dc.html` 及结构化摘要 README）；以 PRD 为准、demo 为参考。

---

## 4. 文档与实施顺序（全自动模式）

1. **文档**（每份经 `/sdd-review`，★ 按建议自动拍板并在 §4 决议记录留痕）：F049 design + tasks → F054 spec + design + tasks → F055 spec + design + tasks → F053 spec + design + tasks → F056 spec + design + tasks；其后 F050 / F051 / F052 / F057 / F058 / F059 的 spec 补齐（design / tasks 随实施推进）。
2. **实施**（按各 tasks.md 的 `[MVP-114]` 波次）：F049 首波 → F054 首波（先在 114 演练 `app` 类型注册与 runtime-manager 拉容器）→ F055 首波（含审批三前置）→ F053 首波（CLI）→ F056 首波（广场 + 授权）→ 114 联调剧本 §1 → `/e2e-test`。
3. **每轮部署 114**：`bash /opt/bisheng-ops/deploy.sh`；新增 runtime-manager / app-proxy 两个 systemd 单元与 nginx location 由 F054 tasks 交付部署脚本增量。
4. **限流 / 熔断**：遇模型限流则 60 分钟后重试同一步；每轮结束在本文件 §5 追加进度行。

---

---

## 6. MVP-核心（预算受限版，2026-08-17 用户定调）

> **用户定调**：总额度可能不足以支撑全部需求，**高优开发最小闭环**——只支持「本地开发的应用部署到 BiSheng 平台并被同事使用」这一条链路，**不要求集成平台能力**（知识库 / 模型 / 身份工具 / SDK / MCP 全部不做）。本节是 §2「首波」的再裁剪：**只做打勾项**，其余连纵切首波里的项也顺延；各 Feature tasks.md 以 `[MVP-核心]` 标记（是 `[MVP-114]` 的子集）。

**闭环剧本（不变）**：管理员建服务账号 + 签密钥（勾 `app:manage`）→ 开发者 `bisheng login` → 本地写表单问卷（python3.11，标准库 + 平台注入的 SQLite 连接）→ `bisheng deploy` → 预检 / 扫描 / 预置审批 / 上线 → owner 设可见范围为全员 → 同事从广场打开 `/apps/{slug}` 提交问卷 → owner 看日志、可下线。

| Feature | `[MVP-核心]` 只做这些 | 顺延（含原首波项） |
|---|---|---|
| **F049** | 凭据底座（生成 / 哈希 / 校验 / 撤销 / 掩码 / 一次性展示）；服务账号（类型标识 + 租户直写 + 资源归属人字段 + 登录守卫公共 1 处 + `/user/list` 数据层排除）；权限位常量注册表（含三扩展位，本期只消费 `app:manage`）+ 开放能力层开关（常量级）；v2 鉴权 `Depends`（HTTP）供 F053 / F055 新端点；**最小管理页**：platform 一页 = 服务账号列表 / 新建（名称 · 描述 · 归属人）/ 签发（勾位 · 一次性展示）/ 撤销；`whoami` 端点 | 36 端点 + 2 WS 接入、share-token、主体侧授权页、四处缺陷修复、`default_operator` / `enable_guest_access` 移除、审计事件全覆盖、批量撤销、编辑、列表新列、租户对账矩阵 |
| **F053** | CLI 包工程（wheel + 平台下载端点）+ `login`（存凭据）+ `deploy`（打包 → 上传 → 分阶段输出预检 / 扫描 / 审批单 → `--wait` 到终态）+ `logs`（简版） | `skills sync` 与两包、`dev`（迷你代理 / 本地 sqlite）、接入信息区、`login` 拒 `delegate`、多平台凭据、版本兼容校验 |
| **F054** | App / AppVersion / AppInstance 模型 + 状态机（草稿 / 已上线 / 待上线 / 已下线 / 已删除）+ 五个状态动作（含审计）；`app` 资源类型注册（catalog + FGA + 前端 union + 114 存量生效脚本）；runtime-manager（独立进程、直连 dockerd、意图 RPC：build（python3.11 Dockerfile 模板）/ start / stop / status / logs / 探活 / 容量准入；restart policy + healthcheck + 轻量档限额；本机卷 SQLite + 同名连接变量）；app-proxy（`/apps/{slug}`：验平台会话 → 可见范围 → 应用态 → 剥离伪造头（归一化）→ 注入身份头 → 反代 HTTP；未登录重定向回跳、无权限 / 已下线 / 不存在页）；nginx location + 两个 systemd 单元 + deploy.sh 增量；platform 构建页「托管应用」类型 + 卡片（含 ⚙️ 管理权限 / 删除裁剪、上下线开关）+ 详情页最小（发布 tab：应用态 + 入口链接 + 下线 / 重新上线 + 手动上线；运行日志 tab）；工场运行时层开关（常量级） | 出站白名单、docker-socket-proxy、WS 三不变量、过渡态页、附件存储、数据面、备份手册、访问记录留痕、预览入口、二维码、`node20` / `static` 模板、容量准入以外的稳定性验收自动化 |
| **F055** | 管线端点：接收包 → 快照入 MinIO → 预检（manifest 校验 · 调 F054 build / 探活）→ 密钥扫描（基础规则集含 `bs-sak-`）→ 版本记录 → 审批单（**预置流程**：场景 seed + `tenant_admin` 来源改真租户管理员 + Root 回退超管 + 新建租户 seed 钩子；申请人 = 归属人）→ 审批通过 → 调 F054 上线动作（容量不足 → 待上线）；驳回 / 撤回 / 删除致取消；`deploy` / `logs` 服务端权限判定（`app:manage` + 归属人 owner-only）；三档 seed + manifest 选档 / 默认轻量；元信息随提交更新；发布面最小区块（审批状态 + 驳回理由 + 撤回）；审批状态只读接口 | 审读视图、临时预览实例、能力总线（模型 / 知识库）注入与收回、应用运行期凭据、结构演进与迁移快照、WB-15 差异、档位管理 tab、`withdraw` 守卫以外的事件触达全表、发布面提交入口 |
| **F056** | client 广场接入托管应用（卡片 + 按可见范围过滤 + 点击进 `/apps/{slug}`）；发布面 / 卡片 ⚙️「管理权限」对 `app` 类型可用（复用 PermissionDialog）+「仅 owner 可见」提示 | 审计查询面扩展、导出、超管租户筛选、GOV-07 验收、事件触达接线全表、标签接入验收 |
| F050 / F051 / F052 / F057 / F058 / F059 | **全部顺延**（spec 已定稿留档） | — |

**文档策略（省额度）**：F054 / F055 / F053 / F056 的 design + tasks 改用精简流程——单写手（复用已落盘的探查笔记：`~/.claude/jobs/b4f8a315/tmp/f049-notes/`、`f054-notes/`）→ 单路审查（清单 + 代码断言合一）→ 就地修订；tasks 只细拆 `[MVP-核心]`，其余任务只列标题与 AC 覆盖、不展开。**实施策略**：按 F049 核心 → F054 核心 → F055 核心 → F053 核心 → F056 核心 → 114 联调的顺序，每个任务一个实现 agent（Test-First 从简：核心逻辑单测 + 114 手动验证），每波结束部署 114 冒烟。

## 5. 进度日志

| 日期 | 进度 |
|---|---|
| 2026-08-17 | 纵切定义；spec 层地基就绪（F049 spec 65 AC 定稿、拆分 v2、契约）；两 PRD 残留已回修；开始 F049 design / tasks（工作流） |
| 2026-08-17 深夜 | F054 / F055 spec 亲写并经独立审查修订（各 65 AC）；F053（50 AC）/ F056（45 AC）spec 由 agent 写出、F053 按审查修订中、F056 审查中；F051 / F052 spec 写手启动；契约新增候选 AppManifest（F055 owner）、INV-36 补审批例外、N4 收口、⚙️ 裁剪归 F054；PRD-1 DEV-01 ① 表 `dev` 单元格回修；Claude Design 交互稿已提取到 ui-demo/；F049 design 工作流仍在探查阶段 |
| 2026-08-17 04:xx（用量上限检查点） | **spec 层已齐 8/11**：F049 / F053 / F054 / F055 / F056 定稿（均经独立审查修订）、F051（33 AC）/ F052（45 AC）已写、审查中；未写：F050 / F057 / F058 / F059。**design + tasks**：F049 工作流在 design 写作阶段（4 份探查笔记在 `~/.claude/jobs/b4f8a315/tmp/f049-notes/`）、F054 工作流刚启动探查（笔记目录 `f054-notes/`）；F055 / F053 / F056 工作流未启动。**契约待办**：F052 / F054 / F055 spec 定稿后把表 1 候选（App/AppVersion/AppInstance、ResourceTier、审批场景预置、AppManifest）与候选 INV-32~36 转正。**恢复方式**：重新 `/loop` 同一 prompt；先收 F049 / F054 工作流结果与 F051 / F052 审查报告（审查修订仍走「写手 SendMessage 就地修订」），再依次启动 F055 → F053 → F056 的 design+tasks 工作流（脚本模板 = `~/.claude/projects/-Users-lilu-Projects-bisheng/b4f8a315-*/workflows/scripts/f054-design-tasks-*.js`），随后补 F050 / F057 / F058 / F059 spec，最后进入 [MVP-114] 实施 |
| 2026-08-17 05:xx（限额恢复，用户「继续」） | 恢复 F049（从缓存续跑 design）与 F054 工作流；F052 审查 17 条已裁定回写手（应用数据工具改**读写**、类型不支持统一为「不可及」、能力收回信号、owner 提示口径对齐 F055）；F055 AC-07 补「门面支持类型」、F054 AC-56 补每应用数据库服务端接口供 F052 复用；F051 审查重跑；F057 / F059 spec 写手启动 |
| 2026-08-17 10:xx（用户取消 loop） | 11/11 spec 已写；F050 审查完成 15 条**待修订**（要点：subject 口径统一为「模式 S 记密钥主体自身、模式 D 记被代表用户」并与 F051 AC-22 / F055 AC-55 对齐；On-Behalf-Of 头值仅 user_id 需回写伴生 PRD §3.2 / §4.4.4；AC-48 错误码详表移 design；F049 AC-33 / AC-39 补「随 F050 取代」标注；开放 API 逐调用审计记录对象登记契约表 1）；F058 修订 agent 续跑中；F049 工作流在 design 修订阶段；F054 工作流第 4 路探查疑似被机器休眠打断（恢复：TaskStop 后 resumeFromRunId）；F055 / F053 / F056 design 工作流未启动。**恢复方式：重新 `/loop` 同一 prompt** |
| 2026-08-17 11:xx | **F049 design + tasks 完成**（design 13 决策 / 27 坑，双审 26 条已修订；tasks 76 任务、Wave 1–2 = 40 条 [MVP-114]、65 AC 全覆盖，清单审 21 条已修订）；F058 spec 定稿（36 AC）；**下一步**：F050 15 条修订 → 恢复 F054 工作流（TaskStop wsrprnq5h + resumeFromRunId）→ F055 / F053 / F056 design+tasks 工作流 → 实施 F049 Wave 1–2 |
| 2026-08-17 11:xx（用户定调预算受限） | 收敛为 **§6 MVP-核心**：不集成平台能力（F050–F052 / F057–F059 全部顺延），只做「本地应用 → deploy → 托管上线 → 广场可用」闭环；文档改精简流程、实施按 F049 → F054 → F055 → F053 → F056 |
| 2026-08-17 13:5x（第二次限额恢复） | 11:50 触限：批 A 未落盘、F054 / F055 精简工作流全失败。恢复：批 A 续跑（从 T001 逐任务落盘）+ F054 精简工作流重跑；F055 排队（并发降到 2 路防再触限）。**教训：三路重活并发约 1 小时即触限，实施期保持 ≤2 路** |
| 2026-08-17 14:xx（跨 Feature 裁决 5 项） | F053 tasks 补审查 14 条已采纳并提交（`f01e50663`）；抛回的 5 项裁定如下 —— ①**F053 design 事实回正**：runtime-manager 的 `logs` 端点批 4 已实现（`d693feeb3`），真正的断点是中段 **F054 T057（backend 转发）+ F055 T039（权限判定）**，坑 18 / 依赖表已改，并补齐 manager 侧口径（`since` 收 epoch 秒或 `30m/2h/7d`；带 `keyword` 时行数 < `tail` 是设计；dockerd 宕机 503→`16121`，404 只表示实例不存在）；②**AC-10 补限定**：可区分粒度只到「密钥类失效 / 平台不可达 / 未部署开放能力层」三组，组内不细分（F049 已把不存在 / 已撤销 / 已过期收进同一个 `26002`，服务端不给区分信号），CLI 不得臆造区分；③**F055 design D5 ★ 拍板：`secret_scan` 提前到 `precheck_*` 之前**（详见 F053 spec 决议-13 —— 扫描输入是源码包不依赖构建产物、失败更快、DEV-04 四步是逻辑分组非顺序契约；这是对 PRD 字面顺序的自觉偏离），F053 AC-31a 已同批改，**F055 design D5 + `STAGE_LABELS` + README 待批 2 收工后回写**（并发写者冲突，不与批 2 抢文件）；④AC-27 与 `contracts-runtime-manager.md` §5 的缺口（模型协议面 base URL 与凭据、附件存储句柄未列入注入清单）**登记为 Wave 4 顺延项**——MVP-核心不集成平台能力，CLI 开工前不阻塞；⑤`logs` 的 114 联调排期正式挂在 **F054 T057 与 F055 T039** 之后，两者均在 MVP-核心波次内，不是新增依赖 |
| 2026-08-17 15:xx（F055 Wave 2 + F053 CLI Wave 1 落地） | **F055 Wave 2 完成**（`f16dd2d3f`，T008–T023，147 passed）：manifest 校验 / 包安全解压 / 密钥扫描 / 资源档位 / 版本记录 / 预检 / accept+run_pipeline / Celery 任务；**D5 扫描前置已随该批一并回写**（`PIPELINE_STAGES = scan → build → probe`，F055 spec AC-01 与 design D4 阶段表 / §4.1 数据流 / 114 步骤全部同批订正）。**F053 CLI Wave 1 完成**（`8c3b63973`，T001–T018，138 passed）：新工程 `src/bisheng-cli/`，依赖上界三件套闭环（上界 + lock + wheel 装机冒烟，default 与 `--resolution highest` 双腿验）。**本轮另两项裁决**：①`26004`/`26031` 新开 **exit 18「缺陷类」**（判据=动作是否不同：exit 1 值得重试、19 可改参重试、18 两者都无用只能报障；把已登记码映到「未登记」那一格还会给假标签）；②**硬链接改为按普通文件打包**——design D4 要求跳过的前提是假的，`packaging.py` 手工构造 `TarInfo`(REGTYPE) 再 `addfile` 的写入路径根本产不出 hardlink 成员，跳过只是白丢内容。**已知待清**：F055 的 conftest 为 F054 缺席的服务层立了 `sys.modules` 占位（否则约 40 条断言会全绿于缺席），F054 服务层落地后要改回 patch 真模块。**在跑**：F054 T032–T035 + T046–T057（入口鉴权 + 领域服务 + 状态动作/读侧 API，解 F055 与演示的最大阻塞）· F053 CLI Wave 2（三条命令，纯 mock；**平台侧分发端点 T027–T031 与 T034 回写本轮不做**，避与 backend 并发写冲突） |
| 2026-08-18 · **MVP 代码面完成** | 六批并行实施全部收口，门禁 `test/app_runtime + test/app_publish` **583 passed / 7 skipped / 0 failed**，624 routes、单 alembic head、check-i18n 无漂移、platform lint 0 / typecheck 0。**演示链路端到端的代码已齐**：`bisheng login/deploy/logs` 三条命令 + 平台分发端点与 CLI wheel 产物（F053 33/50）· 应用领域与运行时 + 构建页第三类型 + 应用详情页（F054 70/104）· 发布管线与审批流 + `/api/v2/apps` 四端点（F055 42/70）· 应用广场与治理（F056 19/33）· 开放 API 鉴权基线（F049 33/76）。**表单问卷示例应用**在 `examples/apps/form-survey/`（零依赖纯标准库，三个消费侧都验过）。**114 部署契约**三件已在真实环境校验：nginx 两份同构过 `nginx -t`、systemd 两单元过 `systemd-analyze verify`、compose profile 实测「不带 --profile 是 11 个 service、带上才 13 个」。**本轮解开/修掉的四个真缺陷**：①迭代发布链路被状态机挡死（缺 `online→online` 边，审批通过后抛 16102）②`app.release.*` 写库却在审计页筛不出来（前端半边 16 条全缺）③`pack_cli_wheel.sh` 的首个校验因 `pipefail` × `grep -q` 的 SIGPIPE 在正常 wheel 上谎报失败 ④CLI 在 git 仓库子目录里认不出 git，导致上层 `.gitignore` 失效、被忽略的文件（可能含凭据）会被打进包。**下一步 = 114 联调**（顺序不可换：`deploy.sh` 发代码 → 再往 `config.yaml` 加 `app_runtime` 键 → 全进程重启 → 装 systemd 两单元与 nginx location），随后补 F056 的 T016/T021（需真 FGA + 非管理员账号）|
