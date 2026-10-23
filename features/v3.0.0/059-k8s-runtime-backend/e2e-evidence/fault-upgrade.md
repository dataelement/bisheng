# F059 故障与升级验收（进行中）

## 109 真实 prepare 取消

固定 runtime 源码 `54b3ea2c1`，专用测试平台与 Node profile revision=1。`e2e-f059-cancel-d109c2` 的真实 npm 根 postinstall 已打印固定 BEGIN 标记；按精确 app/deployment/kind=prepare 查询账本，120 秒内获取仍 running/preparing 的绑定后调用 owner 取消接口。

| 检查 | 实际结果 |
| --- | --- |
| owner cancel / 非 owner、跨租户 cancel | 成功 / 两者精确 16105 |
| 操作终态 | cancelled / operation_cancelled / cleanup complete |
| 发布结果 | 预检失败、无审批和正式版本 |
| 运行写入者清理 | 同一实际 CID 连续两次不存在，剩余该操作容器为 0 |
| 人工强制清理 | 未执行 |

应用、部署、版本、操作和实际 CID 及四份脱敏证据摘要见 [JSON](./fault-upgrade.json)。先前 d109c1 误用 revision=2 被拒绝，保留 setup 失败记录，不能计为取消验证。

## 未完成项

当前R29 manager-only升级保留Pod/CID/PVC/profile及旧false/unknown拒绝保持已经真实通过，见installation的R29记录。新R11正常stop/离线数据/resume已通过，见platform的R11记录。R3空闲manager停机访问已真实通过（见下）；189初始化失败、响应丢失、在途manager重启、独立安装域完整卸载和最终清理仍待完成；取消及M2迁移失败/快照恢复的后续实际结果见本文末尾；保留的旧unknown写入者负例不替代全部故障注入。私有工具本地测试只证明工具行为。单节点结果不能代表NodeLost跨节点围栏；T070保持pending。

## 109 实际迁移基线（尚未v2/恢复）

v1实际发布、独立审批12 executed，generation1/deploy completed与cleanup complete后，owner两次PATCH写入随机哨兵与NULL。每次写前非owner16162、跨租户16101且rows未变；两行及其SHA/随机值SHA已冻结于私有0600证据，完整ID见JSON。旧测试工具误把终态写成approved，曾在任何数据写前拒绝；修正后只对原成功发布接续两行PATCH，没有重复发布。v2失败和恢复仍待执行，不能把准备或本地SQLite repro计为平台故障通过。

189新r2先准备未到创建资源阶段，controller空闲租约已过期导致renew409与terminal fact失败；前端部署最终16227/operation_timeout，但manager op仍running/admitted/cleanup pending。未修改租约、无Pod/PVC；登记T198/T199后正常修复。旧r2 journal与失败记录保留，不原地抹去重跑。

## 189 控制器自然空闲续租复验

e405候选同一Pod/容器/holder经历自然租约过期，精确renew409后fresh claim/renew成功，epoch3→4，descriptor未变。旧已到期操作进入failed/cleanupcomplete且无资源；这不是Pod停止证明。真实业务之后的独立准备失败仍保留在platform证据。

## 189 主安装域卸载前置（静态复核）

在 `6f254f337` 的 Chart 与调用链复核中，primary release 的卸载被旧 r4 未确认创建阻断：应用 `2122578f094b4c5fb19f9669815431f2`、操作 `6031594368584d1090ba7a7a2ca8e2e4` 的 PVC 仍为 Bound，未取得原写入者停止事实。按名字 404 不构成停止证明。

Chart 卸载会删除 admission webhook、服务与 RBAC，以及执行域 NetworkPolicy、Quota、LimitRange；保留 Namespace/PV/PVC 不能替代持续围栏。当前五个业务应用即使全部停用，也不能据此卸载该 primary release。本轮没有执行卸载、移除保护或手工释放账本。

