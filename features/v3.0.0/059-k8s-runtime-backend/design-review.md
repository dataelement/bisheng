# F059 design 评审记录

**当前结论：LGTM，R-D1、R-D2、R-D3 已在设计文本中闭环，用户已确认设计并授权进入 tasks。** 按用户“修订并复审”完成三项修订，再按 sdd-review 的 24 项 design-checklist 及场景矩阵复核。由同一代理完成，没有独立代理评审。本结论仅针对静态设计，不代表 K8s 功能、接口或故障验收已通过。

- 日期：2026-10-21。
- 代码基线：`755d4456e50c015a3fa88da0c0c35ab53bbd1650`；分支 `codex/059-k8s-runtime`。
- 用户确认的设计正文 SHA-256：`b846e993909cda416502d33fdbf6b2174357068673840c2fc0f7d75fe9dc76a4`；确认后 design 的状态及实施现状随任务更新，上述摘要是审批快照，不代表后续实施版全文。
- [spec.md](./spec.md) 全文保持已确认版本，SHA-256：`11991622ee73976a354bd533cb6691407780c99ce70fdf034212f6ea6928c13e`；55 条有效 AC 不变，AC-38 保留退役。
- 严格格式结果：[design-review.txt](./design-review.txt) 为 `LGTM`。

## 三项修订与复审闭环

