# Runtime 标准 Helm 配置合同草案

状态：**草案，供主设计与用户审查，不代表已实现或已部署**。

核对日期：2026-11-06。范围：当前 `standard-helm-delivery` 工作树的 Runtime Manager、Backend app_runtime、运行域 Chart 和手工诊断工具。

本文件只提出运行时合同建议，不替代本特性的 spec/design/tasks。未修改实现、镜像或线上环境。

## 1. 已批准的方向与边界

- 取消强制的运行环境能力预检，以及报告满 24 小时后自动阻断业务的逻辑。
- 网络、权限、准入和存储配置由运维负责；标准 Chart 提供默认配置、参数、校验和说明。
- 保留可显式运行的环境诊断工具；不默认创建环境验收 Job/CronJob，不让 Manager 启动时自动运行 15 项集群探测。
- 保留每次应用发布的镜像检查、依赖解析/下载/构建、临时应用启动与健康检查，以及正常的审批/上线流程。
- 保留 Pod UID、控制器 epoch、停止证明、SQLite 单活动写入和 PVC 保留/清理约束。取消环境诊断闸门，不表示允许未知写入者被强删或接管。
- 本轮只改代码和部署文件；不构建镜像、不部署线上。新合同最终需要配套版本镜像，不能用既有 v3.0.0 镜像宣称已经支持。

这里的 `operator-configured` 表示“按受信部署配置运行”，不是“诊断实测通过”。标准交付采用这一模式，不再增加一个默认关闭的强制诊断体系。

## 2. 当前耦合点及必须同时修改的调用链

| 位置 | 当前行为 | 新合同要求 |
| --- | --- | --- |
| `runtime_manager/k8s_capabilities.py::report_validity` | 检查报告来源、descriptor 摘要、24 小时年龄 | 仅供诊断展示；报告年龄不决定执行资格 |
| 同文件 `assess_capabilities` | 15 项报告全部通过才 ready；source-image、RuntimeClass 也依赖报告 | 改为配置能力与诊断结果分开计算 |
| `executors/kubernetes.py::_probe_state/heartbeat_snapshot` | 从报告推导 mandatory/status/binding 保护和路径能力 | 从受信配置推导可配置能力；诊断另行输出 |
| `operations.py::heartbeat` | 将 probe_report.ready 与 API 可达性合并 | 正式 readiness 使用配置/运行状态；不改写诊断结论 |
| Backend `RuntimeOperationService._node_report/_protection_update/heartbeat` | 报告 ready 决定 node.status；报告缺失/失败会降低旧资源保护历史 | 验证新的配置合同；诊断不再改变 node.status 或保护历史 |
| Backend `RuntimeOperationService.create`、Repository `admit` | blocked 拒绝新工作 | 保留真正配置错误、节点不可用、容量不足等拒绝；诊断未测/老化不触发 blocked |
| Backend `RuntimeOperationService.route` | Kubernetes node.status 非 ready 则入口 unhealthy | 取消诊断对 node.status 的影响；不可因未测/老化阻断已有路由 |
| `api/platform_observe.py` | prerequisites 依赖 probe.ready，并把配置存储称为 installer-verified | 改为配置/实时连接状态；诊断明确显示未测/历史结果 |
| `RuntimeKubernetesRepository.bind_resource` | 初次绑定 UID 时根据当前保护位固化历史 | 改为根据 Backend 已认可的配置保护合同固化；不是诊断成功位 |
| 同 Repository `confirm_resource_stopped` | 历史位和当前位同时满足，才接受停止事实 | 保留两者；当前位来源变更，真实 UID 停止证据不变 |

当前关键代码：`k8s_capabilities.py:70–84,165–223`；`executors/kubernetes.py:110–203`；`operations.py:623–641`；Backend `runtime_operation_service.py:142–323,75–83,405,773–798`；`runtime_kubernetes_repository.py:290–318,361–387`。

只令 `assess_capabilities` 无条件返回 ready，会留下 Backend 保护协议、路径、RuntimeClass、诊断 API 和清理流程中的旧闸门，不是完整修复。