完整卸载验收须使用独立 release/installationId、控制与执行 namespace、受限服务身份、合格 PV 和独立平台配置及逻辑存储域；运行真实 SQLite 应用并确认停止与 cleanup 后，才卸载该独立域。共享 backend 的新应用默认节点及 manager/data RPC 地址是全局配置，不能临时改向新 manager 而影响 primary。仅合成 SQLite/PVC 的 Helm 保留检查最多证明存储保留子合同，不算完整平台卸载通过。

源码锚点：`deploy/kubernetes/app-runtime/templates/admission.yaml`、`network.yaml`、`rbac.yaml`、`storage.yaml`、`services.yaml`；`runtime_delivery_coordinator.py:45`、`runtime_control_client.py:21`、`runtime_data_session_service.py:113`。该项保持待验收，不将静态复核记为真实卸载结果。

## T256/T257 manager独立升级：真实189

2ac固定源码的amd64 manager原生构建及UID10001/禁网/只读导入烟测通过；内网仓库digest `5619057b1c026d9ff545f4090f6c84c9aaef5fc1050604162770c7f4d018830c`、config586bdc40…。首轮私有Git checkout umask077产生700目录/600文件，镜像生成但非root import失败；只正规化固定公开构建源码权限，内容和Git clean保持，R2另用标签/日志/结果。保留bad bd2092…及日志，未改产品Dockerfile绕过。

Helm28只更新images.manager，旧Pod30d08ee0…替换为faa48ee8-fd38-4980-a290-4b44ada8d6b4；五应用PodUID、各容器CID、PVC/PV身份全部未变，egress/admission/app-proxy的Pod与容器未重启。descriptor数据/UID、helper/assembler/profile均不变。receipt SHA `539386dafef972122991013f7b03c0e920be301df794dea3df09ea5136763e5b`，before/after SHAefe107e7…/6e7757c1…；不据此声称切换期间所有HTTP请求连续成功。

自然node heartbeat已ready/controller_epoch22，运行期15必需检查和原始安装报告16项分别通过，bundle/image/source-image三路径true；容量仍6784Mi/3125m/5实例，旧r4failed/cleanup pending及原PVC保持。root首轮核查误要求运行期16而assert失败，实际报告无故障；纠正口径后冻结真实ready文件，不改产品。owner取消、inflight重启/释放及其他故障仍待独立实测。

## 189 停用验收新增阻塞：报告与历史保护

Python应用a4a566…的单次正常停用d675d583ebb34e68b4756fe8852ff91d在原900秒后自然timed_out/operation_timeout，cleanup pending；离线driver在等待停用600秒处失败退出，未编辑数据库、未恢复上线。Pod0ca2a71e…同UID已删除中/Failed、全部init/app/helper terminated，但资源历史status/binding标志均false，分类器与backend继续拒绝确认。finalizer、PVC、容量保留，无手工SQL或强制清理。

只读五应用cohort：旧Python/Node/static均false/false，后创建source/image仍true/true，node当前ready且两项保护true。不能据此归因最近manager-only升级；首次绑定时是否为true及具体触发心跳缺历史证据。真实本地assessment→manager heartbeat→backend Service→SQLite事务五例证明TTL/helper变化会触发不可逆清零，实际guard失败与报告失效被混用。T258–T261按design4.5细化；不将修正上线视作旧false恢复。原失败journal与脱敏快照SHA见JSON。

## R11/R3 manager停机访问连续性：189真实通过

同R29 f886镜像，受限单次UID/RV CAS将manager 1→0→1；实际旧UID缺席15.931秒，5个完整轮次开始于停机后5秒之外且在up意图之前完成，owner HTTP、SDK identity/OBO、新owner WS和nonowner/foreign HTTP/WS拒绝均通过。原WS与精确原app UID/CID中的CONNECT连接贯穿停机，不重连；未证明长HTTP响应流或SDK远端模型调用。120秒原总预算、15秒最小停机保持，未使用恢复兜底。