| ID / 原严重度 | 上轮问题 | 本轮修订与定位 | 复核结果 |
| --- | --- | --- | --- |
| R-D1 / high | 要求所有容器有终止记录/ID，init 失败和未启动容器可能永久占住 finalizer、预占和生产名称 | [4.5](./design.md#L183) 区分 never_scheduled、kubelet_terminal、unknown；终态来源由无副作用 status 规则约束；全部执行 Pod 保留 finalizer，收尾计划到清理确认后才关闭；D5、4.9、4.10、5、7.2 同步 | 文本闭环：初始化失败可按可信停止证据释放，不凭缺失 ID 放行，不放松 AC-49；覆盖 AC-08、AC-43、AC-52。实际集群生命周期与节点身份仍待验收 |
| R-D2 / high | 数据接口只找在线 sidecar，停用后保留库无法查改导出 | [4.8](./design.md#L240) 在线同 Pod、停用独占 purpose=data；新增限时内部 data 操作，空生产位置/互斥/UID确认后签 owner 动作票据；完成后停 helper、保留 PVC及停用态；定义结果未知的只读查询和并发拒绝 | 文本闭环：F054 AC-56、F086 AC-47、F059 AC-36、AC-37 和 INV-33 一致；不额外运行业务实例、不绕过单写或自然人 owner 边界 |
| R-D3 / medium | 材料签名输入和分块 HTTP/失败重试不完整 | [6.2.1](./design.md#L411) 固定 material-v1 的头、11 行输入、类型、body/ticket 摘要、方法/路径/偏移、会话 JSON、分块、finalize、续期及错误；增加 414-byte 编码向量 | 文本闭环：client/backend 不再猜测 wire format；AC-15、AC-47 的范围与重放合同具备可实现输入。只校验了编码向量，真实签名互验/授权与传输仍待开发 |

停止依据采用 [K8s v1.28.15 TerminatePod](https://github.com/kubernetes/kubernetes/blob/v1.28.15/pkg/kubelet/status/status_manager.go#L380-L486)、[终态延迟规则](https://github.com/kubernetes/kubernetes/blob/v1.28.15/pkg/kubelet/status/status_manager.go#L965-L1029)、[删除中 Pod 的绑定校验](https://github.com/kubernetes/kubernetes/blob/v1.28.15/pkg/registry/core/pod/storage/storage.go#L221-L232) 及 [AdmissionReview 的身份/子资源合同](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/#request)。status 来源限制是本次设计，不是已经安装或已探测的配置。

现有数据边界重新核对 [AppDataService](../../../src/backend/bisheng/app_runtime/domain/services/app_data_service.py#L142)、[节点应用 scope](../../../src/backend/bisheng/app_runtime/domain/services/runtime_operation_service.py#L374)、[单应用数据 API](../../../src/runtime-manager/runtime_manager/api/platform_data.py#L16) 和 [Docker DataExecutor](../../../src/runtime-manager/runtime_manager/data_executor.py#L68)。材料分块规则对照 [RuntimeArtifactService](../../../src/backend/bisheng/app_runtime/domain/services/runtime_artifact_service.py#L146)，保留其持久 offset/摘要/SQL 确认原理，新增 workload 认证不冒充已实现。

## 场景交叉复核

以下都是设计推演结果，尚未执行真实部署或故障注入。

| 场景 | 修订设计的结果 | 追溯 |
| --- | --- | --- |
| 未调度 Pod 超时/取消 | 同 UID 删除时间＋空 nodeName 的新鲜对象，绑定禁止条件成立后确认 never_scheduled；没有这些证据不释放 | 4.5；AC-08、AC-43、AC-52 |
| 首个 init ImagePullBackOff | DELETE 后由绑定 kubelet 提交受保护终态，未启动 app/helper 不强求 ID；再移除 finalizer 和释放预占 | 4.5、4.9；AC-09、AC-52 |
| material-fetch 拒绝或 environment 初始化失败 | 同一停止分类；不得用 PodInitializing 直接推定可清理，也不因 Waiting 状态永久阻塞正常终止 | 4.5、4.6；AC-47、AC-52 |
| 正常停止已运行实例 | UID、删除事实、status 来源/终态和新鲜 API 结果共同确认；之后才允许替换或维护 | 4.5；AC-49、AC-50 |
| NodeLost、404、同名异 UID | 停止未知，保留归属/预占及生产卷，不补第二写入者 | 4.5；AC-49、AC-52 |
| 节点控制器合成 Failed | status 规则拒绝非绑定 kubelet 的终态转换，不计停止证明 | 4.5、4.9；AC-13、AC-49 |
| status 验证器暂不可用 | API 状态更新/确认延迟，manager 不误释放；本地停止不依赖 backend 回调，恢复后对账 | 4.5、4.9；AC-07、AC-52 |
| 临时 Pod 完成期间 manager 被杀 | finalizer 保留对象，恢复后读取同 UID 终止证据；操作终态不撤销同 UID 收尾计划 | 4.5；AC-48、AC-52 |
| 在线 owner 查改导出 | 原业务授权后在现有 Pod 内执行，与维护互斥，不创建第二挂卷实例 | 4.8；AC-36、AC-37 |
| 停用后 owner 查改导出 | purpose=data 独占空生产位置，冷启动纳入 60 秒，结束后停止/清理 helper，仍停用且保留 PVC | 4.8；AC-35、AC-36、AC-43 |
| data 操作与迁移/部署竞争 | SQL 互斥＋UID 账本＋固定名称拒绝并发，不以 helper 忙为由额外挂卷 | 4.5、4.8；AC-48、AC-50 |
| 数据编辑结果未知/票据到期 | 不自动重做编辑；重新授权的只读请求指向旧 request_id/journal，不能复活写票据 | 4.8；AC-36、AC-48 |
| 准备完成后合法部署重新初始化 | deployment-init 依据当前部署和冻结材料授权，独立于原 prepare 终态 | 4.7；AC-15、AC-47 |
| 旧 ticket 过期或归属撤销 | 旧 ticket 直接拒绝；新 exchange 必须新 nonce/签名并重验当前归属，撤销后不续发 | 4.7、6.2.1；AC-47 |
| 改方法/路径/偏移/请求体/ticket、重放 nonce | 固定字节验签及范围/nonce校验拒绝；不从 body 接收新的租户/应用范围 | 6.2.1；AC-15、AC-47 |
| 分块/finalize 响应丢失 | 新签名查持久事实，同字节不重复追加，冲突拒绝，完整材料确认前不执行 | 6.2.1；AC-46、AC-47、AC-51 |

## 24 项检查

| # | 检查 | 本轮依据 | 结论 |
| --- | --- | --- | --- |
| 1 | 目标简洁 | 1：K8s 执行后端，复用平台流程和存储 | 通过（静态） |
| 2 | 非目标明确 | 1、8：不含商业、多副本、形态迁移、新 UI、任意 Dockerfile/SQL | 通过（静态） |
| 3 | 特有约束 | 2：1.28/189、存储、三种交付、单写、执行层失联边界 | 通过（静态） |
| 4 | Constitution Check | 2.1、4.9、4.10：C1–C8 落点保持；status 验证器不持集群身份、不编排资源、不写停止事实；无设计层 BLOCKER | 通过（静态） |
| 5 | 关键决策 | D1–D8：能力抽象、直接 Pod、材料、身份、单写、隔离、构建及安装权限 | 通过（静态） |
| 6 | 备选/选定/原因 | D1–D8 每项保留被否方案、所选方案及具体原因 | 通过（静态） |
| 7 | 重新考虑条件 | D1–D8 均含触发条件，未把默认选择写成不可改变铁律 | 通过（静态） |
| 8 | 具体依据 | Docker 真实调用链、K8s 固定版本源码、既有盘点及存储/OCI 官方资料 | 通过（静态） |
| 9 | 数据流 | 4.2、4.3：发布、预检、审批、维护、上线、访问与停用数据路径 | 通过（静态） |
| 10 | 关键数据结构 | 6.2、6.2.1：资源证据、内部 data 操作、材料头/类型/JSON/编码及会话状态 | 通过（静态） |
| 11 | 模块职责 | 4.1：现有 Docker 与拟新增 K8s 接口明确区分；业务授权仍由 backend Owner 完成 | 通过（静态） |
| 12 | 现状准确 | 4.1、7.2：无 K8s executor/Chart/新接口实测声明，未来脚本明确标识不存在 | 通过（静态） |
| 13 | 反直觉事实 | 4.5、5：从未启动不一定有容器 ID；普通 phase 不是来源证明；RWOP 与停用 helper 的差异 | 通过（静态） |
| 14 | 后果 | 5 逐条说明双写、永久占用、停用数据缺失、身份/协议歧义等后果 | 通过（静态） |
| 15 | 处理位置 | 5：k8s_lifecycle、准入、材料 client/auth、数据执行器等拟实施位置 | 通过（静态） |
| 16 | Outgoing | 6.1、6.2、6.2.1：Python 能力、既有 HTTP、新材料协议与错误/重试；数据动作仍通过原业务接口 | 通过（静态） |
| 17 | Incoming | 6.4：业务合同、K8s/准入、卷、工具、仓库、镜像/SDK与CI前置 | 通过（静态） |
| 18 | 依赖风险 | 4.5、4.9、4.10、6.4：终态来源规则的认证/可用性前置，F086 修复继承与离线物料边界 | 通过（静态） |
| 19 | 分层测试 | 7.1：55 条有效 AC 全覆盖；补三类停止证据、数据互斥、协议篡改与分块重试 | 通过（静态） |
| 20 | 手动验证 | 7.2：189 专用资源、实际允许/拒绝、初始化失败与停用数据场景；新工具仍待实施 | 通过（静态） |
| 21 | 后续与短板 | 8：不自动 fencing 接管、Pod 缓存成本、未验证平台/架构/存储限制保持 | 通过（静态） |
| 22 | 修订历史 | 设计末尾登记初稿与本轮三项修订，不宣称实现完成 | 通过（静态） |
| 23 | 规格一致 | R-D1、R-D2、R-D3 的文本冲突/合同缺口闭环；55 条 AC 正文及 INV 保持不变 | 通过（静态） |
| 24 | tasks 偏差 | 当前仅阶段登记，设计复审通过但未获人审确认；无任务拆解/代码偏差 | 通过（静态） |

## 追加审查（用户选择继续评审）

**结论：维持 LGTM，本轮没有新增 high、medium 或 low ISSUE。** 2026-10-21，用户未确认设计，选择“继续评审设计”；本轮由同一代理再次检查修订后的执行链与现有代码，未修改 design 正文、spec 或功能实现。设计对象仍为上列 SHA-256，不能据此越过设计人审门。

| 核查重点 | 核查依据与结果 |
| --- | --- |
| 停止分类是否放松单写 | 4.5 的 never_scheduled 要求同 UID、删除时间与空 nodeName 的新鲜对象；已绑定 init 失败须等待受保护的 kubelet 终态；404、NodeLost、租约到期仍为 unknown。没有把缺失 container ID 本身当作释放依据 |
| status 验证是否引入新的回调死锁 | 4.5、4.9 的 status 规则只检查 AdmissionReview，不读取 backend、不直接保存停止事实；资源模板规则另读已提交计划。核对 K8s 官方终态延迟及 AdmissionReview 身份字段，没有把普通 phase 或外部回调自报身份当作证明 |
| 收尾是否依赖已经终结的操作 | 所有执行 Pod 保留 finalizer，4.5 的只读收尾计划持续到同 UID 清理确认；停止事实与资源释放、finalizer 移除可按持久事实续办。控制器租约不被用作旧写入者死亡证明；晚到请求仍须按当前资源意图、代次及 UID 检查 |
| 数据会话是否造成额外业务实例或自动重做编辑 | 4.8 在线复用同 Pod，停用会话独占固定生产位置；保留原应用态/serving 代次和 PVC。创建互斥事务提交后才唤醒 manager；超时不等于清理完成，未知结果通过新只读请求查询旧 journal，不重跑原编辑 |
| 材料协议是否混淆重放与幂等 | 6.2.1 签名涵盖 method/path/query、原始 body 和 ticket 摘要；nonce 拒绝重放，传输 ID/持久 offset 负责幂等。重复相同分块与冲突分块结果不同，过期 ticket 不能单独续期，finalize 仍要求内容与平台记录确认 |
| 新链路是否破坏既有代码边界 | 核对现有 RuntimeRecord/RuntimeTransfer、操作 claim/fact、owner 数据 Service、DataExecutor、archive_directory 与出口策略；新增接口和内部 data 操作仍明确为待实现，原服务 HMAC、业务权限、Docker 合同和平台存储 Owner 保持原归属 |

额外复核：已确认规格全文摘要不变，55 条有效 AC 与 7.1 覆盖集合一致，D1 至 D8 的决策四要素完整，material-v1 的 414-byte 编码向量与已登记摘要一致，Git 空白检查通过。编码样例计算不是接口验签实测。

实施和部署阶段仍需执行设计 7.1、7.2 已列的 manager 失联/并发控制器、init 拉取与材料失败、status 规则允许/拒绝、停用数据会话及数据动作超时、分块重试/撤销、Docker 回归等场景。这些是现有验收门，当前未执行；本轮没有新开“已验证”记录或声称 189 上线成功。

参考：[K8s v1.28.15 的终态延迟](https://github.com/kubernetes/kubernetes/blob/v1.28.15/pkg/kubelet/status/status_manager.go#L965-L1029)、[AdmissionReview 请求合同](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/#request)、[现有操作归属校验](../../../src/backend/bisheng/app_runtime/domain/repositories/runtime_delivery_repository.py#L290)、[现有材料安全归档](../../../src/runtime-manager/runtime_manager/bundle_inputs.py#L194)。

## 审查历史

- 初稿设计全文 SHA-256 为 `4eba2bedb1a9df443e78e4b7888c5e4c6f2042c7983347343f3d830df5809bad`，曾自审 LGTM；用户要求先评审后，发现 R-D1、R-D2、R-D3，原结论撤回。
- 上轮仅更新未通过状态后的全文 SHA-256 为 `2a3c47761c21cfe758aca7407bc5b1583c50057d6dedaae42765896855b4a7d6`；原问题定位为旧版第 187–188 行、228–230 行、219/358–359 行。它们是上述修订的输入，旧行号不能用于当前文本。
- 本轮用户明确要求“修订并复审”；三项修订及复核见本文当前结论。没有沿用旧自审 LGTM，也没有将用户的规格确认当作设计确认。

初稿 DR1 至 DR8 的记录保留如下；其中 DR1、DR2 的遗漏已经由本轮 R-D1、R-D2 继续修订，表内原“闭环”描述不是当前评审的独立证明。

| 发现 | 问题 | 初稿记录（历史，不是当前结论） |
| --- | --- | --- |
| DR1 | 单副本控制器、RWO 或 SQL 租约不能独自证明旧写入者停止 | D2、D5、4.5：直接管理固定生产位置；生产服务/维护互斥；UID 账本、finalizer 和具体容器终止证据；未知时保留阻塞，禁止 404/phase/租约替代证明 |
| DR2 | 在线数据 helper 新开 Pod 会与 RWOP 冲突，恢复备份和结果记录也不能被应用修改 | 4.4、4.8：同 Pod helper；business/platform 子目录隔离；backend 业务层签 5 秒受理票据、helper 只持公钥，结果未知不重做写操作 |
| DR3 | 短启动 deadline 无法在 ready 后延长为预览期限；正式 Pod 也不能继承准备期限 | 4.6、4.9、5：按照 1.28 源码校验区分任务/预览/正式期限，初始化自有阶段超时，管理恢复后有界清理 |
| DR4 | manager 最小权限表缺 Service 就绪检查所需的 Endpoints/EndpointSlice 读权限 | 4.10、6.4：补 get/list/watch；不扩展 Node/PV/SC 或其它 namespace 权限 |
| DR5 | 平台核心在集群外时无法默认访问 ClusterIP；CNI源地址也可能因转发变化 | 4.2、6.3：仅安装者发布共享 entry/control 私网端点、限制来源及 HMAC，实测转发/ACL；不给单应用暴露节点端口 |
| DR6 | 准入回读 backend 与持锁创建资源可能循环等待；候选取材料也不能要求已经正式 serving | 4.5、4.7：提交资源意图后才调用 K8s；候选按有效已批准 deploy/recover 归属，正式续期按 serving 归属，均须精确冻结及 UID 绑定 |
| DR7 | 泛用 rootless builder、直接 OCI tar 追加会引入内核前置和越界层/凭据风险 | D7、4.6：固定 profile 准备＋可信受限层组装，拒绝任意 Dockerfile、whiteout/设备/路径逃逸；受信 helper 不从应用目录导入模块 |
| DR8 | kubelet 退避、helper资源及删除后日志会被过度承诺 | 4.9、7.3：持久化恢复起点及安全替换策略，helper单列预占；只读实际可保留的 app/previous 日志和诊断尾部，不承诺已删除完整日志 |

## 文档检查和证据边界

- 已确认 spec 全文摘要不变，55 条有效 AC 与 7.1 的映射集合一致；原 AC-38 不复用，AC ID 全写。
- D1 至 D8 每项包含备选、选定、原因及重新考虑条件；原编号未变，只新增 6.2.1，核对标题、章节引用和文件链接。
- material-v1 编码样例为 11 行、414 bytes；SHA-256 为 `206cf7e08bc12e23245980c45989fe8165233183e18bed03b99a8c17c6050167`。该计算仅证明文档样例编码一致，未进行真实 Ed25519 验签或接口调用。
- 核对 Markdown 表格列、阶段状态与 Git 空白；189 盘点原始记录摘要未变：cluster.txt 为 `c619c88fb0168bde7ea5b5803dcd3adae084aa032ca2efeac447a2b5b426cb70`，storage.txt 为 `df49b8847ef1b9f406803eb5b2aa8f05c444bb3d8ef85c169f9116c312f0e0d2`。
- 未修改功能代码、未访问或更改 189 集群，未执行部署、离线安装、数据恢复、授权或故障 E2E。新增组件、API、模型、status 保护和离线 data 会话均仍是待实施设计。

依据根 AGENTS.md 第 6 节、SDD-Guide 第 3 节和 sdd-review，设计复审通过后仍须用户单独确认，才能进入 tasks 拆解/评审及编码。tasks 当前只登记阶段，不视为已拆解；正式平台验收仍须继承 discovery 中列出的 F086 必要修复。

## 用户设计确认

2026-10-21，用户明确回复“确认设计，进入任务拆解，继续推进 SDD 流程。”。仅更新设计状态元信息；D1–D8、接口、正文和55条规格 AC 不变。原等待确认的审查历史保留为当时状态；现进入任务评审与实施。

实施状态另见task-reviews.md：T020/T021已完成编码/真实Ed25519互验；上述表记录批准设计时的审查闭环，不代表完整材料服务或K8s已交付。
