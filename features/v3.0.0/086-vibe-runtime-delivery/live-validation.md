# F086 真实部署验收记录（更新至2026-10-21）

**Docker 主链路通过；完整 SDD 交付门仍有未完成项。** 本记录保存2026-10-20验收时的工作树结果，基线 `4aa9ce69b2830b81162fe631b9c801057c40ee8b`。验收当时没有提交、推送、合并或发布 Docker Hub 镜像。

2026-10-21用户授权“提交推送代码先”：将当前实现与证据作为阶段性成果保存到功能分支，未完成的验收与发行门保持开放。

## 1. 环境与证据边界

| 环境 | 实际执行 | 边界 |
| --- | --- | --- |
| 109 / Linux amd64 / Docker 24.0.5 / CentOS 7 | 独立 MySQL、Redis、MinIO、OpenFGA、backend/worker、socket proxy、manager、app-proxy、egress、nginx；API/CLI 发布与故障验收 | 全部资源使用 e2e-f086 名称、独立目录/库/网络。没有发布宿主端口，没有切换原业务镜像或配置 |
| 本机 / Orbstack Linux arm64 / Docker 29.4.0 | 七个镜像原生构建；Python、Node、static 禁网准备/启动、代码更新、缓存、SQLite helper/备份、Node 安装钩子/前端编译、CPython C扩展离线构建与源码变更失效 | 原生 ARM64 容器，非 QEMU。该层使用内存产物端口，不能代替第二套完整平台 E2E |
| 189 / K8s v1.28.15 | 只读前置检查：单节点 Ready、Calico v3.27.4、系统 Pod Running | 无 StorageClass/PV/RuntimeClass；动态卷供给未配置。未创建 namespace、Pod 或策略，未证明 NetworkPolicy 实际执行。F059 只有 spec，没有可部署执行器 |

基础镜像最初受 Docker Hub 网络阻塞；之后使用用户提供代理和经官方 SHA256 校验的 crane 转存镜像，没有修改主机 Docker daemon 代理配置。服务和应用仍为独立进程。只有 socket proxy 持有 socket；测试 manager 也通过 TCP proxy 访问 Engine。一次性驱动器直接挂 socket 的提案曾被自动审批拒绝，已换用上述方案。

backend 测试镜像复用主机缓存层，并按当前 `uv.lock` 执行 `uv sync --frozen --no-dev`；API/worker挂载当前源码。前一个缓存镜像的 MCP 版本不匹配不能作为 F086 缺陷，已纠正后再验。新装多租户模式曾出现 `Missing tenant context`，完整旅程因此按默认单租户模式执行；未把它登记为多租户部署通过。

## 2. 已执行旅程