恢复新manager UID59ace601-5974-487f-8eaf-095a6b13f015、epoch25，源码/镜像/backend两文件、descriptor及current/v1双保护独立确认；6Pod/7PVC/CID/卷投影不变。旧三false/新二true保持，旧Python held仅controller_epoch24→25正常重对账，没有追认停止或释放。主证明b397e367…、独立部署3825ca37…、inventory8184a040…完整SHA与路径见JSON。

此前R2在任何down前被裸根308拒绝；真实slash200/SDK200/WS成功后最窄修正私有工具，原失败不覆盖。该成功不替代在途操作重启、取消、响应丢失、真实DDL/恢复及独立卸载；T070仍pending。

## m2前置：两个健康专用应用正常停用（物理证明待采）

R11安全删除权限配对真实16105/16101/online owner16104，每次fresh原v1/approval12/gen3/resume保持；独立纯SELECT销毁前后均0且无活动操作。随后R11唯一stop8d71…/gen4与健康fullimage唯一stopdc0317…/gen5均已completed/cleanupcomplete。两应用保留原卷，未执行delete/data/restore，旧false/unknown不动。容量释放须待同UID停止/APIabsence/PVC/PV及预约独立证明，不由公开stopped推断。R11此时附件对象/snapshot均零样本，不能将空清单冒作非空清理验证。

m2已在新目录生成并冻结NULL→NOTNULL应用包（v1 09807c39…/1235B，v2 49d45022…/1237B），尚未发布。私有快照reader修正实际operation.deployment_id为空的关联，另经精确公开failure.operation_id证明，不改库。首版DDL观察器使用189不支持的--resource-version，被真实CLI解析阶段拒绝；尚未运行真实观察或迁移，不以31项假CLI/隔离SQLite测试替代兼容性。新原生list→watch接线待复审。

## M2 真实迁移失败与首轮显式恢复

原v2两次请求（未确认schema拒16229、明确确认后接受）只各发一次；原观察器工具超时保留parent `f07ef54c…`，新的accepted续验从同一待审批v2继续，硬拒绝deploy端点。新watch真实初始ADDED/存活进程证明后，预览四资源正常停止/清理、逐项API缺席证明 `1992d949…`，approval14正常执行。

部署 `a9e809d78cf749a0bf4f4a8b8b3f8989` /操作 `8aba1b5c7a37425393a7e9d5e6ff259c` /gen2真实16228/publishing失败，失败阶段migrating、maintenance/dataMayChanged真且cleanupcomplete。只读观察器从精确Pod UID `41905459-4212-4e23-aec8-2591a14c0762` /容器CID读到`sqlite3.IntegrityError` NOTNULL完整调用链，日志摘要 `e39c7853…`、绑定DDL证明 `e80a1f98…`，原冻结校验器独立通过（结果370e6699…），不以阶段标记代替执行DDL。

同操作snapshot_confirmed事实seq3、verified快照 `dbae5da6ab5e42328db992dd39ddde5f`（16384B，SHA `eaf3653e…`）及完整confirmed上传由backend纯SELECT证明；通过backend现有存储端口导出，原NULL与随机基线行/摘要14608a29…及SQLite integrity在恢复前纯检查通过。私有恢复脚本只修正transfer真实36位UUID兼容，原脚本/错误检查和数据不改，平台代码未因此改动。

首次显式owner restore（含非owner/跨租户拒绝配对）只发一次，接受 `4d858a521f714fc598c565e10e9dc19c` /gen3。维护helper UID `e9b0cef2-a8de-4bea-b8ee-ae969bea5af0`成功、同UID停止清理完成，恢复及保护快照结果入库；后续starting阶段POST资源登记409导致failed/cleanupcomplete，尚未证明恢复后的行和路由。静态及Service配对定位restore+serve未接入资源白名单，T270/T271修复中。原请求不重放、不自动回滚、不改failed为completed。快照去重返回同artifact，不能用新增数量证明或否认保护备份；仍须按同restore的confirmed上传核对。

