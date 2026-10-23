# F059 189 安装验收阶段证据

状态：**T068通过**。固定源码、镜像、资源UID与校验和见 [installation.json](./installation.json)。

候选54b3ea2c1、Helm revision10在189实际完成第五轮15项必需检查及registry-push，正常清理exit0；真实平台公开安装诊断通过。覆盖受限RBAC/exec、PSA、状态来源、同UID删除与binding拒绝、网络隔离、精确镜像启动、材料TLS/HMAC和SQLite锁/fsync。此前失败与其他源码轮次独立保留。

报告过期、CNI身份变化、必需检查失败三组均通过真实发布入口：先确认节点blocked及公开ready=false，提交各自唯一static应用，持久化失败16121/precheck_build、无审批/正式版本/运行操作。每组原样恢复descriptor字符串并验证节点ready，manager Pod UID/containerID/启动时间/restartCount完全不变；没有生成虚假成功报告或延长TTL。

旧失败installer仅按自然到期、同UID及真实停止/绑定拒绝证据清理；固定旧dryRun按四次404与CAS撤销。最终执行namespace无Pod/PVC，canary计划为空。专用registry启用delete经过用户明确授权，原容器及数据保留。

业务发布、应用数据/SDK与故障升级仍由T069/T070单独验收。本节不是整体交付通过；DM8仅静态，单节点不能证明跨节点。

## 业务验收前临时卷池增补

按冻结计划新增scratch-09..40共32个4GiB独占ext4 local PV，实际预分配128GiB；精确NS/nodeUID、原19PV/marker权限及loop前后核对不变。新卷归专用operator管理，Retain，无Helm归属，不重绑旧卷；inventory摘要与新UID见JSON。原preflight卷因既有fsGroup为0:10001/0664，按精确旧UID冻结原状，不改旧权限。该结果不证明宿主重启或跨节点恢复。

后续控制候选0e/Helm11：固定LAN manager manifest b17045eb…，保留当前实际能力报告再升级；四个历史failed draft逐一只读预检后owner DELETE，后续GET16101，无force清理。收据SHA df530fbb693835dfa83604c4adc54b588b2e0e03858bffb34806b87567b93bf7。新业务尚在precheck_build，资源未创建，空闲租约续租409登记T198/T199；该状态不撤销历史T068安装探测证据，但不计T069业务完成。

## 2026-10-23 开发收尾候选

Helm14以d86e66a2d固定manager镜像升级manager/egress/admission，全部Ready；descriptor UID/数据相同，原能力报告/helper/profile2保留，backend四文件来自709821ecb。真实平台进度见[platform.md](./platform.md)：首Pod已创建启动并正常同UID清理，完整发布仍pending。

## 当前143候选：新helper重验

源码143606851、Helm16使用新manager/helper固定digest，profile2运行/预备镜像和assembler/app-proxy保持原值。原生amd64构建及lock:null实际resolve烟测通过。首轮新helper探测15/16通过，只有storage-sqlite因原preflight01–03全部Retain/Released而超时；本轮canary已按正常停止确认清理，失败报告完整保留。

新增preflight04–07四个1Gi独占有界ext4 local PV，物理预分配4Gi，inventory SHA 35f57e5fb4e4a49df8b12862c9e66da90bcab0e88e797a988e7ef9aa473dddf2。固定NS/node UID、原19卷和全部既有loop在本次供应中不变。首个只读计划因旧快照scratch06 marker模式不符拒绝；只读确认现为0:10001/0664且内容/UID不变，将该实测状态单独冻结到新快照，旧快照和旧卷不修改。

同源码/镜像第二轮完整探测进行中；未把旧报告当作新helper通过。r6完整6场景已在新目录准备，无API bootstrap；新报告ready前不启动业务。

第二轮同143源码/镜像完整探测exit0，16/16真实通过；SQLite证据UID 12e4f5eb-e512-4549-8395-eb9620c281d8，descriptor digest d7e831157cd56ff2a941118b9deafb2c2f62b572c633428efb4412839a337afd。canary Pod/PVC均正常清理，仅旧r4隔离PVC仍保留。报告发布后平台Node初次读仍blocked，业务需等正常配置投射/心跳ready再启动，未跳过准入。

