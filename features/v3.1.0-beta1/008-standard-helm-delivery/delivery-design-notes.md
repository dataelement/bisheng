# 标准 Helm：交付设计核对笔记

状态：设计草案，供本特性 `spec.md` / `design.md` 和实施审查使用；不是已发布安装能力的声明。

核对时间：2026-11-06。代码基线：`feat/3.1.0-beta1@99f81004fd2d2d754290aba223eac3fa7a099b56`。只读比较了公开仓库 Chart / 构建源码和私有 `k8s-product` 的 122 Chart、镜像锁及模板清单；没有访问集群、镜像 Registry 或真实凭据、许可证、私钥。本文所说“已有镜像记录”仅表示本地交付记录存在，不证明当前 Registry 可达。

## 1. 本轮边界与最新决定

- 只改代码、部署文件和说明，不构建或发布镜像，不部署线上。
- 标准 Chart 源码归公开 `dataelement/bisheng`，私有 `k8s-product` 继续保存环境 values 和交付证据，不再承载产品代码补丁。
- 资源、超时、节点、网络、存储配置可调；基础组件逐项可选，Gateway 可选；Vibe / 代码沙箱默认开启并说明关闭方法。
- 环境能力预检调整为可主动执行的诊断工具；不作为默认安装、发布、入口访问的强制前置，不因报告达到 24 小时阻断业务，不默认引入每六小时刷新任务。
- 应用自身的镜像检查、依赖安装、构建、启动、健康检查继续执行。移除环境报告门禁不等于移除 Pod 身份、签名、准入、网络隔离、单写约束或正常业务鉴权。
- 内部密钥/证书、实际 Service 地址和必需的数据库初始化仍需可靠初始化；这与取消强制环境验收是两个职责。
- 首次注册成为超管；官方 runtime catalog 使用受控幂等初始化，不要求管理员额外执行导入，也不虚构 `user_id=1`。

以上以用户最新确认优先于此前“强制环境预检 + installer CronJob”的候选方案。既有 Discovery / 部署说明中的旧策略需在主设计中同步更正，不能继续作为新标准交付要求。

## 2. 去除启动代码补丁所需的正式合同

122 的 `helm/bisheng-runtime/files/runtime-manager-compat.py` 不只是模板修补。实际有四项行为，必须逐项消除依赖：

| 补丁行为 | `99f81004` 源码事实 | 标准方案 |
| --- | --- | --- |
| 去掉空 `initContainers` | `k8s_templates.pod_template` 已在空列表时省略字段 | 使用修复后的 Manager，不在 Chart 注入 Python |
| 允许读取 image-check 日志 | `KubernetesClient.logs` 已接受该容器 | 使用修复后的 Manager，保留日志参数/字节限制 |
| image-check CPU 从固定 25m 提升到 2 核 | 正式 `_container` 仍固定 Helper CPU / 内存 | 按用途提供可信系统 Helper 资源配置，不把 122 的 2 核当成所有集群的固定值 |
| 节点列表写入 required nodeAffinity | 正式模板仍只有 Linux / 架构 selector | 实现可信执行调度策略，覆盖动态应用、准备任务、镜像检查、预览等 Pod |

移除范围包括代码文件、兼容 ConfigMap、workload 启动 command、checksum 注解、volume / mount 和专用补丁环境变量。保存普通业务配置的 ConfigMap 不属于启动代码补丁。

### 2.1 资源、超时和调度必须贯穿校验链

当前镜像检查同时受到以下限制：

| 层 | 当前源代码位置 / 行为 |
| --- | --- |
| Helper | `runtime_manager/image_check.py::check_images`，内部 60 秒 |
| Manager | `executors/kubernetes.py::_image_check`，执行期限最多 120 秒，创建年龄达到 120 秒失败 |
| PodPlan | `k8s_templates.py::PodPlan.validate`，image-check 最长 120 秒，data 最长 60 秒 |
| Backend | `runtime_kubernetes_service.py::_validate_image_check`，校验 activeDeadlineSeconds 最多 120 秒 |
| Admission | `k8s_admission.py::_pod_baseline`，同样限制 image-check 最多 120 秒 |

