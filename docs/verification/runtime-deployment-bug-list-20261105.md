# Kubernetes 运行时产品问题清单

日期：2026-11-05。核查基线：`feat/3.1.0-beta1@0639aa623f`。
分支：`codex/3.1.0-beta1/runtime-deployment-bugfixes`。

本文记录已核查的问题和范围，尚未实施产品代码修复。122 的历史对象运维处置与产品缺陷关闭分别记录。

## 待修复清单

| 编号 | 问题 | 范围与修复目标 | 状态 |
|---|---|---|---|
| R1 | 空 initContainers 与 API omitempty 不一致 | 生成端不输出空字段；Admission 对旧空字段仅做窄兼容，非空模板保持严格校验 | 待修 |
| R2 | image-check 不在日志容器白名单 | 允许固定容器名，保留路径、大小、时间范围约束 | 待修 |
| R3 | Kubernetes 配额拒绝丢失主因，误报依赖构建失败 | 受限提取原生/KubeSphere quota 原因与资源数字，Manager/Backend/CLI 分类及提示一致；普通403不得误判配额不足 | 待修 |
| R4 | API Key expires_at 丢时区后立即过期 | aware 输入转换为现有本地 naive 时间合同；保留 naive 输入和历史数据语义，不迁移历史记录 | 待修 |
| R5 | 预检 canary 漏传私有镜像拉取凭据 | 执行域、控制域使用各自凭据，支持不同namespace及不同Secret名，不自动扩散凭据 | 待修 |
| R6 | 预检异常停止、回收与恢复闭环不完整 | 见下文分项；代码缺陷、正确保护和维护恢复能力分开处理 | 待修/待设计 |
| R7 | 冷镜像检查消耗 listener 的有限生命周期 | 调整真实检查顺序，避免无关前置耗时使后续检查误失败，不无限延长租约 | 待修 |
| R8 | 网络正对照来源和瞬断处理不准确 | other-app 从正确策略身份探测；DNS仅正对照做有界重试，永久失败仍报告失败 | 待修 |
| R9 | 可选 settings.admin 自动预置缺 external_id | 此可选路径单独确认是否修复；正常首次注册授超管的流程保持 | 待定 |

配额数值、节点和存储等属于部署参数；资源/期限参数化及完整 Helm 产品化另按方案安排。自动排队、动态配额查询与自动调整额度不是这次缺陷修复的默认前提。

## R6：历史预检残留的归因

### 现场对象

| Pod | UID |
|---|---|
| preflight-066b70ef211142f69eca | 0c7b4553-aab7-4fdd-a0f5-3839686a9795 |
| preflight-981c64a1625445cabf11 | 01747234-fcb5-40dd-b801-7a0b811c8f9e |
| preflight-9d47932ff2ea48d1a64d | 4fd66c58-bd7f-4afa-a40f-92e10ac7dd73 |

三者创建于 2026-11-04 18:30–18:36（台北时间），位于124节点；最终 Pod.phase=Failed、reason=DeadlineExceeded，data-layout 为 ContainerStatusUnknown，无可信 containerID/起止时间，均无 PVC/hostPath。PodSpec 均未携带 imagePullSecrets。现存历史 Events 已不足以逐一证明最初的拉取错误，不能把 Unknown 或占位 exit137 直接认作 OOM。

2026-11-05 的节点复核发现：按三个精确 UID 查 Docker，仅剩已退出 pause sandbox；Running=false、PID=0，未发现对应运行中的应用/初始化容器。第三只虽已无 finalizer，kubelet 仍每10秒收到 `admission_kubelet_delete_unconfirmed`，与源码路径一致。

### 分类与代码位置

1. **R5 / 通用工具代码 Bug**：`scripts/verify_k8s_runtime.py::_pod`、`_control_probe` 没有传递相应 pull Secret。私有镜像需认证且未预拉取时可能触发；本次确认凭据引用缺失，但初始逐 Pod 拉取报错未完整保留，不能仅归因于122配置填错。
2. **R6-a / 通用代码 Bug**：`stop_confirmed` 仅看 Pod 终态与无 running 状态，没有完整拒绝容器级 Unknown/NodeLost/ContainerStatusUnknown，与准入采用的停止证明规则不一致。
3. **R6-b / 通用代码 Bug**：`_cleanup_one` 发布 stop_state=confirmed 时漏写 stop_confirmed=true，正常停止对象也可能缺少准入所需授权。
4. **R6-c / 代码健壮性问题**：cleanup/recover_expired 中单个异常对象可中止后续对象回收。应独立汇总失败并回收其它已确认安全的对象，不静默忽略错误；共享卷/未知写入者仍必须阻断回收。
5. **正确保护，不作为待放宽的Bug**：`k8s_admission.py::_terminal_status` 拒绝 Unknown，`_terminal_delete` 在 finalizer 检查前要求可信停止状态。不能把所有 Unknown 或所有管理员删除普遍放行。
6. **R6-d / 产品交付的异常恢复能力缺口**：正式交付的预检清理/过期恢复路径，尚不能闭合这类经节点核实停止但 API 仍 Unknown 的旧 canary；需要标准化受精确 UID、维护身份和权限边界限制的恢复流程。正常自动回收与异常维护恢复应分开设计，不能仅删除 finalizer 或写入伪造停止状态。
7. **122 运维遗留处置**：三个旧 API 对象需要单独安全清理。即使产品工具已补正，新版本也不能将历史 Unknown 自动视为已停止。