## 3. 建议的最小配置与消息合同

### 3.1 一个受信配置来源

建议由 Chart 的同一组 values 生成一份有版本的 `runtime-policy.json`，只读挂载给 Manager、Admission，并由 Backend 加载对应 node_id 的期望配置。

建议最小字段：

```text
contract_version: 2
mode: operator-configured
installation_id / node_id / cluster_id / execution_namespace / platform
protection: status_policy_revision、状态来源规则、binding/delete 围栏规则
workload: 镜像与Helper引用、资源、阶段超时、节点调度、RuntimeClass
network: Service/Pod CIDR、API/平台/代理地址及允许端口、包源
storage: class选择模式、accessMode、size、filesystem、容量保护、静态池
delivery: bundle/image/source-image启用配置、镜像仓库/包源配置
```

密钥内容不进入 policy、digest 输入的公开副本、心跳或报告；仅允许必要 Secret 引用名。Backend 不持集群 SDK/权限，符合 constitution C1。

Backend 必须有部署时登记的每 node_id 期望配置，不能仅凭 Manager 心跳自己声称“configured=true”就改变信任来源。仍使用现有独立 HMAC 身份、角色及 node_id 绑定；不增加注册任意节点的业务接口。

建议使用同一份 JSON 字节生成并核对 SHA256，或使用有测试向量的统一 canonical JSON 规则；不能让 Helm/Go 与 Python 各自猜测序列化方式。配置版本、摘要及作用域不符时给出明确配置错误，不回退为旧报告放行。

### 3.2 分开运行状态与诊断

建议在现有内部心跳 `capabilities` 中增加版本化的配置观察对象，名称供实现阶段统一：

```text
configuration:
  version: 2
  source: operator-configured
  policy_digest: <sha256>
  protection_baseline_digest: <sha256>
  state: configured | invalid
```

Backend 验证该对象与本节点的期望配置相同，结合已有身份、平台/执行域校验、预算及真实 API 可达性，决定新执行的 ready 状态。`configured` 只表示配置有效，不表示 CNI/CSI 经过实测。

`probe_report` 继续保存显式诊断的实际结果，但不参与新合同 readiness、路径启用、保护历史及入口判定。没有报告时输出 `not_run`、`observed_at: null`、空 checks；不得合成 `source: cluster-probe`、随机 UID 或 15 项 ok=true。

`/healthz` 仍只表示进程存活；环境状态接口分别提供配置状态、控制连接状态、可选诊断结果。用户可在没有手动诊断的情况下正常安装与发布应用。

本次不应顺带扩大节点 API 不可达、应用实际不健康等情形的放行范围。需要定向验证：只改变诊断的缺失/年龄/结论，已有节点状态、路由、资源保护位不得变化；实际配置或运行错误仍保留原安全行为。

### 3.3 路径与 RuntimeClass

| 能力 | 资格来源 | 真实失败在哪处理 |
| --- | --- | --- |
| bundle | 受信运行/准备镜像、材料链路、包源与存储配置完整 | 本应用 prepare/probe 的实际拉取、材料、依赖构建及健康失败 |
| image | 可信冻结 digest、镜像凭据与平台配置完整 | 本应用镜像检查、CRI 拉取/启动及健康失败 |
| source-image | 显式启用，配置 assembler、可写镜像仓库及对应凭据 | 实际组装/推送失败；不依赖可选 registry-push 报告 |
| 强化 RuntimeClass | 受信部署显式选择的 RuntimeClass | 实际无法调度/启动时报明确原因；不伪造 sandbox 测试通过 |

默认 bundle/image 不因未提供可写 OCI 仓库而整体 blocked。未启用 source-image 时只禁用相应路径。

RuntimeClass 选择不再随手动报告变化。继续继承 F059 AC-19/AC-31 的合同：更强隔离不可用时明确告警，回退到满足必需基线的默认档，并记录实际生效档位。不能因取消报告门槛而静默声称已启用强化隔离，也不在本次默认改成新的拒绝策略。具体取消报告后的能力判定来源待正式设计评审。代码沙箱开关与托管应用 RuntimeClass 不是同一个功能。

