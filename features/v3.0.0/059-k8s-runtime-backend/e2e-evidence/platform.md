# F059 K8s 平台业务验收（进行中）

结论：**尚未通过完整业务验收**。当前优先189 K8s；arm新增验证暂停。详见[结构化证据](./platform.json)。

| 现场步骤 | 真实结果 | 限制 |
| --- | --- | --- |
| 新Pod模板与创建事务 | k189r5首个prepare Pod已创建、调度并启动storage-guard/transfer | 不代表应用已上线 |
| 准备阶段 | precheck_build/16227，原ValueError遮蔽日志缺口 | 固定容器名单已补；原准备失败不能倒推为成功 |
| 停止与清理 | 同UID kubelet_terminal持久证明；该Pod、Secret、scratch PVC均cleanupcomplete且fresh API缺失 | 只证明该操作已注册资源，不声称全集群未知writer盘点 |
| 材料入口 | 专用TLS代理缺根路径，origin404/backend401；精确补路由后新连接401，平台env200 | 401只证明入口及拒绝，signed transfer待复验 |
| 旧k189r4 | 无持久create receipt，仍保留其操作和PVC | 不凭403日志/404或人工文件追认not_created |

## 首个诊断候选（历史）

- manager/egress/admission：`d86e66a2d`，固定digest见JSON；backend四文件来自`709821ecb`，其余平台源码保持先前基线。
- Helm升级保持descriptor数据/UID、能力报告、CA、helper及profile revision 2；app-proxy未改。
- `709821ecb`完整amd64九镜像及bundle/SQLite烟测通过；`d86e66a2d`只更改K8s日志目标白名单，原生manager构建/导入烟测及245相关回归通过，不重标helper来源。

待完成：同app明确新attempt、Python完整发布、审批预览、HTTP/WebSocket/SDK/OBO/附件/SQLite，再扩展Node/static/image/source-image及故障升级；不将本地/原生Docker烟测算作K8s业务通过。

## r5 同应用第二次尝试：材料成功，停止确认待修复

`87a95018bda240b695a392fb156f8cd4` 已明确接受；prepare `01a6500a2a7b46578e677abb07320e1c` 的同UID Pod `81be1259-85ac-44df-8a6c-9a43ab4fc332` 成功下载材料并终态Succeeded，准备进度事实200。随后停止确认409：CREATE时节点为空，实际调度到binfeng-k8s-node189后未回写账本。保留删除中的Pod/finalizer/PVC，等待T219/T220正常对账；没有手动清理或重写数据库状态。完整发布未通过，材料入口的有效传输已得到真实验证。

### 延迟绑定修复的现场恢复

706b13861固定源码的amd64镜像原生构建/导入烟测通过，内网digest `ae93f837a58529eee86f85bbd79f46801a9e068ab7c84babe35292209c97ad41`，Helm15三个控制服务升级完成，descriptor UID/data及helper/profile/app-proxy不变。正常对账将原Pod节点补齐，保存同UID的kubelet_terminal停止证明，三条资源账本cleanupcomplete且逐项APIabsent；证据SHA `dc8150cce9cf728a02e90d8b09673a1b025a57fb450389e088a14900fbecb733`。没有直接清理finalizer/PVC或SQL改状态。

同应用第三次正常发布已明确接受，deployment `8070bb448ebe4f0182142ed25bf16038`，version `7e064c50b23348e59666a158404ef229`；旧journal/header保持，续办记录追加，不重放unknown。完整业务验收继续中。

### 第三次失败：可选锁合同和诊断覆盖

prepare `e36537609ef047748674e5172885dddd` 的inputs成功，resolve失败；两个Pod都按真实UID完成kubelet_terminal及正常清理，5条资源账本cleanupcomplete/APIabsent，proof SHA `aa2d35fff5a9c63a46542dff75c1497d564ea30db6846687a4fae66598488cee`。首个failed fact3明确保留preparing/transfer TypeError；清理重试fact4将投影覆盖为failed/空tail，原fact仍在。

189无网络、无凭据原生helper复现：相同已知源码包省略lock成功，仅改lock:null即在k8s_helper.resolve_download写os.environ处TypeError。T221–T224规范化可选锁并保留首次诊断，已本地回归通过；未回填历史。后续采用独立k189r6完整场景batch，r4/r5原journal和追加链保持，完整业务仍未通过。

## k189r6独立完整批次

新helper完整16项安装探测通过，backend节点正常恢复ready后启动原platform六场景。原runner SHA ba5b766e3afbbfa4c4b6f170e3c32c288fccbad58dfc91c498484bb66cf4ac3c，固定源码143606851，profile2；新journal隔离，旧r4/r5及追加链不变。当前进行中，platform失败保留现场，未执行all的finally cleanup。

r6首个Python应用prepare8fb6b53a…真实完成inputs/resolve/install/upload；4Pod同UID停止，8条资源账本正常cleanupcomplete。执行器在第一次cleanup.pending时立即失败，公开16227/precheck_build；首次failed_stage=preparing正确保留。登记T225–T227按原期限等待，不把DELETE受理当完成、不复活失败操作；未生成审批或正式版本。