## M2 第二次显式恢复：189真实通过

新journal以旧4d/gen3已知failed/cleanupcomplete为前置，只对新gen3→4发一次owner POST；nonowner/foreign各精确16105且状态不变。新restore6cd6f833513f41f6980c2fc4e66688da完成completed/cleanupcomplete，App继续current v1、pendingNone、原失败v2及approval14执行记录保持。原NULL与随机nonce行摘要14608a29…完全一致，真实入口health读到v1与同组数据；原parent5676945e…及migration_restore字段逐对象保持。

保护快照按本restore的confirmed upload db502ccf-34f9-4772-93ee-5a8a1edfe5dc确认（offset=size），对应dedup artifact dbae5da6…/16384B/SHAeaf3653e…；原producer仍8aba，不改归属来凑证明。backend现有存储端口实际下载后校摘要/大小/SQLite integrity，独立observe acceptance_complete=true。正式journal4191fe7b…、绑定2e469112…、导出回执1a502951…完整SHA见JSON；不输出行/nonce或凭据。

同操作SQL与元数据证明restore helper UIDadfd7678…已confirmed/cleanupcomplete，随后同名位置只有serve UIDbfd5c5b3…/gen4/Running；不得把同名新Pod存在说成旧helper未清理。原PVC UID8e9e3c90…/production07及PV身份保持，单个当前Pod。SQL证明6a2aa7de…、物理证明733863da…；独立审证52e77506…确认业务/保护绑定，未声称独立本地重新检查未下载的SQLite本体。

首次私有second-r1工具在读取v2状态时误用Cookie，被鉴权拒绝；新restore intent尚未生成且journal==parent，经只读确认后保留旧文件。仅修验收工具改走既有owner publish-status，新目录second-r2；未因此改平台、重放未知请求或跑全量回归。T070仍待其余故障与独立卸载，ARM/追加109/公开发行暂缓。


## R31 真实准备中取消：189通过

新Node草稿09672c6d…的唯一发布ad7c654e…绑定prepare c29cfb53…/gen1；同一安装Pod UIDba740781…的精确CRI Docker CID经四项标签与二次Pod读取确认，实际npm根postinstall BEGIN与十次WAIT、无END，240秒hook已运行54.85秒时提交owner取消。非owner与跨租户GET/cancel均精确16105；owner意图持久化后仅POST一次。公开取消完成发生于BEGIN后100.81秒，早于自然结束；最终cancelled/operation_cancelled/cleanupcomplete，发布16227/precheck_build、无审批和正式版本。

SELECT账本六资源全部cleanupcomplete，三个Pod同UID kubelet_terminal停止事实；随后物理集合与账本逐ref/kind/UID精确一致、六项自然404，预约released。原四应用Pod/CID/restart与恢复后M2 Pod UID保持；未强删、改finalizer或手工释放。草稿保留用于后续已知终态的新发布，不把历史取消请求重放。

五份原始脱敏文件摘要及完整ID见JSON；独立L1 `77e4d874…` 通过。验收工具仅修复v2 Bearer请求被登录Cookie覆盖和提交意图防重放，六项定向测试通过，不改产品、未跑全量回归。各调用有300秒总预算但分阶段无持久全局期限；本次submit意图至公开取消完成实际165.72秒，之后SQL/物理取证不冒作300秒内观测。仅关闭T070取消子项，初始化/响应丢失/在途SIGKILL/独立卸载仍待验收。


## R31 在途SIGKILL首轮：未通过，原失败保留