| 场景 | 结果及实际断言 | 日志 |
| --- | --- | --- |
| MySQL 真并发 | 强制12个请求同步读取插入前状态；一份幂等操作、一次容量分配、跨租户竞争最后容量、唯一归属、外层回滚和范围拒绝；5 passed | [最终 SQL 结果](e2e-evidence/2026-10-20-docker/logs/sql-race-final.log) |
| 首次发布 | 专用 SAK 上传 → MinIO 源码快照 → Celery 扫描 → manager 下载/准备 → 临时容器探活 → 版本/审批 → 正式上线 → nginx/app-proxy/HTTP；owner 数据 helper 可查询 | [首次上线](e2e-evidence/2026-10-20-docker/logs/approve-and-access.log) |
| 代码更新和复用 | v1→v2 的 dependency artifact ID、environment key相同；代码实际更新。SQL 事实另存，未以内容相同冒充缓存命中 | [交付事实](e2e-evidence/2026-10-20-docker/evidence/control-records.txt) |
| 审批预览 | 第三版预览 HTTP、SDK CRUD 成功；预览迁移新表时生产库没有该表，正式批准后回收预览 | [预览](e2e-evidence/2026-10-20-docker/evidence/preview-v3.log) |
| SQLite 结构更新 | 新增 notes 表前保护旧写入者、保存并确认快照，再执行 DDL；上线后数据保持 retained | [结构更新](e2e-evidence/2026-10-20-docker/logs/approve-v3-snapshot-sdk-ws.log) |
| owner 恢复 | 读取当前 generation CAS，修改数据，再恢复此前快照：值和表结构恢复，代码仍为v3；保护当前库的新快照也已确认；停用状态恢复不自动上线，resume仍保留数据 | [恢复](e2e-evidence/2026-10-20-docker/logs/restore-lifecycle.log)、[审计](e2e-evidence/2026-10-20-docker/evidence/restore-audit.txt) |
| SDK 和 WebSocket | 正式入口 SDK0.1.1 put/get/list/stat/delete 经 backend 完成；真实 nginx/app-proxy WebSocket回显通过；同租户非owner与非owner超管恢复均16105 | [实际调用](e2e-evidence/2026-10-20-docker/logs/approve-v3-snapshot-sdk-ws.log) |
| manager 不可用 | 停止独立manager后6次HTTP仍200，SDK存储仍可用，应用容器ID没有变化；随后恢复manager | [入口独立性](e2e-evidence/2026-10-20-docker/logs/manager-independence.log) |
| backend 不可用 | 停止测试backend后6次入口均503，未放行应用数据；随后恢复backend | [拒绝访问](e2e-evidence/2026-10-20-docker/logs/backend-failclosed.log) |
| 离线缺包与补包 | humanize依赖未供应时审批前16227失败，旧v3在线；联网准备机下载wheel，owner导入私包，实际CLI wheel以普通SAK重发，自动消费绑定材料；v4批准上线且import依赖成功 | [缺包](e2e-evidence/2026-10-20-docker/logs/publish-v4-missing-material.log)、[CLI](e2e-evidence/2026-10-20-docker/logs/cli-offline-retry.log)、[上线](e2e-evidence/2026-10-20-docker/logs/approve-v4-offline-supply.log) |
| Nginx 与材料入口 | 真实nginx -t验证静态和平台配置；2,218,132字节离线包经nginx上传、后端哈希验证后成功，随后禁用该测试材料；未实际上传2GiB | [Nginx](e2e-evidence/2026-10-20-docker/logs/nginx-main-check.log)、[大包](e2e-evidence/2026-10-20-docker/logs/large-material.log) |
| 完整应用镜像 | 本地不可变Image ID，经预检/审批上线，nginx/app-proxy返回200；owner停用、删除 | [额外交付结果](e2e-evidence/2026-10-20-docker/evidence/extra-delivery-results.json) |
| v1兼容源码构建 | 旧版清单仍走平台模板构建应用镜像，审批上线后统一入口200；owner停用、删除 | [额外交付结果](e2e-evidence/2026-10-20-docker/evidence/extra-delivery-results.json) |
| 错误端口 | 探活失败16124，修复后发布阶段为precheck_probe、原因readiness_timeout、执行阶段starting；未生成审批、正式版本0条，资源已回收 | [最终响应](e2e-evidence/2026-10-20-docker/evidence/bad-port-final.json)、[SQL核对](e2e-evidence/2026-10-20-docker/evidence/final-control-records.txt) |
| 正式删除 | 在线删除先被16104拒绝；owner先停用再删除成功，destroy completed/cleanup complete、17条预占全released、2个快照purged、本地SQLite目录和应用容器均移除 | [删除](e2e-evidence/2026-10-20-docker/logs/delete-app.log)、[清理事实](e2e-evidence/2026-10-20-docker/evidence/deletion-records.txt) |

首次两个发布尝试分别因测试预算过小和节点过期被拒绝，均没有生成审批单或留下可执行操作。其后按正式默认预算配置并修复统计耗时再继续；不把失败尝试计作上线成功。

两侧原生容器均通过五项场景，包含本地CPython C扩展在相同包版本下由源码返回42变为43，依赖产物随之失效重建。[amd64结果](e2e-evidence/2026-10-20-docker/evidence/amd64-native.log)、[arm64结果](e2e-evidence/2026-10-20-docker/evidence/arm64-native.log)。

## 3. 现场发现与修复