## 4. status/binding 保护与单写不变式

### 4.1 保护位的含义

新合同下，保护位表达：运维为该执行域配置了预期的 status 来源校验及 binding/delete 围栏，Backend 已认可这份配置。它不再表达“最近一次诊断已实测通过”。诊断页面必须展示这一来源区别。

为控制迁移范围，可以暂时保留内部字段 `status_protection`、`binding_protection` 及资源表两列名称，但必须增加版本/source，更新字段注释、DTO 与测试口径。`binding_policy_verified` 是遗留列名，不得在界面解释为手动诊断已通过。若实现阶段认为必须改列名，应单独评估双数据库迁移，不为改名扩大本轮工作。

### 4.2 两种摘要服务不同用途

- `policy_digest`：对新操作的完整执行配置，包含资源、超时、调度、镜像和网络/存储设置。
- `protection_baseline_digest`：仅对保护连续性有关的安装/执行域身份、status/binding 规则及版本、可信写入者等计算。

修改 CPU、阶段超时或调度偏好不应清除所有旧 Pod 的保护历史。变更 status/binding 规则语义必须提升对应 revision，并处理存量资源，不能复用旧 revision 假装保护连续。

当前代码把大部分 descriptor 变化作为保护基线变化，见 `protection_baseline_digest`；新合同需要缩小该摘要的责任，不能只把报告从输入移除。

### 4.3 保护历史如何建立和失效

1. Backend 首次绑定真实 Pod UID 时，读取已认可的配置保护合同，并保存该资源当时的保护历史；保持既有 generation/epoch/模板/UID 围栏。
2. 诊断未运行、变旧、被删除或检查失败，不自动修改这些历史位，也不自行停应用；诊断如发现实际问题，由运维修复或显式停用执行域。
3. 运维明确关闭/更换保护规则、作用域不一致或确认发生保护断档时，禁止新执行/停止事实接纳，并按原保守原则降低受影响 UID 的历史位。
4. 仅配置消息暂不可解析时，不得声称拥有当前停止授权；也不能把“解析恢复”当作旧历史已修复。实现需区分暂不可用、明确规则变更及既有历史 false。
5. 已为 false 或未知的旧 UID，不能因新模式启用、升级、重新发送心跳或诊断成功而补写 true。恢复遵守已有人工维护/节点证明边界。

### 4.4 停止与清卷仍检查真实事实

保留现有 `StopIdentity`、fresh API 读取、namespace/name/UID、resourceVersion、删除时间、finalizer、策略版本及所有容器停止状态的校验；`Unknown`、`NodeLost`、`ContainerStatusUnknown`、同名新 UID、仅 API 404 均不等于旧进程停止。

未调度 Pod 的 binding/delete 围栏与已绑定 Pod 的可信终态仍采用现有独立证据路径。当前 Backend `confirm_resource_stopped` 同时检查资源历史和当前保护能力，必须继续保留；不能将运维声明当作一个 Pod 已经停止的证据。

生产 serve/migrate/restore/data/purge 复用固定生产位置；旧写入者停止未确认时不启动新写入者、不强删、不释放预约、不清 PVC。SQLite 迁移/备份确认屏障及 helper flock 不因诊断变为可选而变化。

参考：`k8s_lifecycle.py::classify_stop/finish_stop`、`k8s_admission.py::_terminal_status`、Backend `runtime_kubernetes_repository.py::confirm_resource_stopped/release_resources`。

## 5. 手工诊断保留方式

- 保留 `scripts/verify_k8s_runtime.py --live` 和安全清理能力；运维显式启动，实际创建的 canary 保持独立身份、安装范围、UID 和回收保护。
- `--write-report` 只更新诊断结果，不改变配置摘要/运行资格/旧 UID 保护位。报告更新须继续使用 CAS，不能覆盖并发配置。
- 报告记录实际时间、配置摘要、每项真实结果与脱敏原因；配置已变化时显示“针对旧配置”，年龄仅展示或告警，不作为运行时锁。
- 周期诊断可以由运维自己的工具安排；取消脚本只允许固定 21600 秒的要求，或去掉内置常驻循环，保留一轮命令供任意调度器调用。标准 Chart 不依赖该循环。
- 手动诊断未运行不生成“已通过”记录；手动诊断失败也不伪装成配置声明失败。没有自动下线责任的工具应明确给出处理提示及非零退出码。
- 单独的显式停用/修复操作沿用受信运维变更，不新增普通业务用户可提交的“忽略隔离”参数。