values 不能只修改上述某一层。应将系统执行策略作为一个版本化合同：由部署配置生成，同步用于计划生成、冻结校验、Pod 生成、Helper 行为和 Admission 验证；改变影响执行安全的配置时更新策略标识。不要允许应用包直接提供任意 PodSpec 或放宽资源/期限。

需要保持的语义：

- 运行时操作有绝对总 deadline，阶段超时不能超出剩余额度；重启和重试不重新获得完整预算。
- 区分镜像网络获取、解压/摘要验证、依赖安装、构建、应用启动及健康检查，不用一个无界 timeout 掩盖阶段错误。
- 保留 Linux / 架构必要条件；用户节点限制与这些条件取交集。不要使用 `spec.nodeName` 绕开 scheduler，也不能破坏 PV nodeAffinity。
- 支持 nodeSelector、affinity、tolerations 的受控范围；Backend 当前“精确等于 OS/架构 selector”的验证也必须同步调整。
- 应用主容器 CPU / 内存仍来自产品 ResourceTier 和审批后的冻结计划。Helm 管理控制面、系统 Helper 资源及 Namespace 总配额，不建立第二套绕过档位的应用资源来源。
- 控制面 Deployment 的 requests / limits、探针超时及调度也进入 values；短期默认值是可解释的通用默认，不复制 122 的节点分布。

取消强制环境预检后，诊断脚本本身仍有 `kubectl` 请求 30 秒 / 进程 40 秒、单项检查 180 秒、`crane` 180 秒等参数化工作。诊断超时不应变成业务 ready 的持续租约。

## 3. Chart 源码与依赖打包

目标入口沿用 `docker/helm/bisheng`。当前三份产品 Chart 的唯一源码位置分别是：

| 模块 | 目前唯一源码位置 | 可复用内容 / 必须修正处 |
| --- | --- | --- |
| 平台 | `docker/helm/bisheng` | 前后端、Worker、Linsight；补齐 Beat、可选基础组件/Gateway、按组件持久化与统一开关；Linsight PVC 缺失需修复 |
| 沙箱 | `docker/helm/bisheng-sandbox` | StatefulSet、逐 Pod DNS 会话保持、安全上下文；名称、namespace 和网络 allowFrom 不能固定为单一安装 |
| Runtime | `deploy/kubernetes/app-runtime` | Admission / RBAC / 执行域网络策略 / 配额；控制面共享 namespace 的策略范围及 Namespace 所有权需调整 |

可采用父 Chart + 本地依赖。实施前冻结唯一一种源码布局：保留当前 Runtime 路径并由本地 `file://` 依赖引用，或者将其移动到 `docker/helm/bisheng-runtime` 后更新全部测试和文档引用。不得长期维持两份可编辑 Runtime 模板。Sandbox 同理，不把另一份源模板复制到父 Chart 的 `charts/` 后分开维护。

建议打包规则：

1. 子 Chart 独立维护版本；父 Chart 使用固定 dependency version 与 `Chart.lock`。
2. `charts/*.tgz` 是从唯一源码生成的 vendored 发行产物；校验脚本证明其内容与源树一致，不能把压缩包视为另一份源码。
3. 下载父 Chart `.tgz` 后依赖已齐全，不要求客户现场执行联网 `helm dependency update`。源码用户通过受控打包命令重建依赖。
4. 所有依赖条件、values/schema 与 README 保持一致；模板应能在断网、无 kubeconfig 情况下完成静态渲染。
5. 不把 `k8s-product/environments/122` 的完整 values、密钥、许可证、TLS 私钥或业务数据复制进公开 Chart。私有 Chart 的环境字典渲染器可以借鉴结构，但不直接成为第二份通用 Chart。