## 当前候选与r7独立批次

开发收尾来源7816e0bb87cd1b9ea0c82e8c01283cdf2e821a13；manager原生amd64构建/禁网导入通过，内网digest `3e0bf023a016b3f486bd5fe5cbcae85d89cc8737daaa9166f926291ec7781de5`。Helm17三个控制服务更新，descriptor UID/data、helper143、profile2与安装报告逐字节保持；新镜像assess_capabilities及平台ready通过，controller_epoch11。无新16项探测或ARM/公开发行冒认。

r6原失败记录保留；正常cleanup后8精确资源逐项fresh API absent、4Pod停止证明，proof SHA `110aab26f2846ed75f35a02a95e948e40e8ec5cba21528ead45acec7dfa87d77`。不复活旧operation。r7使用原runner、原身份及六场景新journal；首个Python deployment d623cbd318f04795bb6121a572ff566e（app baa177a4b5fe42cbb8cf4dadc8f09299）已接受。当前尚在准备/业务验收；platform模式失败保留现场，未执行all自动清理。

### r7准备成功、初始化总窗口失败

prepare6be875…最终completed/cleanupcomplete，4阶段、8资源完整结束且prepared_delivery等于delivery；T226真实路径已通过。probe081663…的材料初始化真实成功，但data-layout/schema-init/material-fetch/env串行共用90秒；Pod调度17:47:32、环境安装17:48:51启动、17:49:03被停止，仅12秒。所有镜像已有本机缓存；tail只到pip Lookinginlinks，app仍PodInitializing。4资源normalcleanupcomplete，保留原失败，不冒认审批/上线。登记T228/T229修正既定阶段计时。


## 当前a1de/Helm18与r8

来源a1de5271f5f00cef0cba06d41f09c673a9190525，manager固定digest `06bb857f4caa79499a844d16838831c7429dfc7d499e65649f314d96fd390cad`；原生amd64构建/禁网导入通过。Helm18三个控制服务更新，descriptor UID/data、helper143/profile2和有效16项报告不变，平台自然接管epoch13并ready。backend两个data grant/session源文件先CAS核旧哈希一致，备份/替换/重启专用backend+worker；原loopback检查失败因端口只绑定192.168.106.189，原失败receipt保留；实际私网API HTTP200、文件新哈希再次核对通过，未追加重启或动OpenFGA。

r8按原runner、身份和六场景新journal启动；首个Python app6da0d71cbda643e881e02d707eac7e79，deployment123f35de6d2b4fdf8050a44d75eebc9e，versionab8c8e9a50c84bf899c1aef0a2bf0898。当前真实业务仍进行中，不把修复部署及本地回归算成审批/上线通过。r7公开失败16124/precheck_probe和正常cleanup事实保留。

### r8真实启动通过，终态删除收尾

同UID8c83f28c…创建18:16:57，data-layout/schema/material/environment分别完成18:17:13、18:17:52、18:18:17、18:18:33，4init96秒后appRunning/Ready。probe cd1ad0fe…已ready；随后SQL停止证明kubelet_terminal于18:19:10入库，Pod Failed/app137且finalizers缺省，但grace30和对象仍在。登记T232/T233修复已移除finalizer后的kubelet最终删除误拒；原操作仍active，未人工delete/释放预占或修改证据。正式审批上线未通过。

## 开发闭合与r9新批次

T232/T233原生amd64候选a06b281b2，内网固定digest `4666d75388bde2ae7c1b0b73916442451b4119a7384852cf373633e8489dfe32`，Helm19三个控制服务滚动完成；descriptor UID/data、有效报告、helper143/profile2/app-proxy均不变。r8原probe最终timed_out保留，修复后正常对账cleanupcomplete；4条精确资源fresh API absent，原同UID停止证明不变，proof SHA `a37f1bab1216ab6029b5b7a24cf52f12db04ac375208d95b9a1e5de490855f1b`。无手工delete/finalizer/SQL或操作复活。

T234/T235修正共享E2E75秒HTTP截止，仅精确同步成功preview/resume/stop/delete采用settings总预算且不重试POST。合流d13e9ee91，112新旧合同、完整backend1753/19skip通过；runtime1519/13skip通过的生产字节保持。r9仅测试源码更新，a06生产镜像来源不重标；新六场景原套件、原身份和独立journal启动，旧批次不变。当前开发修复闭合230/235，完整业务/故障/发行/L2仍在门内；ARM和109按用户优先级暂缓。

## r9工具CA修正与r10

r9真实预览已启动，原platform日志保留ConnectError；只读配置确认F059_E2E_CA_FILE缺失，虽公共CA文件已挂载但客户端未加载。相同工具容器仅显式加入公共CA后，TLS校验开启的入口/api/v1/env得到200。原suite.cleanup阶段通过并正常回收r9应用/预览，未手工修改K8s或SQL。r10独立六场景沿用d13工具、a06镜像/helper143/profile2，显式设置CA且在任何业务API前验证TLS，结果见k189r10-entry-tls.json。生产代码未因本操作配置错误修改，未把入口前置200算成应用访问通过。