122 自定义工具已经修正部分凭据与停止字段，但产品仓库仍未同步；本次清理历史实例不等于 R5/R6 已修复。

第三只对象在 `_terminal_status` 的 Unknown 检查即被拒绝；漏写 `stop_confirmed` 不是已证实该对象卡住的直接原因，不能只补该布尔字段就视为完成修复。

### 必需回归

- 执行域/控制域不同 Secret 名的私有镜像预检。
- Failed + Unknown、缺少 containerID/起止时间，不授权停止或卷复用。
- 正常终止后发布完整停止授权，同 UID/RV 再解除 finalizer并删除。
- finalizer 为空的 Unknown 对象，普通 kubelet 删除仍受停止证明保护。
- 单个未知对象不阻断其它可证明安全对象的清理；整体仍明确返回失败和诊断。
- 维护恢复严格限制对象 UID、身份、动作与核验时间；拒绝同名替换、业务Pod和业务卷。

## 122 运维处置记录

状态：**已完成历史对象清理，产品 Bug 尚未修复**。最终核验时间：2026-11-05 09:27 UTC。

### 清理边界与方式

- 按上表三个精确 UID，先在124节点复核对应 Docker 进程均已退出（Running=false、PID=0），只剩已退出 sandbox；对象均无 PVC/hostPath。
- 普通删除受停止证明保护阻断，因此只对资源 Webhook 临时增加维护例外：限定管理员身份、目标 namespace、三个旧 UID、Failed 状态及 UPDATE/DELETE。UPDATE 只允许移除停止 finalizer，保持 spec/status、标签、注解、ownerReferences 不变；status Webhook 与 failurePolicy 未改。
- 每个变更前校验节点证明时效，并带 UID/resourceVersion 前置条件；执行服务端 dry-run。移除 finalizer 或处理已有删除请求后，三个对象均确认 NotFound，未伪造 Pod 停止状态、未删除节点容器或业务卷。
- 临时例外已撤销，Webhook 正文与原始备份精确一致。初次尝试遇到 API 拒绝及对象自动消失返回404，均恢复准入配置后再处理；原始错误记录保留。

### 收尾验收

- 三个目标 UID 均已不存在；核心服务配置、原 Pod UID 与重启次数、持久卷与配额未发生本次维护导致的变化；全部原 Helm release 的 revision/status/chart 不变。
- 原运行中的预览 `task-5afd2067d381c23da78ecceda7fa4a67a48e67c8` 保持同 UID、Running/Ready、重启0次；本次未取消、重试或修改构建任务。
- 只读查询确认两次现有部署 `1e3bb0cac04b4f0c8db67f765e53d206`、`4c65119bdef7472a8b5c2e7ab5bd461b` 均为 completed/cleanup complete。
- 比对期间另有两个平台 stop 操作 `cca5cabaef5e45c7bbd312408f452e55`、`c5bdef7f025e4c3c8d0155d06b9514b1` 完成，对应应用服务与任务被正常回收；平台审计存在相应 `app.stop`（operator_id=1、reason=stopped by user）。本次维护没有调用 stop 接口。
- `bisheng-information` 中两只带 `purpose=temporary-source-browser-probe` 的临时探针也在比对期间消失，原因未在本任务追查；本次未对该 namespace 执行写操作，其余核心服务基线一致。原始差异已保留，不将“所有对象完全未变”作为验收结论。

操作证据保存于122服务器 `/root/bisheng-maintenance-audit/20261105-preflight/`。主要文件：`baseline.json`、`cri-proof.json`、`deleted-pods.json`、`webhook-restored.json`、`verification.json`（首轮原始差异）、`verification-final.json`（复核结果）、`application-verification.json`、`concurrent-stop-audit.json`。维护脚本作为本次审计材料保存，不作为产品启动补丁或标准回收方案。
