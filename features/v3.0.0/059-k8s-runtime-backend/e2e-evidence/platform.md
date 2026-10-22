# F059 K8s 平台业务验收（进行中）

结论：**尚未通过完整业务验收**。当前优先189 K8s；arm新增验证暂停。详见[结构化证据](./platform.json)。

| 现场步骤 | 真实结果 | 限制 |
| --- | --- | --- |
| 新Pod模板与创建事务 | k189r5首个prepare Pod已创建、调度并启动storage-guard/transfer | 不代表应用已上线 |
| 准备阶段 | precheck_build/16227，原ValueError遮蔽日志缺口 | 固定容器名单已补；原准备失败不能倒推为成功 |
| 停止与清理 | 同UID kubelet_terminal持久证明；该Pod、Secret、scratch PVC均cleanupcomplete且fresh API缺失 | 只证明该操作已注册资源，不声称全集群未知writer盘点 |
| 材料入口 | 专用TLS代理缺根路径，origin404/backend401；精确补路由后新连接401，平台env200 | 401只证明入口及拒绝，signed transfer待复验 |
| 旧k189r4 | 无持久create receipt，仍保留其操作和PVC | 不凭403日志/404或人工文件追认not_created |

## 当前运行候选

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