父/子 Chart 的 namespace、labels、fullname 和 release 所有权须统一设计。一个 release 不得接管已有 MySQL / Redis release；共享 namespace 时，控制面 NetworkPolicy 只选择本安装的目标组件，不能对 namespace 内全部 Pod 默认拒绝。执行域仍可使用独立 namespace 和受控安全策略。

## 4. 镜像与 catalog：记录事实，不虚构发行

只读核对到的 122 镜像锁 `source_revision` 为 `f945f9eea55da83cd8477418e9b769021d339a8a`，并非当前修复基线。其记录为 `linux/amd64`：

| 类别 | 已记录版本 | 使用限制 |
| --- | --- | --- |
| Backend / Frontend / Sandbox / Manager / Proxy | `v3.0.0`，保存了 digest | 旧 Manager / Backend 不包含本轮与 R1–R10 新合同 |
| Helper / Assembler / Python / Python preparer / Node / Node preparer / Static | `v3.0.0-amd64`，保存了 digest | 仅证明 amd64 交付记录；不能据此宣称 arm64 镜像兼容 |
| Gateway | `v1.8.0`，保存了 digest | 122 记录，不代表当前 Gateway 最新发行或公共推荐版本 |
| OpenFGA | `v1.15.2-dm`，保存了 digest | 现有环境镜像，不能从其名称推断任意公开环境可访问 |
| ES / etcd / MinIO / Milvus | `8.12.0` / `v3.5.5` / `RELEASE.2023-03-20T20-16-18Z` / `v2.5.10` | 可作兼容调查依据；需单独确认公共镜像来源与发行支持范围 |

公开平台/沙箱 Chart 当前默认也是 `dataelement/*:v3.0.0`；Runtime Chart 当前要求用户填写镜像，没有默认兼容发行镜像。源码中没有已核验的新 `3.1.0-beta1` digest 清单。

122 `runtime-profiles.json` 是 schema 1 的三个环境模板：`python311-122@1`、`node20-122@1`、`static-122@1`，均为 `official=false`，只列 amd64，并在 defaults 中引用 `-122` 名称。这份文件不能原样冒充新的官方 catalog；应从正式镜像 inventory / tools 生成不含环境命名的官方模板。

交付原则：

- Chart version、目标 appVersion、实际镜像 tag / digest 是不同字段。目标代码版本可以写在设计中，不能据此编造 Registry 中尚未发布的 tag 或 digest。
- 镜像引用支持 repository/tag 与显式 digest；digest 优先时不能生成 `tag@digest` 歧义。`global.registry` 改写必须同时覆盖工作负载、初始化任务、运行模板和诊断工具。
- 开发/模板检查可以注入显式测试镜像值；尚未发布的兼容镜像必须作为未完成的发行前置列出，不能把旧镜像默认值解释为已完成标准安装验收。
- 替换旧 Manager 启动补丁，必须切换到包含正式模板/日志修复及新执行策略的镜像。Backend / Helper / Admission / 相关 CLI 也要使用兼容合同版本；Helper 继承 Manager，Assembler 继承 Helper，必须检查构建传播。
- 不覆盖旧 `v3.0.0` tag 或伪装相同 digest 已获得修复；不伪造所有镜像具有同一 source revision。可复用的未变镜像应如实记录原 revision 并提供兼容证据。

本轮代码提交不能消除此处“兼容镜像未发行”的限制；也不应因此偷偷触发镜像构建/推送。

## 5. 存储配置语义与静态兼容

StorageClass 不要求固定名称或厂商。默认 class 必须区分三种语义：

| values 意图 | 应生成的 PVC 字段 | 结果 |
| --- | --- | --- |
| 使用集群默认动态供应 | 省略 `storageClassName` | 由 Kubernetes 选择默认 StorageClass；没有默认 class 时按正常 PVC 事件诊断 |
| 指定动态 class | `storageClassName: <用户值>` | 使用指定 provisioner |
| 显式无 class 静态匹配 | `storageClassName: ""` | 不使用默认动态供应，只匹配无 class PV |

当前 `pvc_template` 和 verifier 将空字符串直接写成 `storageClassName: ""`；需要统一修复为显式三态配置，而不是只改 Chart 注释。