在新迭代f43bb953…/prepare c0fe7a9a…的真实240秒Node安装hook运行中，按manager原Pod UID56193f9b…/精确旧CID唯一SIGKILL，CLI已ACK。hook证明距BEGIN5.20秒、kill意图距BEGIN7.66秒；kubelet同Pod重启一次、controller28→29，但原prepare随后failed/execution_failed/cleanupcomplete，inputs/resolve事实保留、install未完成，正式版本仍0。观察器120秒预算包含预检，最终unknown/71次state检查异常，不能表述为71次HTTP失败或容器恢复即续办成功。

原安装UID142037c5…及另两Pod均同UID kubelet_terminal停止，六资源自然API缺席、容量released，原四应用CID/restart与M2恢复Pod UID保持；未强制清理。故障后的owner取消工具仅做新绑定前置检查即拒绝，未提交cancel；原failed/意图/unknown结果均保留。七份脱敏证据及独立NOT_PASSED报告5c8ec11f…摘要见JSON。

根因验证只围绕该链：真实backend Service/SQLite证明旧租约未到期对新holder的409/controller_lease_held不会改变prepare，epoch更换和相同模板本身可复用；真实OperationExecutor＋KubernetesExecutor最小复现证明该暂态拒绝进入业务_failure，错误处理跨自然到期后拿到新epoch并误清理正在安装的原Pod，runtime.prepare甚至尚未进入。实际故障窗只统计到10次lease_held标记，不单凭计数宣称抓到首个进程内异常。登记T272/T273，将开工前控制器准入移出业务失败处理范围；不改模板/后端围栏、不吞任意异常、不延长原deadline。修复与新操作复验尚未完成。


## R32 租约交接定向复验：189通过

按用户最新范围，只验证租约交接及同一在途准备操作，未重跑全量/安装探测/整组业务。修复源码0f2db1f9a与实际manager镜像bc488d16…/config86230f…已由installation的R32记录固定，其他模块保持。

| 检查 | 实际结果 |
| --- | --- |
| 故障提交 | 对精确旧manager CID仅一次SIGKILL，CLI已ACK，无取消/审批/上线操作 |
| 控制器交接 | 同manager Pod UID2919607c…，restart0→1、新CID，epoch30→31；25.77秒恢复 |
| 原在途操作 | fe9a00424af44176811354d01be141f0/同dep b58853b2…/gen1/owner1，原deadline 2026-10-23T07:22:07不变 |
| 原安装进程 | 同Pod UID6959dd58…、同CID873910bd…，重启后仍running，未重建安装Pod |
| 自然完成 | 精确原CID的BEGIN 07:13:15.897→END 07:17:15.903，240.006186秒；没有owner cancel |
| 操作结果 | prepare completed/cleanupcomplete，inputs/resolve结果SHA原样保留，install/upload进度齐，未出现失败fact |
| 清理与容量 | 同UID kubelet终态后8资源自然API缺席，预约released；原四应用CID/restart与M2 UID保持 |
| 后续正常发布 | 同发布probe87225ca3…也completed/cleanupcomplete，创建1版本；不把它当作正式生产上线或probe物理清理证明 |

实际kill至恢复窗口匹配到6个固定controller_lease_held日志标记，确认经历旧租约等待；计数不是唯一请求数，也不替代UID/事实证明。派生交叉证明逐项断言同op/原deadline/原安装UID与CID/原阶段结果/终态与清理，完整SHA见JSON；原c0fe失败与unknown观察记录保留，未重放或复活。

私有比较器首轮在本机Python3.10解析9位Docker时间时拒绝，尚未写结果；r2仅截取到微秒再核同一组原始证据，未改平台或再次远端运行。此次通过只关闭T070的租约交接/在途重启子项，其他故障矩阵、独立卸载及正式交付门仍保留原状态。

独立最终窄审PASS：`/private/tmp/f059-prepare-sigkill-r4-independent-evidence.md`，SHA `a89f59ae73a2b54a91b550b3497bcf467c1d46609e2a65dec912571c304202a2`。原始11份与第12份派生comparison清单逐摘要一致；仅本租约交接和准备续办，不替代其余故障矩阵或生产上线。