| 问题 | 修改与验证 |
| --- | --- |
| MySQL重复插入仍读旧快照、独占锁升级死锁 | savepoint冲突后使用共享当前读；同步竞争用例原先2 failed，修复后5 passed |
| 首次执行归属仅锁不存在的记录 | 固定节点下先锁RuntimeNode再创建/锁RuntimeAssignment；竞争归属仅一个成功 |
| 数据helper把带时间戳日志当JSON | 增加可选timestamps参数；helper读原始JSON，普通日志仍带时间戳。真实数据查询和恢复通过 |
| HTTPS构建前置不完整 | Debian源改HTTPS；Node slim补齐系统CA，保留TLS和apt签名校验；双架构镜像构建成功 |
| 多容器主机心跳过慢 | 内存使用one-shot统计并最多8路并发；109从约52秒下降到约9秒一轮。节点事实仍15秒过期，极慢Engine会阻断新写操作 |
| 节点过期只有code 0 | 映射现有16121运行时不可用，并补业务错误回归 |
| owner无从取得恢复CAS输入 | 新增owner专用GET /apps/{app}/runtime/state；普通非owner、超管非owner、外租户均拒绝，真实恢复使用该接口 |
| 预检失败的阶段和原因丢失 | Coordinator保留发布阶段，将operation ID、实际执行阶段、原因和数据风险放进details；probe/preview先记starting。新增5项回归，实际错误端口复测通过 |
| CI验证缺少真实前置/缓存证据 | Nginx检查补齐MinIO DNS和临时目录；Node提供锁文件，比较实际缓存命中；增禁网安装钩子/前端构建和源码变化失效断言 |

测试驱动器自身还修正了审批task_id/显示名字段、预览尾斜杠、等待current_version_id切换、/actions/stop路由、预先分配version_id与正式版本记录的区别，以及HTTP/1.1回显握手；这些不登记为产品缺陷。源码包、镜像与预览的参数均按真实API调整，未绕过审批、owner检查或内容校验。

## 4. 2026-10-20的未完成项（当前进展见第8节）

- DM8真实驱动、DDL、唯一约束、并发/savepoint及业务事务切换；已向用户请求独立测试schema。
- 新装多租户启动问题与完整跨租户/OpenFGA部署旅程；已有SQL/ASGI跨租户检查不替代该证明。
- 全部阶段中断/取消/杀进程、最终上传确认故障、长连接权限撤销硬期限、存量升级/回退及完整应用镜像/旧source-image发布旅程。
- GitHub双原生工作流、不可覆盖发布、双架构服务索引和官方profile目录尚未实际运行/发布；本地两种架构的镜像不是正式发行。
- K8s执行器仍在F059，不能将189的节点Ready当应用部署通过。
- backend两项permission_runtime初始化失败、frontend lint 95错误/1警告均已在未修改基线复现，尚不是全绿的合入门。

因此T055/T056及正式镜像发行门仍保留未完成。阶段已确认的spec/design无需重新确认；当前报告不是可合并或已交付声明。

## 5. 本地回归与复测

- backend运行/发布与opt-in集合：1214 passed、2 failed、24 skipped。两项失败仍是基线已复现的permission_runtime初始化；skip包含6项live权限、5项未配置数据库及其他既有安全门。
- manager：437 passed、10 skipped；app-proxy 256 passed、CLI 383 passed、SDK 212 passed。变更101个Python文件通过Ruff和逐文件arch-guard。
- 扩展dev-toolkit的本机尝试遇到旧MCP版本和localhost沙箱限制；在锁定MCP 1.30.0的测试镜像复验，最终129 passed。[分发回归](e2e-evidence/2026-10-20-docker/logs/dev-toolkit-frozen-final.log)。测试驱动器还补齐按仓库相对路径读取的CLI/前端/代理文件，并移除了macOS AppleDouble元数据，不修改产品或测试断言。
- 源码和镜像原生检查均针对工作树，正式GitHub发行仍未运行；日志与不可变镜像事实分别保留。

## 6. 证据管理

2026-10-21提交前仅清除了三份证据的行尾空白，保留原始与归档SHA256，不改测试结果或JSON值。[规范化记录](e2e-evidence/2026-10-20-docker/normalization.json)。

日志为本套件白名单导出，剔除了密钥/JWT/Bearer内容；不含环境文件、身份凭据、SQL密码或MinIO访问密钥。镜像与挂载事实不导出Config.Env。已核对26个原业务容器ID仍在运行，没有替换或重启；最终清理结果单列归档。4个测试应用均为deleted，错误端口应用正式版本数为0，全部29条容量预占为released。[原服务核对](e2e-evidence/2026-10-20-docker/evidence/preexisting-services-check.json)。