按组件提供 `enabled / existingClaim / storageClass / size / accessModes` 与调度配置。平台不统一强制 RWX：Backend、Worker、Linsight 的本地卷是否共享取决于真实用途，跨进程权威状态遵守 `docs/constitution.md#c8`。多副本跨节点共用 RWO 的配置需要报错或明确不支持；Linsight 引用但未创建 PVC 的现有缺陷应补齐。

Vibe 数据卷是持久化 SQLite 的独立合同，不能仅凭 RWO/RWX 判断兼容。当前 Helper 检查 ext4/xfs、真实容量约为请求的 0.8–1.1 倍，并验证锁、SQLite 与 fsync。保留这些应用执行前检查；不把取消环境报告门禁变成接受无界 hostPath 目录。新安装优先使用可提供实际容量边界的动态文件系统卷；具体 CSI 支持范围以测试结果发布。

122 静态池可保留为独立兼容模式：节点、路径、PV 名称和容量均配置化，节点管理员预先准备有界文件系统。保留 UID/resourceVersion/claimRef 比较与未知写入者保护；不让标准 Chart 自动格式化磁盘、SSH 到固定节点，或以数据库 root SQL 决定可以删除哪些卷。线上存储迁移、旧 release 合并不属于本轮。

## 6. 在线、离线与 Registry 能力分开

| 模式 | 必要条件 | 不应强加的条件 |
| --- | --- | --- |
| 在线 bundle / image 应用 | 产品/运行镜像可拉取；需要新增依赖时，Helper 可通过受控网络访问配置的 Python/npm 源 | 不因未提供可写 OCI 仓库就阻断所有普通应用 |
| source-image 应用 | 额外提供可写应用镜像 repository、可信 CA、受控 push 凭据及适用的构建网络 | imagePullSecret 不能代替写入权限，也不能假设任意 Registry 支持相同前缀授权 |
| 离线预置依赖 | Chart 依赖已内置；完整镜像清单可离线导入；依赖位于预置材料或可访问的企业镜像源 | 不承诺任意未缓存 PyPI/npm 依赖能在断网环境安装 |
| 手动环境诊断 | 同版本 verifier 及其显式工具依赖 / 身份；检查范围内需要的 canary 资源与仓库权限 | 不默认要求客户在 122 风格 root Docker 容器挂载主机 kubeconfig |

在线出站、`HTTP(S)_PROXY`、CA、PyPI extra-index、npm registry 和允许的访问端点应作为不同配置说明，避免“允许 443”却无法解析或被 proxy 拒绝。代码沙箱的联网策略与 Vibe 构建的代理出站路径分别配置。

离线交付至少包括 Chart tgz、固定 image-set、catalog、导入/镜像路径改写说明和校验摘要；本轮可完成清单生成与文档代码，不下载、重打包或发布镜像。公共 Registry 可达性、厂商镜像许可证和架构可用性应在发行前核验，不从 122 镜像锁推断已经完成。

## 7. 审查与验收矩阵

下表区分本轮可执行检查和需要未来兼容镜像/测试集群的证据；未执行不得标记为通过。