## 6. 参数化必须贯通的最小合同

| 配置组 | 配置消费者与冻结位置 | 不能只改 Helm 的原因 |
| --- | --- | --- |
| 资源 | values → policy → Backend 新操作冻结档位/Helper开销 → Manager PodPlan → approved template → Admission | image-check 目前有固定 Helper CPU；资源预约和 Pod 实值必须一致 |
| 节点/调度 | architecture、nodeSelector/affinity/tolerations/RuntimeClass → 同一 policy → 操作或资源冻结模板 | Backend 当前精确要求 linux+arch，不能只在 Pod 上追加节点约束 |
| 超时 | 任务绝对 deadline、阶段调度/物化/镜像检查/健康窗口、API请求及grace/cleanup → 配对配置与冻结 | PodPlan/Backend 当前 image-check ≤120，image_check.py 自身60，启动阶段固定90；只调一层仍超时 |
| 网络 | 同一 policy → Chart Services/NetworkPolicy → Manager/Admission/Backend CIDR/端口校验 → 应用阶段代理授权 | 改 Service 端口或 IP 不能遗漏准入、平台目标验证、控制流量和 phase 出站策略 |
| 存储 | class选择模式、existing/static pool、size/accessMode/filesystem及容量保护 → PVC模板/准入/运行期 guard | 空字符串 class 与省略不同；不能去掉运行期有界卷检查来代替取消环境诊断 |

具体要求：

- 保留应用用户不能传 nodeName、hostPath、privileged、任意 PodSpec 的边界；部署侧调度约束是预配置政策，不是发布接口的新参数。
- 新操作冻结所选政策版本/摘要和执行参数；已有 resource intent 继续使用其 approved template，不能因 Helm values 改变而重新渲染成另一个 Pod。
- 原 absolute deadline、原阶段起点在重启/重试后继续使用；不通过增大 values 给已过期操作续命。
- 超时有限且 schema 有合理边界；安全围栏、UID 规则、TLS 验证、禁止提权等不作为可任意关闭的“超时参数”。控制器租约若需配置，必须连同 Backend 30 秒租约/Manager续约窗口配对设计，不混入首轮普通任务超时调整。
- 静态 local PV、ext4/xfs/容量 guard 是另一个存储支持合同。取消安装诊断不自动移除它们；要支持共享底层容量或更多文件系统，应补真实配额/锁/持久化适配，沿用户已批准的存储方案处理。
- `storageClassName` 用三态：省略=集群默认；非空=指定类；显式无类模式=空字符串。Manager 和诊断工具必须一致。

## 7. 兼容与交付阻塞

1. **配对版本。** 旧 Manager 只懂 descriptor schema 1、旧 Backend 只接受 protection_observation v1；不能仅用新 values 配旧镜像。建议新配置合同显式 version 2，非法/不支持版本给出明确原因，避免静默 fallback。正式发镜像前须验证升级次序；本轮不发布。
2. **存量资源。** 不能把所有旧 Pod 历史位清 false，也不能全部补 true。可仅在原历史为 true、同执行域/策略 revision、Backend 认可运维配置延续同一保护合同时保存其历史；旧 false 保持。迁移必须有配对测试和审计说明。
3. **混合版本。** 如需要 Backend 先升级兼容旧 Manager，保留显式旧消息适配器；新标准路径只使用 v2，不为两种来源混造报告。是否支持滚动混用须在版本交付合同中说明，不能无测试承诺。
4. **配置来源。** 当前只有 Docker host isolation 的部署期 per-node 配置先例，K8s 尚无等价期望 policy 登记；需要正式 settings/config 入口。Backend 不以新增 K8s API 权限解决此问题。
5. **公开状态口径。** API/日志中现有 verified、mandatory_isolation、probe.ready 命名需逐处审查，不让“运维配置有效”被展示成“15项实测通过”。
6. **策略变化与已冻结操作。** 调度/超时 schema 的新值必须同时通过 Manager、Backend 和 Admission；缺少旧政策的持续可读表示时，升级可能阻断在途资源对账，需要冻结材料兼容方案。
7. **无额外安装验收账户。** 标准 Helm 不因取消预检仍留下 canary Job/Cron/Secret 的强制依赖；手动诊断身份仅在运维选择运行时提供。配置初始化、TLS 与 catalog seed 是独立职责，不混称为验收。
8. **原文档冲突。** F059 AC-23/30/31、design 4.10、README 中“必须实测/24h/6h/不能覆盖”是旧合同，应明确标记由本特性替代；不能只改代码后保留旧说明。

