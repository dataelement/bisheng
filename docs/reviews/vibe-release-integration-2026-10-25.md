# Vibe 分支整合与部署记录（2026-10-25）

## 最新结论（2026-10-26）

- 三分支业务源码已推送；最新业务热修为 `f8fbe89481`，release 合并提交 `d9e6c4d4fe`。后续仅追加这份记录及脱敏证据。
- **189 单应用主流程通过**：源码包 → backend/Celery → K8s prepare/probe → 审批 → 正式 Pod/PVC → 授权 HTTP 200。示例保留在线：[打开示例](http://192.168.106.189:30101/apps/e2e-vibe-k8s-20261025/)；[平台入口](http://192.168.106.189:30101/)。访问需要登录本平台。
- **116 部署保持运行，业务验收等待资源释放**，这是用户最新确认的安排，不降低容量门槛、不停止无关服务。
- 九个普通工作树已清理；六个托管工作树归档仍为 queued，磁盘路径尚存，未计为清理完成。
- 无全量测试。新建189环境仅验收一个 static bundle 应用，不能扩展为全部语言、交付模式、SDK/OBO、升级、停止或故障场景都已通过。安装报告原15项已通过，本轮未重复执行。

## 授权与范围

用户明确要求汇总所有 Vibe 开发，依次合入并推送 `feat/3.0.0-vibe`、`feat/3.0.0`、`release`，清理对应 worktree，更新 116 Docker，并在 189 部署独立平台应用层和 Kubernetes 托管层、复用 116 中间件。本轮不新增公开 tag，不运行项目全量测试；DM8 静态、ARM 延后口径保持。

## 整合记录

- 远端起点：Vibe `5f2541f4bc`、发布线 `cd2822b7e6`、release `113f682575`。主工作区仍停留在较早发布线且有无关改动，保留原样；合并使用隔离工作树。
- 纳入治理收尾 `85faaa32c`，以及七个旧 F059 子分支。后者的业务内容已在治理基线内，完整历史汇合后对比 `85faaa32c` 无内容差异。CLI 二进制冲突保留较新 wheel，逐文件核对当前 CLI Python 源码与 wheel 一致，manifest 摘要一致；operations 冲突保留 maintenance 持久化及后续异步 purge 围栏。
- 同步最新发布线：追加文档并集；三语错误码执行按键三方合并，再经官方生成器生成六个消费端文件；用户登录冲突仅注释，保留服务账号边界说明。
- 两条合法迁移链使用新空 merge revision `vibe_merge_release_20261025` 汇合；不改写既有迁移，不做数据回填。
- F086 工作树残留的源码有已纳入部分及早于现有权限修复的部分，不用旧草稿覆盖新实现。逐文件摘要保存在证据目录；清理时由应用的 archive_worktree 保留可恢复 Git 快照，独有验收材料可恢复，不将旧验收重新算作本轮通过。

## 合入前定向检查 / 七维度代码检查

| 维度 | 结果与边界 |
|---|---|
| 边界条件 | 原 F054/F055/F056 定向证据固定到 `932fa37e1`；本轮合并没有回退分页、空值、预览或清理围栏 |
| 权限与认证 | 保留自然人当前租户作用域、可信凭据关联、OBO 拒绝顺序和独立宿主证明；合并未增加放行 |
| 并发安全 | 保留 generation/epoch、单写、异步 purge 和导出租约；不重放旧分支覆盖较新状态机 |
| 信息泄漏 | 合并文档不收集密码、token、完整环境；部署凭据仅存远端安全配置，不进入 Git |
| 测试覆盖 | 迁移单 head：1 passed；K8s purge / destroy 事实合同：30 passed；只针对合并风险，不是全量测试 |
| 代码风格 | 改动 Python Ruff、locale 官方生成器 --check、git diff --check 通过 |
| 文档同步 | F054/F055/F056 设计及提测报告保留；15 个 Vibe worktree 的归属、包含性与草稿摘要已记录 |

**代码整合审查：PASS_WITH_WARNINGS。** 此结论限本次整合，不能宣称整个 SDD 全 AC、真实增量 E2E、客户离线发行或 ARM 验收已通过。用户此次明确要求先完成合并部署；后续环境实测单独补证，不通过修改勾选状态掩盖缺口。既有两条前端类型基线问题保留。

## 部署约束和当前状态

- 116 已只读认证成功，现部署目录 `/opt/server/bisheng-test`；内存余量紧张，先更新本次授权的应用服务，配置新 runtime 前复测容量。不停止无关服务、不删除既有业务数据、不降低容量或隔离门槛。
- 189 复用先前专用 known_hosts 严格核验；8 CPU、约 56 GiB 可用内存、约 465 GiB 可用磁盘。既有 `e2e-f059-*` 应用、PVC、准入和服务继续保留，新平台使用独立命名空间/安装标识。
- 189 新平台计划复用 116 的独立数据库和 OpenFGA store；116 的 Redis 逻辑库均已有数据，因此新平台另配独立 Redis，不复用或清空现有任务队列。公开/临时桶分别配置。Vibe 私有对象由现有 UUID 应用/任务前缀隔开，当前固定私有桶设计不声称是不同平台的独立桶。
- 现有 Drone release 流水线构建 backend/frontend/sandbox 并自动更新 116。本轮 runtime 镜像另从最终 release 同一源码构建原生 amd64，固定不可变版本和 digest 交付内网，不把旧 runtime 镜像当作已更新。
- Docker 宿主证明单元、K8s 能力报告、私有材料路径和实际应用发布/升级/停止/档位选择须部署后分别验证；当前尚未在这份记录中标记通过。

证据目录：`docs/reviews/evidence/vibe-release-20261025/`。执行中的 SHA、CI 构建号、镜像摘要、环境入口和清理结果将在各阶段完成后追加。

## 实测后的窄范围修复

116 真实 `iptables-save` 将父链 `-i/-s` 选项换序，导致等价规则误判 `host_firewall_jump_not_first`。校验现复用字段规范化；仍检查父链前 N 条，额外 ACCEPT 或其他子网必须拒绝。11 个宿主隔离用例通过（包括两网络参数换序、提前 ACCEPT 和错误子网），Ruff 通过；未跑其他全量回归。

此 hotfix 七维度检查无新增 HIGH：无 API/权限/事务变化；不扩大规则、日志或清理范围；仅修正合法配置的读回比较，文档和任务已同步。真实 canary 继续复验后记录结果。116 的 systemd219 使用部署 drop-in `ProtectSystem=full` 兼容旧版，不宣称旧版支持 strict/ReadWritePaths。

## 17:59 后续实测与交付状态

### 分支与清理

远端已核对：`feat/3.0.0-vibe` 与 `feat/3.0.0` 均为 `311b81867a4c1541545c3640cd562a78f53ade6b`；`release` 为 `7cf8e14755bf01f43b5f56dcb4c079f35fdb9534`。没有 force push 或新增 tag。

已清理八个临时 F059 工作树和干净的 `vibe-app-integration` 工作树，共九个；保留分支引用，后者唯一非缓存忽略文件 `client/junit.xml` 另行备份。六个 Codex 托管工作树受置顶保护，archive 返回保护错误，尚未删除；未绕过应用保护。当前 release 执行工作树保留至部署收尾。主工作区原有四项无关改动未动。

### 116 Docker

- backend、两个既有 worker、frontend、runtime-manager、app-proxy、egress-proxy、docker-socket-proxy 已启动。backend 健康、backend `/health` 和前端 `/` 实测均为 HTTP 200；`/api/v1/env` 返回 `app_runtime_enabled=true`。
- manager 到 backend 的 heartbeat 与 plan 持续返回 200。宿主隔离真实 canary 成功，systemd 服务 `Result=success`、`ExecMainStatus=0`，定时器已启用。全部九个运行镜像逐一验证了实际 amd64 image ID。
- 前端使用内网原生构建物，私有仓库 digest 为 `sha256:328f570b3841d421f739688e89841276596f3cd1cfab07dff5fa8ec1eb5a226e`；后端为 `sha256:1963957aff6e15ec223648a687a3e11ac9b80183fbb7bd50e05d5854ae16c21e`。运行镜像基于初始 release `f5db95ecab6934c590fa32486cb15a5ff3dc2737`，宿主工具安装了 `311b81867a` 的窄范围修复；已核对初始 release 到当前 release 的 backend、frontend、nginx 源码无差异，不将旧源码标签改写成新 SHA。
- 原部署配置和约 1.1 GiB 的一致性 SQL 备份保留在远端 root 专用目录；未重启 MySQL、MinIO、Milvus、ES、Redis 或其他无关服务。
- **实际应用发布、升级、停止和资源档位业务验收尚未执行。** 自动审批拒绝使用默认应用管理员账号并持久化会话；已改为申请专用账号或明确授权默认测试账号，后续会话仅在内存使用。未绕过认证创建会话。

脱敏实测证据：`evidence/vibe-release-20261025/docker116-deployment.json`，仅包含镜像、健康状态和宿主检查结果。

### 189 Kubernetes

- 新建 `bisheng-vibe-runtime-system`、`bisheng-vibe-runtime-apps`、`bisheng-vibe-installer`、`bisheng-vibe-platform`；Helm release `bisheng-vibe-runtime` revision 1 安装成功。manager、app-proxy、egress、admission 四个 Deployment 均为 1/1。
- 新建四个 1 GiB production、三个 4 GiB scratch、两个 1 GiB preflight 专用有界 ext4 loop 文件系统及 Retain local PV；持久 systemd 挂载和 kubelet 挂载依赖已配置，未重启 kubelet。尚未把这项准备工作当作 SQLite 锁/fsync 或重启验收。
- 定向 RBAC：允许新 manager 在 execution namespace 创建 Pod；拒绝读取 control Secret，拒绝 exec、attach、portforward。使用显式 `--subresource` 验证，避免 `pods/exec` CLI 简写被错误解释成基础资源。
- descriptor 的 `probe_report` 仍为空；四个控制进程 Running **不代表运行域已 ready**。未生成虚假报告、未开启应用部署。
- 新平台 backend、Celery、Redis 和入口尚未接通，15 项真实能力探测与业务 E2E 尚未运行。自动审批拒绝 116→189 中间件凭据传输，已请求最小范围授权：新库专用账号、必要中间件凭据、新 Redis 配置，严格 SCP 直传到远端 root 文件，不传原 MySQL root 密码、不写本地磁盘或日志。未经确认未执行传输。
- 旧 `e2e-f059-*` 资源未由本次安装修改；不把旧环境证据算作这套新安装通过。单节点 amd64 不证明 ARM 或跨节点恢复。

### CI 与剩余项

最新 release CI 为 `#5632`（`7cf8e14755`），核对时 backend 构建成功，frontend 仍运行，sandbox 与自动部署尚待执行。较早 `#5629` 已被 CI 标记 killed，不能记为整条成功；未主动取消流水线。116 目前部署来自已固定的 backend 与独立原生 frontend 构建物。

下一步依次为：取得最小凭据/应用账号授权 → 接通 189 新平台 → 真实安装探测 → 两环境发布、升级、停止和档位的定向验收 → 完成受保护工作树清理。此次未跑全量测试；最终业务验收和完整镜像发行仍待完成。

## 22:40 续办：授权、环境接通和单应用主流程

### 本轮边界

用户已明确允许新库专用凭据 116→189 传输、创建独立测试账号并授予超管，以及取消置顶后清理工作树。最新测试范围收窄为部署后跑一个主流程，不做全量回归。本文后续以单应用发布、审批、上线和访问为验收目标，不继续扩展故障、升级、权限矩阵等场景。

### 已执行

1. **最小凭据传输完成。** 新账号仅拥有 `langflow_vibe_k8s_20261025` 的数据库权限，来源限制为 `192.168.106.189`；导出采用必要字段白名单。严格核验两端主机后 SCP 直传到 189 的 root-only 文件，不经本地磁盘，不传原 MySQL root 凭据。
2. **116 权限模型升级完成。** 正常注册暴露 `authorization_model_migration_required`。官方工具先 plan，再 apply、重启三个平台容器、verify；新增 `app` 的 delete、edit、manage_permission、publish、unpublish、use 六条范围，原子切换到模型 `01M5SP22S6QE32MMFVQFTGV3S2`，CURRENT Catalog 为 196。没有改写既有业务授权或使用 `force_write_model`。
3. **两环境测试账号已建立。** 116 新用户 ID 867；189 新用户 ID 1。均为本次新建账号，经正常注册/登录和明确授权的超管身份配置；密码只在各自远端 root 专用配置文件中，JWT 和临时发布密钥不进入证据。189 保留全局验证码设置，仅在运维测试进程内使用本次自身生成的验证码挑战。
4. **189 应用层已运行。** backend、Celery worker、Beat、frontend、TLS 入口和独立 Redis 均为 1/1，入口 `http://192.168.106.189:30101`；材料 HTTPS origin 为 30143。应用层由现有平台 Chart 渲染后施加部署覆盖，固定镜像 digest，通过 Secret 引用配置；运行层独立 Helm release 保持四进程。
5. **189 安装报告 15/15 通过。** 先前 PVC 绑定/清理失败源于真实控制器使用独立 ServiceAccount。已核对 `--use-service-account-credentials=true` 和对应 ClusterRoleBinding，将精确的 `persistent-volume-binder`、`pvc-protection-controller` 身份及 scheduler 写入 Chart 的同一配置源，升级到 revision 2。旧失败报告保留；修订后的实际 SQLite、原生 CRI、准入、RBAC 和网络探测全部通过，资源清理完成。manager 按既有要求单独重启后接受新基线，业务 API 已返回 `ready=true`。没有再跑业务全量测试。
6. **两环境运行镜像目录已配置。** Python、Node、static 各导入一个 amd64 原生环境版本。`official=false`，不伪造 ARM 验收或双架构正式发行。

### 尚未通过的单应用验收

- **116：容量拒绝。** 实测主机约 58 GiB 已使用、可用约 2.7 GiB；Milvus 约 32 GiB，另一个项目 backend 约 6 GiB。现有预约与保留策略计算出的 Vibe 可用预算为 1 MiB，脚本未提交新应用。不调整保留/超卖策略，不停止无关服务；已请求用户指定可释放资源或先保留 116 部署。
- **189：唯一应用已接收，准备阶段失败。** `e2e-vibe-k8s-20261025` 的 app ID 为 `c63121a2f58441df953762501fdc62d3`；首次 deployment `3685d71782c546f69a10e0adf3670495` 在 `precheck_build` 返回 16227。已定位为 Celery worker 调用 manager 的 wakeup 被部署补充 NetworkPolicy 拦截；初始规则只列 backend。异步执行资源已清理，临时发布密钥已回收；不把接收成功、控制进程健康或安装探测通过写成应用上线通过。
- **精确网络规则等待明确授权。** 自动审批拒绝将平台 backend/worker 放入 manager 入站来源，理由是部署授权未明确此网络访问范围。已提交唯一精确规则：来源 `bisheng-vibe-platform`，组件 backend 或 worker，目的 `bisheng-vibe-runtime-system` 的 runtime-manager TCP 8091，继续独立 HMAC。该规则尚未执行；批准后只重试原应用主流程。

### 交付与运行限制

- release CI `#5632` 最终状态 killed：backend 构建成功，frontend 被终止，sandbox 和自动部署跳过。因此不能宣称整条 CI 已通过；当前环境仍使用已核对的 backend 和独立原生 frontend 构建物。
- 安装报告有效期 24 小时；尚未配置自动刷新服务。当前为单节点测试安装，静态 Retain 的 scratch/preflight 卷须在核对停止证据后由安装者回收，不能无条件清 claimRef。既有测试仓库 CA 到 2026-11-05，后续镜像更新前须处理续期；本轮不改动旧仓库/旧 e2e 资源的证书。
- 已取消本任务和关联项目的置顶；六个托管工作树的归档调用目前返回 `queued`，磁盘路径仍存在，因此尚未计为清理完成。F086 忽略的本地 config 已单独按 0600 备份；未强删草稿或绕过托管工具。

公开证据新增：`k8s189-install-report.json`、`k8s189-descriptor.json`、`k8s189-mainflow.json`；待批准规则为 `k8s189-worker-control-rule-applied.json`。这些文件不含账号密码、会话或 HMAC。

## 2026-10-26：精确规则、热修与主流程通过

### 仅修正本次阻塞

1. 用户明确批准的 worker/backend → manager TCP 8091 精确入站规则已 apply，并同步回安装清单；执行应用的 NetworkPolicy、RBAC 和 HMAC 不变。证据 `k8s189-worker-control-rule-applied.json`。
2. 新建专用卷缺少 `.bisheng-volume.json`，storage-guard 按预期拒绝。确认新 execution namespace 无 Pod、九个卷均为 Available/Released、local path 与安装身份匹配且为独立 ext4 后，补齐安装标记；没有清理 claimRef 或删除卷数据。
3. 原版本 prepare 和 probe 均 completed/cleanup complete，审批通过后 outbox 暴露 MySQL `MissingGreenlet`。根因为事务内凭据 flush 未加载服务器默认 create_time，随后同步 DTO 读取触发隐式 IO。`CredentialRepository.create_in_transaction` 增加显式 await refresh，不新增 commit。测试关闭 INSERT RETURNING 后先复现，再配对验证修复及 rollback：**2 passed**；Ruff、定向架构守卫、diff check 通过。按 SDD hotfix 流程完成七维度审查，先推发布线，再由 Vibe 和 release 继承；审查见 `vibe-credential-defaults-hotfix-2026-10-25.md`。
4. 189 backend/worker/Beat 使用同一固定 hotfix digest；应用与中间件数据保持。通过既有管理员“审批异常重试”API 恢复原审批实例 1，没有手工把状态改成成功，也没有重新上传版本。
5. app-proxy 原内部 HTTP backendBase 不在本安装网络放行范围内，入口仍503。改为现有已放通的 HTTPS 平台 origin，并给原生 app-proxy 镜像加入**公开**平台 CA，沿用现有系统信任 HTTPS 方案。非 root 导入/TLS 信任烟测通过；保持 TLS 校验，不增加网络权限；同源 Helm values 保存新地址与固定镜像 digest。没有提交额外 Chart 功能。正式 data-helper 启动就绪存在短暂延迟，Service 全部就绪后复查入口成功。

### 唯一应用的最终结果

| 项目 | 实测结果 |
|---|---|
| 应用 | `e2e-vibe-k8s-20261025` / `c63121a2f58441df953762501fdc62d3` |
| 版本 / deployment | `24fcb79a0b394e6d9634e952375f8091` / `4f599876e25e4bcdaee8e1a213f183b0` |
| 交付方式 | static bundle，无外部新增依赖 |
| 审批与正式状态 | 正常审批 + 异常重试，最终 deployment=succeeded / app=online |
| 正式 Pod | Running；app、data-helper 两容器 ready，重启次数均0 |
| 资源档位 | light：应用500m CPU / 1Gi内存；helper25m / 128Mi |
| 数据卷 | 本次专用 Retain local PV `vibe-release-production-3` |
| 访问 | 经平台 nginx、app-proxy、backend 授权/路由到正式应用，HTTP200，页面标记匹配 |
| 认证材料 | JWT仅留内存；所有临时发布key均在finally正常撤销；不导出账号密码 |

完整单应用事件保留在 `k8s189-mainflow.json`（含失败历史和最终成功），最终Pod、资源、镜像及CI快照见 `k8s189-deployment.json`。示例保持在线，未为清理测试而删除业务状态。

### 明确保留的事项

- 116 等待用户释放资源再做业务验收；本轮未停止其他项目服务，也没有降低保留内存或超卖策略。
- release CI `#5635`（`d9e6c4d4fe`）核对时 backend成功、frontend运行、自动部署pending；不是整条CI成功。本环境使用已固定的内网原生构建物；只含文档/证据的最终提交使用 Drone 官方 `[CI SKIP]`，避免重复镜像构建，规则见 [Drone文档](https://docs.drone.io/pipeline/skipping/)。
- 六个托管工作树已取消置顶并申请归档，工具仍只返回queued，路径尚存；不宣称已删除，不强删F086历史草稿。普通工作树清理共九个；当前执行及hotfix工作树在记录提交后按干净/包含性/远端一致性检查清理。
- 报告24小时有效、测试仓库CA将到期、静态Retain临时卷需按停止证据人工回收等安装运维限制继续有效。未扩展为生产高可用、全离线/双架构正式发行或完整SDD全AC验收。