| 维度 | 应检查的组合 / 故障 | 本轮证据 | 真实安装证据 |
| --- | --- | --- | --- |
| 源码与 vendoring | 唯一子 Chart 源；固定版本；vendored 内容一致；tgz 断网可渲染 | 文件/打包校验 | 新集群使用打包产物安装 |
| 开关 | 默认；关闭 Vibe；关闭沙箱；关闭 Gateway；逐项外部基础组件 | lint、schema、template 对象断言 | 关闭组件不产生工作负载/业务误依赖 |
| 凭据与配置 | 默认示例；existingSecret；外部依赖；自动内部身份的初装/升级保留 | 模板与生成器测试；公开仓库敏感资料检查 | 升级保留现有密钥和数据；无真实运维凭据泄露 |
| 隔离 | 两个 release；共享控制 namespace；独立执行 namespace；不接管外部 release | 名称/selector/RBAC/NetworkPolicy 断言 | 实际多 release 互不干扰 |
| 镜像 | tag/digest 优先级；全部 workload/init/Helper/catalog 的 registry 改写；无假 digest | image-set 一致性测试 | 拉取、架构、来源及合同版本验证 |
| 执行策略 | 非默认 CPU/内存/timeout；不同节点选择；非法/越界配置 | Backend/Manager/Helper/Admission 合同与负例测试 | 慢网络镜像检查、依赖构建、实际调度与配额失败提示 |
| 环境报告 | 无报告、失败报告、时间超过 24h、不安装定时刷新任务 | 业务不再被报告门禁拦截的测试 | 已运行应用入口与新发布均不因报告老化失效 |
| 应用检查 | 坏镜像、依赖安装失败、健康失败、身份/单写不满足 | 保留失败路径与明确原因的测试 | Python/Node/Static；新增在线依赖；会话和数据恢复 |
| 存储 | 默认 class 省略；指定 class；显式无 class；existingClaim；Linsight PVC；多副本 RWO | 精确 PVC 模板和合同测试 | 合格动态 CSI；无默认 SC 的可诊断 Pending；静态池安全回收 |
| 初始化 | 首次注册超管；官方 catalog 幂等 seed；外部 OpenFGA/Gateway 的受控初始化 | 单元/组件测试与模板检查 | 新库首装、已有库升级、失败中止、用户默认值保留 |
| 手动诊断 | 不要求固定主机、IP、context；工具缺失与权限不足清楚失败 | 参数/错误与诊断输出测试 | 同版本工具在独立集群主动执行 |
| 升级/回退 | 不重新生成持久密钥；不丢数据库/PVC；不自动修改现有 122 release | 模板稳定性与说明审查 | 专用测试环境升级/回退演练 |

代码审查特别检查：取消门禁后没有 `ready=True` / 伪造成功报告的兜底；诊断失败不会清除真实业务故障；配额、签名、Pod UID 和挂载保护没有被一起删掉。

## 8. CI 与实际阻塞

本轮新增/修改的 CI 仅执行源码和模板验证：格式/类型或有意义的单元测试、Chart lint / schema / template、依赖打包一致性、渲染对象断言、镜像清单完整性、122 硬编码和启动补丁残留检查。使用本地假镜像引用测试不代表镜像存在。server dry-run 和集成测试需要明确测试环境；不能无 kubeconfig 时静默标为通过。

CI 不执行 `docker build`、镜像 push、Registry 删除、生产 kubectl/Helm 命令或自动发布 Chart。既有发布 workflow 的真正发布动作仍与本次代码验证分离；不得通过新增验证工作流间接触发镜像构建链。

当前阻塞应分层报告：

| 项目 | 是否阻塞代码/模板改造 | 是否阻塞宣称可发布/安装验收 |
| --- | --- | --- |
| 兼容当前合同的 Backend/Manager/Helper/Admission 等镜像未发行 | 否 | 是 |
| 新官方 catalog 尚未由正式 inventory 生成并接受初始化 | 否，可完成格式和 seed 代码 | 是 |
| OpenFGA 生产模型初始化、可选 Gateway 的版本化建表过程尚未验证 | 否，可完成受控入口和部署配置 | 是，对启用对应组件的标准首装 |
| 独立于 122 的测试集群、真实 CNI/CSI/StorageClass 证据缺失 | 否 | 是，对支持矩阵与端到端成功声明 |
| Public Registry 可达性、镜像架构/许可、离线镜像集合未核验 | 否 | 是，对相应在线/离线发行承诺 |
| source-image 没有可写仓库或所需凭据 | 否 | 只阻塞 source-image，不阻塞普通 bundle/image |

因此本轮可以交付可审查的代码、标准 Chart 和部署说明；结果应明确区分“静态与源码检查通过”和“真实空集群安装通过”，不能沿用 122 的成功证据证明新合同已安装成功。