## 8. 最小必要测试建议

这些是实现后的测试建议，本草案未执行测试。

| 编号 | 必须验证的结果 | 建议所在测试 |
| --- | --- | --- |
| RT-01 | 新安装无 probe_report，配置完整且控制链路可用，允许应用 prepare/probe；诊断显示 not_run | Manager capabilities + Backend heartbeat 配对 |
| RT-02 | 相同配置的旧报告在24h、数天后不阻断新应用及已有入口 | 可控时钟，Backend create/admit/route |
| RT-03 | 手工报告缺失/坏时间/失败/旧摘要不会修改 node.status、路径或旧UID保护历史 | protection heartbeat/repository 配对 |
| RT-04 | policy无效、版本不支持、摘要/作用域错配不能由一份成功报告放行 | 配置解析、Backend _node_report |
| RT-05 | 非Manager身份、跨node_id或自报未登记配置被拒绝 | Backend身份/heartbeat API |
| RT-06 | 新UID按认可的配置建立保护历史；已有false绝不因切模式/恢复心跳变true | bind_resource + 升级配对 |
| RT-07 | 无诊断仍可正常停止；未知容器、同名换UID、404、缺停止证明不清卷/不释放预约 | lifecycle、admission、Backend stop/purge |
| RT-08 | 调整CPU/超时不清除旧Pod保护历史；真实保护revision变化保持保守失效 | protection baseline/digest |
| RT-09 | source-image缺配置只禁该路径；无registry诊断不阻塞已配置路径；实际推送失败保留阶段原因 | capabilities + prepare/assembler |
| RT-10 | RuntimeClass显式选择按配置执行；无诊断不静默降级；非法类/启动失败给出真实原因 | PodPlan/操作冻结/观察 |
| RT-11 | 非默认节点selector/affinity/tolerations在Manager→Backend→Admission一致；发布调用者不能注入任意Pod字段 | 模板与Backend注册配对 |
| RT-12 | 镜像检查资源/阶段超时配置贯通；近deadline、重启/重试不会重置原起点或延期 | image-check与阶段持久事实 |
| RT-13 | 默认SC省略字段、指定SC、显式无类静态池三种均正确；WFFC不提前失败 | PVC模板与诊断工具 |
| RT-14 | 保留SQLite单写、停止确认、备份确认、runtime volume guard及Retain行为 | 现有维护/恢复/清理回归 |
| RT-15 | 手动诊断只发布真实checks，CAS不覆盖配置，异常canary安全清理不影响业务 | verifier/report与R6回归 |
| RT-16 | 固定版本升级：旧true/false历史、在途操作/approved template、policy变更及混合消息拒绝 | Manager/Backend兼容合同 |
| RT-17 | Chart无122地址/节点/路径、无代码注入CM、无强制诊断Job/Cron；相关关闭/外部依赖组合可渲染 | Helm lint/template/schema/服务端验证计划 |

实现阶段优先跑这些有实际故障后果的定向测试及相邻回归；不用重复实现逻辑的机械测试替代跨层消息配对。真实集群/CNI/CSI业务验收留待获得单独部署授权后进行。