测试使用[crane官方归档命令](https://github.com/google/go-containerregistry/blob/v0.22.1/cmd/crane/doc/crane_pull.md)；统计参数的含义见[Docker SDK stats文档](https://docker-py.readthedocs.io/en/stable/api.html#docker.api.container.ContainerApiMixin.stats)。

## 7. 收尾清理

109的11个专用测试服务/容器和5个专用网络已移除，测试数据库、对象存储内容、执行目录和生成凭据随`/opt/e2e-f086-20261020`删除。26个原业务容器前后ID一致，未重启或替换。缓存镜像保留，不执行Docker prune。[109清理结果](e2e-evidence/2026-10-20-docker/evidence/docker-cleanup.json)。

本机ARM64测试执行体均已回收，socket proxy及control网络已移除；189未创建任何测试资源。[ARM64清理结果](e2e-evidence/2026-10-20-docker/evidence/arm64-cleanup.json)。

上述为2026-10-20验收收尾快照；2026-10-21阶段成果已提交推送，后续验收和清理见第8节。未进入合并或公共镜像发行。

## 8. 2026-10-21：多租户修复、故障及存量升级

基于已推送检查点 `5131b81194a5fa390593e58d822bcbde52b6ca64` 继续验收；本次代码修复尚未提交。109重新创建独立测试栈和全新数据库，始终开启 `multi_tenant.enabled=true`，不使用单租户回退。backend/worker挂载本次源码，manager通过socket proxy操作同一测试Engine；没有对原业务服务做部署或修改。

### 8.1 多租户启动根因与修复

`PermissionActor.current_tenant_id` 只是业务参数，并不会设置SQL过滤读取的ContextVar。无HTTP中间件的初始化/首管理员回调调用F048投影时因此抛出 `Missing tenant context`。新增 `tenant_execution_scope` 绑定已验证目标租户，同时将visible set收窄为该租户、清除继承的admin scope和bypass；异常、嵌套及并发后恢复原上下文。系统资源和preset dashboard仍通过原F048 facade授权，没有授予额外权限或修改全局过滤器。

修复前新增回归3 failed/7 passed；修复后包含租户过滤和owner投影的组合集合56 passed。109全新多租户启动观测到18项系统资源初始化、首次管理员注册登录通过。初始容器随后因升级演练被替换，启动值以[明确标注的现场观察](e2e-evidence/2026-10-21-docker/quality-and-startup-observation.json)保留，不冒充归档的完整启动日志。通过正式部门挂载与成员API建立两个子租户，在租户2使用普通owner的SAK发布、真实子租户审批人批准并上线；普通非owner位于租户2，外租户用户位于租户3。

[六项live权限测试](e2e-evidence/2026-10-21-docker/logs/live-boundaries.log)全部通过、无skip：owner可读快照和运行状态；同租户非owner及外租户用户不能读/恢复；普通owner不能修改全局运行环境。首次子租户没有审批人导致审批异常，按正常管理API授予专用审批人后由该审批人重试，没有绕过审批或直接写权限表。

### 8.2 实际故障结果

| 场景 | 实际结果 | 证据 |
| --- | --- | --- |
| 探活中取消 | owner正式取消接口；cancelled、cleanup complete、无审批，全部预占released | [取消/超时](e2e-evidence/2026-10-21-docker/cancel-timeout-results.json) |
| 探活任务超时 | 缩短专用SQL操作deadline；上层先返回超时，随后确认manager timed_out和清理，不能以首个超时响应冒充释放 | [超时确认](e2e-evidence/2026-10-21-docker/logs/timeout-confirm.log) |
| 安装钩子中取消 | 真实禁网Node resolve容器已运行慢postinstall后取消；无审批、临时容器及scratch回收、预占released | [安装取消](e2e-evidence/2026-10-21-docker/install-cancel-result.json) |
| 前端编译中超时 | 真实compile容器执行慢build脚本后缩短deadline；timed_out、cleanup complete、无审批、预占released | [编译超时](e2e-evidence/2026-10-21-docker/compile-timeout-result.json) |
| 探活中杀manager | SIGKILL专用manager，原probe容器ID保持；重启接续同operation，一次审批，随后回收probe | [重启结果](e2e-evidence/2026-10-21-docker/restart-probe-result.json)、[容器前ID](e2e-evidence/2026-10-21-docker/restart-probe-before-ids.txt)、[后ID](e2e-evidence/2026-10-21-docker/restart-probe-after-ids.txt) |
| MinIO成功、SQL确认失败 | 专用触发器只拒绝该应用snapshot变verified；对象真实存在但confirmed_at为空，生产新表不存在、旧数据保留、入口503；保留唯一未确认本地备份 | [快照故障与重试](e2e-evidence/2026-10-21-docker/snapshot-confirmation-fault.json)、[备份哈希](e2e-evidence/2026-10-21-docker/protected-backup-facts.json) |
| 同审批重试上线 | 移除专用触发器，通过manual-publish重试，同一审批确认快照并完成迁移，版本2返回200 | [重试](e2e-evidence/2026-10-21-docker/logs/snapshot-fault-confirm.log) |
| DDL后新实例退出 | probe使用隔离库通过；正式库DDL已提交后按测试数据条件退出。operation标记maintenance及data_may_have_changed=true，新表和业务数据都保留，没有自动恢复旧库。版本4兼容更新后仍读到production-marker | [DDL后启动故障](e2e-evidence/2026-10-21-docker/migration-startup-failure.json) |
| 访问者撤权 | 真实Grant API添加viewer、建立WS、再移除grant，4.03秒关闭，后续HTTP403，owner仍200 | [WS撤权](e2e-evidence/2026-10-21-docker/ws-permission-revoke.json) |
| backend不可用 | 已建立WS在4.01秒关闭，后续HTTP503；恢复专用backend | [WS故障](e2e-evidence/2026-10-21-docker/ws-backend-failclosed.json) |
| 出站策略撤销 | 在真实应用内用自身凭据建立CONNECT，通过专用SQL注入撤销其唯一策略；1.27秒关闭，新CONNECT407，上游backend保持运行。该项不是公开Grant API撤权 | [CONNECT撤销](e2e-evidence/2026-10-21-docker/connect-policy-revoke.json) |
| manager不可用的独立性 | 停止超过旧3秒缓存窗口并重启，17秒观察中既有WS保持，32次新HTTP/SDK检查均成功；既有CONNECT跨故障仍可发送HTTP请求。原应用容器未更换 | [WS/HTTP/SDK](e2e-evidence/2026-10-21-docker/manager-existing-connections.json)、[CONNECT](e2e-evidence/2026-10-21-docker/logs/manager-connect.log) |

快照及启动失败时，App.state仍反映旧版本online，不应据此判定入口健康；SQL运行路由进入维护、入口实际503，并由owner操作详情提供维护/数据风险。上述断言明确检查了入口和operation，而非仅检查App.state。

### 8.3 真实存量升级与导入前回退

使用基线 `4aa9ce69` 的旧manager源码和原MinIO依赖，在协议1兼容发布链路实际构建、审批、上线版本101；SDK0.1.1在旧附件接口完成读写，并持久保存测试附件。再提交版本102，停止manager后批准，得到当前101仍服务、approved pending102的真实记录。该过程没有直接插入AppVersion或伪造审批。

维护窗口切换新协议，读取真实Engine/desired-state库存，执行正式 `scripts/upgrade_vibe_runtime.py` dry-run；随后在导入前恢复旧manager/代理，原容器、当前101、pending102与SDK均通过。回退只证明该协议1应用在导入前的回退窗口，不声明旧manager可以管理bundle版本。

再次切换协议2，以实时库存SHA256和maintenance确认执行正式CLI导入；重复调用返回already_imported。随后通过正式rebind接口使用原镜像重建，仍运行101、pending102保留；两条历史版本的冻结业务字段及terminal_state逐项一致，仅排除可变update_time。旧容器已回收，旧附件经SDK0.1.1从新backend endpoint读取成功，无源码重新提交、无新审批、无代码回滚覆盖数据库。

证据：[真实库存](e2e-evidence/2026-10-21-docker/upgrade-inventory.json)、[dry-run](e2e-evidence/2026-10-21-docker/upgrade-dry-run.json)、[回退](e2e-evidence/2026-10-21-docker/logs/upgrade-rollback-check.log)、[首次导入](e2e-evidence/2026-10-21-docker/upgrade-first-apply.json)、[幂等重复](e2e-evidence/2026-10-21-docker/upgrade-apply.json)、[版本核对](e2e-evidence/2026-10-21-docker/upgrade-rebind-result.json)、[旧附件](e2e-evidence/2026-10-21-docker/logs/upgrade-retained-attachment.log)。

准备过程中纠正了驱动器的rows.values字段、异步清理等待、待审批与approved pending字段的区别，以及重建服务后nginx DNS刷新。测试工具纯Python依赖离线提供给驱动器，没有改动服务依赖。曾尝试把SDK源码内置应用包，被既有密钥扫描识别为命中；保留扫描规则，改用内网wheel索引供应正式SDK及依赖后重发。上述不登记为F086产品修复。

### 8.4 清理、审查及当前仍缺事项

7个专用应用通过owner正式停用/删除，23条容量预占全released，3项snapshot全purged；task/previews工作区均为空。专用服务、网络、库/对象数据、配置备份和生成凭据已回收；26个原业务容器完整ID前后一致且仍运行，没有重启或替换。缓存镜像保留。

[删除事实](e2e-evidence/2026-10-21-docker/deletion-followup.json)、[工作区](e2e-evidence/2026-10-21-docker/scratch-cleanup-facts.json)、[环境清理](e2e-evidence/2026-10-21-docker/docker-cleanup.json)。证据白名单及逐文件SHA256见[证据目录](e2e-evidence/2026-10-21-docker/README.md)。

多租户启动、六项live权限、上述关键故障与真实旧应用升级/导入前回退已补验。本次未发现需要更改manager/代理产品代码的新问题；产品修复只涉及六个启动上下文实现/测试文件。通用F048修复仍未提交，后续需先落当前release line再合入派生分支。

T053、T055、T056继续保留未完成，剩余项收窄为：

- DM8真实测试经用户确认本轮暂缓；已完成模型/约束静态审查并修复BIGINT范围，不再以缺测试schema阻塞当前Feature。真实驱动/事务留中央回归。
- 全部阶段/异常组合的完整矩阵，尤其Engine build请求已发出但是否停止不可确认时的保守预占、旧执行节点失联/物理故障、上传ACK丢失及多进程接管全部组合。现有取消/超时/杀进程证据不冒充穷举通过。
- 完整客户平台断网新装、SDK20MiB边界和全部模型/检索权限组合；本次验证不能替代既有模块的全部验收。
- GitHub双原生工作流、受保护发行标签、多架构服务索引、Docker Hub正式镜像/官方profile目录尚未实际发行。
- 既有backend两项permission_runtime初始化失败和前端lint基线失败仍按第4、5节的历史结果保留，未将无关变更纳入修复。

K8s仍归F059；189未新增任何资源。当前不是完整Feature可合并声明，也未再次提交、推送、合并或公开发布镜像。

## 9. 2026-10-21验收口径调整与模型审查

用户明确本轮不做DM8真实测试，按现有模型规范与约束静态核查。15表检查通过；修复材料size_bytes和transfer offset的INTEGER溢出，新增BIGINT DDL-only扩容revision。组合28项回归通过、Alembic单head；新revision没有进行真实数据库升级，不能沿用旧schema E2E结果称其已实测。DM8实测不再是当前验收阻塞，兼容目标及中央回归安排保留。详细结果、证据边界和正式CI工作内容见[模型审查与发行说明](./model-review.md)。本轮没有触发公开镜像推送或客户部署。

## 10. 2026-10-21 GitHub测试发行与公开镜像验证

用户要求测试v3.0.0-test-vibe并明确授权更新该Tag。首轮失败仅因runner缺少rg，755d4456e5将两处改成系统grep，保留已有镜像拒绝和注册表异常拒绝。随后[Runtime delivery images](https://github.com/dataelement/bisheng/actions/runs/39567381522)三job全部成功（6m25s）；原backend/frontend CI同时成功（7m34s）。两原生架构各7镜像、原生禁网/复用/SQLite/前端/扩展集成、服务多架构索引及runtime-profiles artifact已发布。

109通过准备机代理下载及docker load验证本次公开amd64镜像默认CMD；manager/proxy健康200，代理UID10001，manager经socket proxy读Engine成功，未授权控制403/旧入口410、平台不可达入口503。无服务host端口及socket挂载。测试资源回收，原27容器完整ID不变。T053关闭，当前92/94；T055/T056仍未完成。

此测试Tag固定755d4456e5，不含未提交的backend多租户/BIGINT变更；本次不证明新迁移执行、完整平台目录导入、完整断网新装或全部故障矩阵。三份artifact元数据从GitHub页面核对，没有把本地未下载的目录写成导入成功。详情与原始公开镜像结果见[e2e-evidence/2026-10-21-ci-release](./e2e-evidence/2026-10-21-ci-release/README.md)。本节更新此前各节“尚未发行”的阶段状态。