新报告投射及正常心跳后node ready=true/controller_epoch10，未重启或改状态；独立r6 platform套件已启动。私有启动守卫首轮缺now关键字在业务/API/journal前退出，修正v2后固定helper/报告检查通过；该记录不算产品失败或重放。


2026-10-23 manager-only候选7816/Helm17：原生构建及禁网导入通过；descriptor UID/data、helper143、profile2及其16/16报告完全未变。新镜像评估ready、平台自然接管epoch11且ready；没有把保留的143探测报告改标成新运行。真实业务在独立r7继续。

2026-10-23 manager-only a1de/Helm18：固定digest06bb857f…，descriptor/报告/helper/profile不变，新镜像assess ready及平台epoch13/ready成立。backend取消闸两个文件CAS更新、专用服务重启后实际私网env200；错误loopback检查单独保留并追加纠正证据。未冒认新16项完整探测或真实数据取消已通过。

前次控制候选a06/Helm19、digest4666d753…；143来源的16项报告、helper及profile2逐字节保留，r9启动前新镜像assess_capabilities仍ready。此次仅准入收尾修复与真实旧失败正常清理验证，不宣称又完整执行16项；当前候选指针详见JSON，旧Helm10快照归历史记录。

当前候选249/Helm20、digest42c6c3c5…，仅可信维护模板材料PodUID接线修复；helper143/profile2及16项安装报告不变，node ready/epoch15。首个正式Python上线与访问/数据边界已通过，见platform证据；没有重复完整16项探测或跨节点/ARM冒认。

## 当前6f候选与离线数据CPU修正

固定source6f254f337，LAN digest59692b82…、Helm22三控制服务正常滚动，node ready/epoch17。descriptor UID/data、有效143能力报告、helper8a/profile2/app-proxy不变；只更新backend两源文件并重启专用backend/worker，原文件SHA已先核对且备份保留，OpenFGA不变。未把此次滚动冒认为新的16项完整探测。

## 当前控制镜像995与Helm23

995c80f2a原生amd64构建/import通过，内网固定digest7cef8910…，Helm23三控制服务ready、epoch18。descriptor UID/全部data、143 helper、profile2、现有16项有效报告和app-proxy保持；仅bundle PATH补系统sbin，backend仍保持6f参数源码。原生烟测不是新完整能力报告/业务通过。

## 0d5中间候选真实16项通过（Helm24）

原生amd64 manager/helper/assembler及公共CA组装器变体完成构建和隔离非root烟测；helper/assembler实际SGID目录两允许、危险位10拒绝，OCI源码字节和9种PATH组合通过。仅推送189专用测试仓库20261023-26；没有ARM、官方九镜像inventory或正式CI发行冒认。

manager28449f9c…/helper5906c518…/assemblerCA9836c134…更新后，仅descriptor两个镜像字段变化、UID保持；旧报告descriptor摘要不匹配，实际manager三路径false/backend blocked。真实16项探测随后全部通过，报告SHA `6720eaf4938302d5ad5c7e01b8b1972627dbf5f7c4b1e92d5db83ec838e92ec6`；投射后自然ready/epoch19。三个既有应用仍Running，r4保留不动。

最终入口CMD修复来源d7f7c2e10另行冻结；上述中间0d5安装通过不等于d7f已部署，需新镜像摘要及真实报告后更新。

## 更正后实际部署：Helm26 / 0d5 / epoch21

CMD问题已用固定CLI官方实现与三个base的实际无--cmd对照证伪，T252/T253撤回。d7中间候选16项探测自然通过且全部preflight Pod已正常清理（报告SHA35c968ac…），没有人为中止或修改其结果。当前分支全部src/scripts/deploy/workflow构建输入与0d5逐字节相同，保留SGID/PATH真实修复。

正常helm upgrade恢复0d5精确manager28449f9c…/helper5906c518…/assemblerCA9836c134…；descriptor UID不变、摘要f306a49e…，使用原实际16项通过且与该摘要完全匹配的报告6720eaf4…（恢复时年龄1549秒，小于24小时），未宣称重跑探测或新构建。Helm26/自然ready/epoch21与三交付路径true已fresh验证。r4保留、app-proxy/profile/data配置不变。更正提交20175cad9，最终镜像源码基线0d5。

## T254/T255新增上游探测：189真实复验

