# OpenSandbox 调研报告

> 调研日期：2026-09-20
> 对象：github.com/opensandbox-group/OpenSandbox（阿里开源，Apache 2.0，CNCF Landscape 收录）
> 方法：通读仓库 README、架构文档（docs/architecture）、execd/server/egress 组件文档、Kubernetes CRD 文档、安全容器运行时指南、Helm 部署文档、Python SDK 文档、code-interpreter 示例
> 背景：为 bisheng 3.0 沙箱能力建设与 PTC 落地提供参考

---

## 目录

1. [项目概览](#一项目概览)
2. [总体架构](#二总体架构)
3. [全生命周期调用流程](#三全生命周期调用流程)
4. [沙箱的发现与管理机制](#四沙箱的发现与管理机制)
5. [Python 代码与 Shell 命令的执行支持](#五python-代码与-shell-命令的执行支持)
6. [部署与运维成本](#六部署与运维成本)
7. [Docker Compose 与 K8s 支持](#七docker-compose-与-k8s-支持)
8. [信创系统与硬件支持](#八信创系统与硬件支持)
9. [总结与对 bisheng 的建议](#九总结与对-bisheng-的建议)

---

## 一、项目概览

OpenSandbox 是一个**面向 AI 应用的通用沙箱平台**，提供多语言 SDK、统一沙箱协议和 Docker/Kubernetes 运行时，覆盖 Coding Agent、GUI Agent、Agent 评测、AI 代码执行、RL 训练等场景。

| 维度 | 内容 |
|---|---|
| 开源协议 | Apache 2.0 |
| 核心组件语言 | Go（execd/egress/ingress/controller/task-executor）+ Python（Server/SDK） |
| SDK | Python / JavaScript(TypeScript) / Java(Kotlin) / C#(.NET) / Go 五语言 |
| 接入方式 | SDK、osb CLI、MCP Server（可直接接 Claude Code / Cursor） |
| 镜像仓库 | Docker Hub / GHCR / **阿里云 ACR（cn-zhangjiakou，国内直连）** |
| 镜像签名 | Cosign 无密钥签名 + 来源证明（provenance attestation） |

核心特性：沙箱协议（OpenAPI 单一真相源）、Docker/K8s 双运行时、内置 Command/Filesystem/Code Interpreter 环境、网络出入管控、凭证保险库（Credential Vault）、强隔离运行时（gVisor/Kata/Firecracker）。

**重要更正**：OpenSandbox **不兼容 E2B SDK**，走自己的沙箱协议（此前 09-17 报告的说法有误）。

---

## 二、总体架构

### 2.1 三面分离

**控制面 / 数据面 / 网络面分离**，协议优先（`specs/` 下四份 OpenAPI 契约为单一真相源：sandbox-lifecycle / execd-api / egress-api / diagnostic-api）。

**客户端面**：五语言 SDK、osb CLI、MCP Server。

**控制面（生命周期）**：FastAPI Server
- 生命周期编排：创建/列表/续期/暂停/恢复/删除/快照/模板；API-key 认证；请求校验；
- `CompositeSandboxService` 路由：Docker → `DockerSandboxService`；K8s → 组合服务（带 `templateId` 或 ID 前缀 `fsb-` 走 FastSandbox，带 `image`/`snapshotId` 走 KubernetesSandboxService）；
- 持久化：SQLite（默认）或 PostgreSQL-HA。

**运行时后端（可插拔）**：
| 后端 | 机制 | 快照实现 |
|---|---|---|
| Docker | 本地/单主机容器 | 容器提交为本地 OCI 镜像 |
| Kubernetes | BatchSandbox/Pool/SandboxSnapshot CRD + controller-manager | SandboxSnapshot CR 提交推送 OCI registry |
| FastSandbox | Firecracker microVM，gRPC FastPath v2（9090） | 委托 FastPath 保存 VM 状态（仅 K8s 模式） |

**数据面（每个沙箱内）**：execd（Go/Gin 守护进程）
- 执行 API：`/command`（SSE 流式）、`/code`（Jupyter kernel 桥接）、`/session`（持久 bash）、`/pty`（WebSocket 交互终端）、`/files` `/directories`（文件操作）、`/metrics`；
- 生命周期管理：init 模式下作 PID 1 / subreaper，回收孤儿子进程、转发信号；
- 隔离会话：bubblewrap 命名空间 + setpriv/userns 降权；
- 加固地板（OSEP-0018）：用户进程经 `opensandbox-launcher` 注入——丢 capabilities、`no_new_privs`、seccomp deny 列表（mount/ptrace/bpf/seccomp）、Landlock 文件系统白名单。

**网络面**：
- Ingress Gateway：K8s HTTP/WebSocket 反向代理，Header / URI / 通配符主机三种路由；
- Egress Sidecar：FQDN 允许/拒绝规则，`dns` / `dns+nft`（nftables 强制解析 IP）两种模式；**Credential Vault**——透明 TLS MITM 代理按主机注入密钥，原始密钥不落沙箱。

### 2.2 隔离强度四层叠加

| 层 | 机制 | 开销 |
|---|---|---|
| ① 运行时后端 | Docker / K8s Pod / Firecracker microVM | — |
| ② 安全容器运行时（服务器级配置，对 SDK 透明） | runc（默认）/ gVisor（用户态内核，~10-50ms，~50MB）/ Kata QEMU（完整 VM，~500ms）/ Kata FC（microVM，~125ms，~5MB） | 见左 |
| ③ 沙箱内隔离会话 | bwrap + setpriv/userns + 可写挂载白名单（防 symlink 逃逸） | 轻 |
| ④ 加固地板 | cap 全丢 + seccomp deny + Landlock + no_new_privs | 轻 |

配置方式：`~/.sandbox.toml` 的 `[secure_runtime]`，Docker 模式填 OCI 运行时名（`runsc`/`kata`），K8s 模式填 RuntimeClass 名（`gvisor`/`kata-qemu`/`kata-fc`）。Firecracker 不支持 Docker 模式。

**已知坑**：gVisor netstack 未实现 `iptables nat`，与依赖 REDIRECT 规则的 egress sidecar 不兼容（换 kata-qemu 或 CNI 级 FQDN 策略）；`execd-ebpf` 审计变体的服务端选择未接线，勿用于生产。

---

## 三、全生命周期调用流程

以"上传 Excel → pandas 处理 → 取回结果和产物 → 销毁"为例（Python SDK）：

```python
import asyncio
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import WriteEntry, SearchEntry
from opensandbox.code_interpreter import CodeInterpreter

async def main():
    config = ConnectionConfig(domain="localhost:8080", api_key="...")

    # ① 创建沙箱
    sandbox = await Sandbox.create(
        "opensandbox/code-interpreter:v1.1.0",
        timeout=600, connection_config=config,
    )
    try:
        # ② 传文件：POST /files
        with open("销售数据.xlsx", "rb") as f:
            await sandbox.files.write_files([
                WriteEntry(path="/workspace/销售数据.xlsx", data=f.read(), mode=644)
            ])

        # ③ 执行代码：建 Jupyter 上下文（POST /code/contexts）→ 流式执行（POST /code）
        ci = await CodeInterpreter.create(sandbox)
        ctx = await ci.create_context()
        r1 = await ci.run_code(ctx, """
import pandas as pd
df = pd.read_excel('/workspace/销售数据.xlsx', sheet_name=None)
summary = {name: len(sheet) for name, sheet in df.items()}
df['汇总'].to_parquet('/workspace/汇总.parquet')
summary
""")
        print(r1.logs.stdout)   # 流式 stdout
        print(r1.result)        # 最后一格表达式的返回值（结构化）

        # ④ 获取结果：同上下文变量存活，可继续计算
        r2 = await ci.run_code(ctx, "df['汇总'].describe().to_dict()")

        # ⑤ 取处理完的文件：GET /files/{path}
        content = await sandbox.files.read_file("/workspace/汇总.parquet")
        with open("汇总.parquet", "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode())
        found = await sandbox.files.search(SearchEntry(path="/workspace", pattern="*.parquet"))
    finally:
        # ⑥ 销毁
        await sandbox.destroy()   # = kill() + close()，触发 DELETE /v1/sandboxes/{id}

asyncio.run(main())
```

### 各步骤的底层机制

| 步骤 | SDK 调用 | 底层 HTTP | 说明 |
|---|---|---|---|
| 创建 | `Sandbox.create(image, timeout=10m)` | `POST /v1/sandboxes` | 起 Pod/容器（池化从 Pool 领）→ execd `/internal/init` 注入 token 哈希+envs → `/ready` 200 才返回 |
| 传文件 | `files.write_files([WriteEntry])` | `POST /files`、`/directories` | 二进制直写沙箱 FS，`mode` 设权限；`search`/`delete_files` 管理文件 |
| 执行代码 | `ci.create_context()` + `ci.run_code()` | `POST /code/contexts` + `POST /code`（SSE） | Jupyter kernel 桥接，变量跨调用存活 |
| 获取结果 | `execution.logs.stdout` + `r.result` | SSE 事件流 | stdout/stderr 与结构化返回值分开；后台任务用 run_id 轮询 |
| 取产物 | `files.read_file(path)` / `files.search` | `GET /files/{path}` | 无自动 artifacts 收集——文件系统即工作区；大文件可用 `get_endpoint(port)` 把沙箱端口暴露成 HTTP 直拉 |
| 销毁 | `sandbox.destroy()` | `DELETE /v1/sandboxes/{id}` | Docker：删容器→停 egress sidecar（9s 宽限）→清 volumes；K8s：删 CR 级联清理 |

**收尾的替代项**：`pause()` 冻结进程（resume 后 sandboxId 不变）；`create_snapshot()` 落 OCI registry（下次 `Sandbox.create(snapshot_id=...)` 复用）；`renew(timedelta)` 续期；不续期默认 10 分钟 TTL 自动回收。

**两个易踩的坑**：
1. 上下文管理器只调 `close()` 不 kill——`async with` 离开后远程沙箱仍在跑，必须显式 `destroy()`；
2. SDK 直连 execd 的所有请求都需 `X-EXECD-ACCESS-TOKEN`（token 由 Server 注入哈希），绕过 SDK 直连会认证失败。

---

## 四、沙箱的发现与管理机制

### 4.1 发现：登记制，不是扫描制

四条信息流协同：

1. **权威账本在 Server 数据库**：沙箱元数据（状态、TTL、metadata）持久化在 SQLite/PostgreSQL；Server 重启恢复过期计时器（TTL 为绝对时间，跨重启不重置），从不需要反向扫描容器列表；
2. **K8s 路径走 CRD 调和**：Server 写 BatchSandbox/Pool CR（期望态）→ controller-manager 调和出真实 Pod → 状态经 informer/轮询收敛回 `status`（phase + conditions + task 计数器 + `observedGeneration` 校验）；
3. **就绪验证靠 execd 登记**：`/internal/init` 注入绑定 + `/ready`/`/ping` 可达才置 Ready——**execd 是沙箱的"身份证"**，镜像里没跑 execd 就无法被纳管；
4. **FastSandbox 特例**：FastPath gRPC v2，`fsb-` ID 前缀路由，端点按需解析。

端点发现动态生成：K8s 侧写在 BatchSandbox annotation `sandbox.opensandbox.io/endpoints`，Ingress Gateway watch 实时路由；Docker Bridge 模式带内置 HTTP 路由。

### 4.2 管理：两个 CRD 解耦"调度"与"供给"

- **BatchSandbox**（实例调度）：`replicas=N` 管实例数，`shardTaskPatches` 批内异构任务，`pause` 触发暂停/恢复；状态机 `Pending → Succeed → Pausing → Paused → Resuming / Failed`（Succeed 非终端，只表示至少一个 Pod 可用）；
- **Pool**（预热供给）：`capacitySpec` 四参数（bufferMin/bufferMax/poolMin/poolMax）控制缓冲与总容量；`scaleStrategy.maxUnavailable`（默认 25%）分批扩缩，上一批 Ready 才扩下一批；驱逐走 `pool.opensandbox.io/evict` 标签，只驱逐空闲 Pod；容量耗尽时 `PoolAllocationPending=True`，超 `pool_acquisition_timeout_seconds`（默认 30s）返回 **HTTP 429 + Retry-After**；
- **SandboxSnapshot**：暂停/恢复核心资源，同节点 commit Job 提交 rootfs 到 OCI registry，恢复时重写模板镜像重建、保持 sandboxId 稳定。

### 4.3 配比：严格 1 : 1

| 运行时 | 配比 |
|---|---|
| Docker | 1 容器 = 1 沙箱（egress sidecar 是另一容器，主容器借用其网络命名空间） |
| Kubernetes | 1 Pod = 1 沙箱（主容器 + 可选 egress sidecar 同 Pod）；replicas=N → N 个独立 Pod |
| Pool | 1 预热 Pod 分配后整体变成沙箱 Pod（不是切分多租） |
| FastSandbox | 1 microVM = 1 沙箱 |

设计准则：**独占的都是工作负载**（容器/microVM/execd 进程树/cgroup/网络策略状态），**共享的都是基础设施**（Ingress Gateway/节点级 fastlet/控制面/镜像存储）。execd-ebpf 审计按"沙箱 cgroup"圈定事件范围，佐证 cgroup 边界即沙箱边界。

---

## 五、Python 代码与 Shell 命令的执行支持

### 5.1 Shell 命令（路径 A）

`sandbox.commands.run(cmd, handlers=...)` → execd `POST /command`，SSE 流式回传：

```python
execution = await sandbox.commands.run(
    "pip install pandas",   # command 字段：shell 语法（支持管道/重定向）
    handlers=ExecutionHandlers(
        on_stdout=lambda m: print(m.text),
        on_stderr=lambda m: print(m.text),
        on_execution_complete=lambda c: print(c.execution_time_in_millis),
    ),
)
```

- **防注入设计**：`command` 走 shell 语法；`argv` 字段是字面量数组（`$HOME` 不展开），按需选择；
- **前台/后台**：前台 SSE 流式；后台命令返回 run_id 轮询，输出保留 24 小时（janitor 每小时清理，运行中的永不清）；
- **持久会话**：`/session` 持久 bash（环境跨命令保留）；`/pty` WebSocket 真交互终端（支持 viewer 只读旁观、takeover 抢占）。

### 5.2 Python 代码（路径 B，三种姿势）

| 姿势 | 用法 | 适用场景 |
|---|---|---|
| **CodeInterpreter（正统）** | `opensandbox-code-interpreter` SDK + 官方镜像；`POST /code/contexts` 建 Jupyter kernel 上下文，`/code` 流式执行；变量跨调用存活；返回值分 `logs` 与 `result` 两块 | 多轮交互式数据分析（如 Excel 多 sheet 解析） |
| **轻量** | `commands.run("python -c '...'")` 或 `files.write_files` 写脚本再执行 | 一次性脚本 |
| **加固** | `sandbox.isolation.create()`：bwrap 命名空间 + 降权 + 可写白名单，`profile="strict"` + idle_timeout 自动 GC | 模型生成的不可信代码 |

官方 code-interpreter 镜像基于 Ubuntu 24.04，预装 **Python 3.10–3.14、Java 8/11/17/21、Node 18/20/22、Go 1.23–1.25** 多版本（运行时 `source code-interpreter-env.sh python 3.11` 切换），内置 Jupyter 多语言 kernel（ipykernel/IJava/tslab/gonb/bash）。

**选型一句话**：跑脚本/装依赖 → `commands.run`；多轮分析变量要活 → CodeInterpreter context；模型现写代码 → isolation 加固会话；长会话保环境 → pause/snapshot。

---

## 六、部署与运维成本

### 6.1 单机 / Docker 模式（开发与轻量生产）

```bash
uv pip install opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server          # 默认监听 8080
```

- 依赖：Docker + Python 3.10+；Server 本身是 Python FastAPI 单进程，控制面开销极小；
- 持久化默认 SQLite（零依赖）；强隔离可配 runsc/kata（宿主机装好即可）；
- 适合：本地开发、单机 PoC、中小规模内部使用。

### 6.2 Kubernetes / Helm 模式（生产）

```bash
# base chart（CRD+RBAC，每集群一次）
helm install base https://github.com/opensandbox-group/OpenSandbox/releases/download/helm/base/0.1.0/base-0.1.0.tgz
# controller
helm install opensandbox-controller <controller tgz> --namespace opensandbox-system --create-namespace
# 可选：Firecracker 链路
helm install opensandbox manifests/charts/opensandbox --set fast-sandbox.enabled=true
```

**组件资源规格**（官方示例值）：

| 组件 | 开发环境 | 生产环境 |
|---|---|---|
| controller | 200m / 128Mi | 1000m / 512Mi × 3 副本 + podAntiAffinity |
| task-executor | 随 Pool Pod 运行 | root 执行 |
| FastSandbox 链 | — | 6 个 Firecracker 范围镜像（controller/fastlet/fastlet-proxy/janitor/firecracker-runtime/sandboxtemplate-builder），**仅 linux/amd64** |

**FastSandbox 节点要求**：裸金属 KVM（`/dev/kvm`）；firecracker-runtime 就绪循环自动校验宿主机、安装资产、自动打节点标签（无需手工打标）；生产需替换两套密钥（Ed25519 路由密钥 + HMAC-SHA256 路由域环）并预创建 agent 注册 Secret。

**运维面**：
- 先决条件：K8s 1.22.4+、Helm 3.0+；
- 升级/回滚：标准 `helm upgrade` / `helm rollback`；Helm 仅作渲染器，集群不保存 release 状态，`kubectl apply` 幂等；
- 卸载默认保留 CRD，需手动 `kubectl delete crd batchsandboxes... pools... sandboxsnapshots...`；
- 故障排查：controller 日志、`helm get values`、task-executor 的 `/tmp/task-executor.log` 与任务 stdout/stderr 捕获。

### 6.3 运维成本评估

| 项 | 成本 | 说明 |
|---|---|---|
| 控制面 | **低** | Server 是单进程 Python；controller 1 核 512Mi 足够；无消息队列等重依赖 |
| 数据面 | **线性于沙箱数** | 1:1 配比，每沙箱一个容器/Pod；Pool 预热会常驻 bufferMin 个 Pod |
| 强隔离 | **中** | gVisor 每沙箱 ~50MB 内存；Kata FC 仅 ~5MB 但要求 KVM 节点 |
| 运维复杂度 | 单机低 / K8s 中 / FastSandbox 高 | FastSandbox 需裸金属 + 密钥体系 + 6 组件 |
| 版本管理 | 规范 | 伞式发布 OSEP-0016，SDK/镜像/helm 统一 release-X.Y.Z；镜像按 digest 固定 + Cosign 验证 |

---

## 七、Docker Compose 与 K8s 支持

### Docker / Compose 路线

- **官方一等支持的是"Docker 运行时"而非 compose 编排文件**：主分支无 `docker-compose.yml`（404）；单机部署 = pip 装 Server + `[runtime] type="docker"`，Server 直接调 Docker API 管容器；
- Server 配置里有 `[proxy] resolve_internal`（适配 Server 自身跑在 compose/容器网络的场景），提交历史也有 compose 代理修复——**自编 compose 文件跑 `server + egress` 是社区常见做法**，但属自助路线；
- Docker 模式能力边界：支持 gVisor/Kata（Docker 运行时级）、文件挂载（PVC/命名卷/OSSFS）、快照（提交为本地镜像）；**不支持 Firecracker**；
- 网络两模式：Host（共享主机网络，性能优先）/ Bridge（隔离 + 内置 HTTP 路由）。

### Kubernetes 路线

- **生产主推**：base（CRD+RBAC）→ controller → 可选 fast-sandbox 三层 chart；manifests 随 release 标签版本化，支持 GitOps；
- 命名空间规划：`opensandbox-system`（控制面+节点运行时）、`opensandbox-dataplane`（SandboxPool/Template/Sandbox 资源与 fastlet/builder Pods）；
- 与 kubernetes-sigs/agent-sandbox 项目有官方集成示例；
- 池化模式约束：网络策略与 per-request 卷**不能动态注入**已预热的 Pool Pod，必须预建在 Pool 模板（如预挂 RWX PVC）；暂停/恢复仅 replicas=1。

**选型建议**：单机/小团队 → Docker 运行时（+ 自编 compose）；生产集群 → Helm/K8s；极高密度多租户且节点可给 KVM → 加 fast-sandbox。

---

## 八、信创系统与硬件支持

**官方未发布信创认证或适配声明**，以下为基于公开技术事实的可行性分析：

### 8.1 CPU 架构支持矩阵

所有 Go 组件（execd/egress/ingress/controller/task-executor）与 code-interpreter 镜像均通过 buildx 构建 **linux/amd64 + linux/arm64 双架构**：

| 国产 CPU | 架构 | 支持情况 |
|---|---|---|
| 鲲鹏 920 / 飞腾 | aarch64 | **可用**（官方多架构镜像直接覆盖） |
| 海光 / 兆芯 | x86_64 | **可用**（amd64 镜像直接覆盖） |
| 申威 | sw_64 | 不支持（需全链自行移植） |
| 龙芯 | loongarch64 | **不支持**：官方镜像不含 loongarch64，且 gVisor/Kata/Firecracker 上游均不支持 LoongArch，需自行交叉编译 execd 等纯 Go 组件（理论可行）但强隔离层无解 |

### 8.2 操作系统与内核要求

麒麟 / 统信 UOS 均基于 Linux 内核，Docker/containerd 可正常运行。分级要求：

| 能力 | 内核要求 | 说明 |
|---|---|---|
| 基础沙箱（runc + execd） | 较低版本即可 | 最保守路线，国产 OS 基本都满足 |
| bubblewrap 隔离会话 | user namespaces 可用 | 麒麟/UOS 默认满足 |
| Landlock 加固地板 | ≥ 5.13 | 较新内核才支持，需核实国产 OS 内核版本 |
| eBPF 审计 | ≥ 5.10 + BTF | 可选能力，缺失不阻塞 |
| Kata / Firecracker | KVM（`/dev/kvm`） | 鲲鹏/海光有虚拟化扩展可满足；**Firecracker 上游仅认 x86_64/aarch64 KVM** |
| gVisor | systrap 平台不需 KVM | amd64/arm64 均支持——**国产 CPU 上最现实的强隔离选项** |

### 8.3 生态组件

- 镜像源：**阿里云 ACR 国内源（cn-zhangjiakou）开箱可用**，对内网/离线环境友好；Cosign 验签可离线执行；
- 数据库：SQLite 零依赖；PostgreSQL-HA 可对接受控环境常见的 PostgreSQL 系国产库（openGauss/人大金仓为 PG 协议系，理论可对接但未官方验证）；
- 对象存储：MinIO/OSS（快照存储），均可在信创环境部署。

### 8.4 信创结论

| 路线 | 可行性 |
|---|---|
| x86 海光/兆芯 + 麒麟/UOS + runc/gVisor | **高**——amd64 镜像直接跑，gVisor systrap 免 KVM |
| aarch64 鲲鹏/飞腾 + 麒麟 + runc/gVisor/Kata | **高**——arm64 官方镜像覆盖；Kata 需 KVM |
| 任意平台 + Firecracker（FastSandbox） | **低**——镜像仅 amd64 且需裸金属 KVM，信创环境基本排除 |
| 龙芯 | **不可行**（现成链路），仅纯 Go 组件可自行移植且失去强隔离 |
| 信创目录/等保合规 | **无官方声明**，需自行完成适配认证与安全评估 |

**落地建议**：信创环境按 "x86/鲲鹏 + 麒麟 + Docker 运行时 + gVisor(systrap)" 组合推进，规避 Firecracker 链路；上线前重点验证三点——国产 OS 内核版本（Landlock 5.13+）、user namespaces 开启状态、gVisor 与所用 egress 策略模式的兼容性（已知 gVisor 与 iptables REDIRECT 型 egress 不兼容）。

---

## 九、总结与对 bisheng 的建议

### 优势

1. **分层隔离做得最完整的开源实现**：运行时后端 + 安全容器运行时 + 沙箱内 bwrap + 加固地板四层可独立启停；
2. **协议优先**：OpenAPI 契约为单一真相源，五语言 SDK 对齐生成——自研平台可直接照抄这个接口形状；
3. **池化供给体系成熟**：Pool 预热 + bufferMin/Max + 分批扩缩 + 429 背压，是"沙箱即调度单元"的完整工程模板；
4. **凭证管理**：Credential Vault（MITM 注入）+ execd 只收 token 哈希，"凭证不落沙箱"的参考实现；
5. **国内可用性好**：阿里云 ACR 国内源、arm64 官方镜像、中文社区（钉钉群）。

### 局限

1. 不兼容 E2B SDK（自有协议，迁移有成本）；
2. FastSandbox（Firecracker）链路仅 amd64 + 裸金属 KVM，信创环境不可用；
3. 无自动 artifacts 收集（对比 RAGFlow 的 `artifacts/` 约定），产物回传需调用方显式读取；
4. 信创无官方认证，合规需自证；
5. 项目迭代快（版本统一跳变到 1.x+），API 稳定性需按 release 锁定。

### 对 bisheng 3.0 的落地建议

1. **不重复造轮子的选项**：直接集成 OpenSandbox（Docker 模式起步，K8s 模式扩展），bisheng 的沙箱执行器对接其生命周期 API + execd API；或经其 MCP Server 快速验证 PTC 场景；
2. **接口设计对齐其协议形状**：生命周期（create/pause/resume/snapshot/renew/destroy）与执行（/command /code /files）分离的两级 API，控制面不管执行流量；
3. **补齐它没有的**：artifacts 自动收集层（约定目录 + 回传对象存储）；
4. **池化直接照抄**：bufferMin/Max + poolMin/Max + 分批扩缩 + 429 背压五个机制搬过来即可覆盖多数容量场景；
5. **信创交付**：按"x86/鲲鹏 + 麒麟 + runc/gVisor"组合预验证，不上 Firecracker。

---

## 附录：关键文档索引

- README 与架构：仓库根 README.md、docs/architecture/index.md
- 组件文档：docs/components/execd.md、server.md、ingress、egress
- 强隔离指南：docs/guides/secure-container.md（gVisor/Kata/Firecracker 配置）
- K8s 运行时：docs/kubernetes/index.md（BatchSandbox/Pool/SandboxSnapshot CRD）
- Helm 部署：manifests/HELM-DEPLOYMENT.md（charts 结构、资源规格、密钥体系、升级回滚）
- Python SDK：sdks/sandbox/python/README.md（完整 API 与 ConnectionConfig）
- Code Interpreter 示例：docs/examples/code-interpreter.md（含 Pool 化 YAML 全文）
- 沙箱镜像：opensandbox-group/sandbox-images（code-interpreter 镜像，amd64/arm64）