dedc安装器通过独立r2 wrapper真实执行，exit0；完整16/16检查通过并正常清理，报告SHA `304b970cdba945fb4c60dffeb10eab3dbdd7ceffeb0b984dbfb39c52581070ce`。runtime镜像仍0d5，helper/profile/descriptor摘要不变，仅能力报告刷新；双guard摘要12588470…/b92a889b…证实范围。

独立复核精确5个可能匹配三个业务Service的control canary：每个均1ADDED/10MODIFIED/1DELETED，同UID闭合，所有事件带NotReady gate、未出现gate=True或Ready=True；每个仅一次进入EndpointSlice，ready和serving明确false。三个正式Pod及Service UID/selector/publishNotReadyAddresses=false保持。registry-push精确对应egress canary UID7f51f0ff-cff8-4e99-9bb6-2cf18e07df32。独立JSON SHA `140eafa532248a53fe1dfef42f198a0bae3faaa47b49de12255d0ab53e508d62`；完整PSV SHA21d17d6c…/e59d0f0d…。

第六个preflight-untrusted角色不匹配上述watch选择器，未连续观察其Ready/gate历史，不推定通过。未见ERROR或stderr错误；不以resourceVersion数字跳跃判断丢失，也不声称绝对无传输缺口/数据包级无影响。root核无control残留、Service不变和精确watch进程后主动SIGINT，两个SSH watch实际exit1属操作者停止记录，不记成130或测试故障。API probe/TCP、外部crane TLS权限、真实source-image业务各自独立。


## R29：保护报告修复实际部署（新业务验收待完成）

T258–T263的生产源码 `f8863f3763285435a5df01fc150400838bdb3f0a` 已完成189原生amd64构建及隔离导入烟测，仅推送专用内网仓库；manager固定digest `0b4bd3e66c1d7c49fe00046c83277dab8b6dbd0628f201abf3192d70dd67ddad`。专用backend/worker仅两个保护源文件按旧哈希备份、原CID重启；新字节哈希复核通过。Helm29升级后manager新UID `fae606c4-3e51-4efa-ba00-a7ce9163de3f`，原UID实际缺席；自然接管epoch24、ready、sticky保护合同v1/current及两guard true。host描述符与Pod投射的完整/保护摘要一致，保护基线 `9006c20349b46e6a60af9d7e2ccdc45f4e4efae5606f58cde88b69bd0b9ad3ff`。

独立fresh核对：旧三个bundle的false/false保持，source/image的true/true保持；四个Running及一个held终态的Pod/CID/PVC/PV身份未变，旧stop仍timed_out/cleanup pending，r4 unknown-create原PVC保持。没有回填历史保护、移除finalizer或释放旧预占。helper/assembler/profile2、代理/准入及描述符数据/UID未变；此次不是重跑16项安装探测、ARM或公开CI发行。新单Python应用的发布/停用/离线数据/恢复仍需单独实测，不能以部署ready代替。结构化证据见JSON的 `protection_report_r29_deployment`。


## R32 租约交接修复部署（2026-10-23）

固定manager源码 `0f2db1f9a29213ca94d4596e64b00ad8fcbac528`，唯一生产差异是operations.py开工前4行控制器准入；Kubernetes executor、Dockerfile/锁/其他发行输入未变。189原生amd64构建、实际UID10001/禁网/只读导入及精确源码摘要烟测通过。专用仓库单次私有推送、TLS校验manifest/config：digest `bc488d16d3b75ccd30e729d7ef79b0c4591abaa40c0037057697f405d9e4900b`，config `86230f7a09ee50970c1667710b0b03c8768b92f56697c833e1ad3fcf6bcf4396`。

Helm32仅更新manager；新Pod UID2919607c…/controller30 ready，现有5个应用Pod、6个PVC/PV、descriptor/其他3代理身份完整保持，业务SQL及node配置前后投影相同。复用原有效探测报告，只做当前descriptor/双保护/readiness核对，没有重跑安装探测或全量业务。后端仍是单文件38a/c06f…与此前独立修复组合，不声称整个平台统一来自0f2；其他镜像与profile保留其原始provenance。

七份raw摘要见JSON r32_manager_only_deployment。此节只证明修复镜像部署；在途重启和原hook自然完成另见fault-upgrade。ARM、追加109和公开CI/tag继续暂缓。
