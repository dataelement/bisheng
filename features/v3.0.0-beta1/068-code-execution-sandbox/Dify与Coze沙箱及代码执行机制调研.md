# Dify 与 Coze 沙箱及代码执行机制调研

> 调研日期：2026-09-17
> 方法：克隆/拉取官方仓库源码逐行核实（dify-sandbox、dify 主仓库 dify-agent / dify-agent-runtime / docker compose、coze-studio）
> 版本基线：dify-sandbox @ 14be466（2026-09-09）、dify-agent-* 1.17.1、coze-studio main 分支

---

## 目录

1. [Dify：两套沙箱与一条 Agent shell 工作区](#一dify两套沙箱与一条-agent-shell-工作区)
2. [Dify：dify-sandbox 代码执行沙箱详解](#二difydify-sandbox-代码执行沙箱详解)
3. [Dify：Agent 的沙箱边界与文件工作区](#三difyagent-的沙箱边界与文件工作区)
4. [Dify：LLM 代码处理工作区文件的完整执行流](#四difyllm-代码处理工作区文件的完整执行流)
5. [Dify：在 local_sandbox 里跑 Python 的安全问题](#五dify在-local_sandbox-里跑-python-的安全问题)
6. [Coze：代码执行沙箱（四层链路）](#六coze代码执行沙箱四层链路)
7. [Coze：代码处理"工作区文件"的执行流](#七coze代码处理工作区文件的执行流)
8. [三方横向对比与选型启示](#八三方横向对比与选型启示)

---

## 一、Dify：两套沙箱与一条 Agent shell 工作区

Dify 实际存在**三条执行链路**，职责完全不同：

| 执行面 | 载体 | 隔离技术 |
|---|---|---|
| Code 节点 / 代码工具（Python / JS / Jinja2） | `dify-sandbox`（独立服务，8194 端口） | chroot + seccomp 白名单 + no_new_privs + UID 池 |
| Agent 的 shell 命令、文件读写、工作区 | `local_sandbox`（shellctl，5004 端口） | **Landlock 路径隔离** + tmux PTY + 网络拓扑隔离 |
| LLM 调用、规划、工具调度、提示词 | `agent_backend` / `api` | **无沙箱**（可信代码） |

核心设计原则：**只有"执行面"在沙箱里，Agent 本体（大脑）不在**。Agent 循环里绝大多数动作（调模型、查知识库、拼提示词）是 Dify 自己的可信代码；真正不可信的只有 LLM 现场生成的代码和 Agent 决定执行的 shell 命令。

两条沙箱线用的技术还不一样：代码执行线用 seccomp，Agent shell 线用 Landlock——因为后者要跑真实 shell，syscall 白名单那套根本不适用。

---

## 二、Dify：dify-sandbox 代码执行沙箱详解

**不用容器、不用 namespace、没有 microVM**——它是一个 Go 服务，把隔离全部压在"被执行进程内部"。Dify 主服务通过 HTTP 调它：`POST /v1/sandbox/run`（`X-Api-Key` 鉴权）。

### 四层进程内隔离

1. **chroot 到最小根目录**（`internal/core/lib/python/add_seccomp.go`）
   - 根目录变为 `/var/sandbox/sandbox-python`，只含 Python stdlib、site-packages、`python.so` 及极少数系统文件
   - 启动时自动发现 sys.path 再复制进去（FAQ 大半篇幅在讲这个兼容坑）

2. **seccomp 白名单，默认动作 kill**（`internal/core/lib/seccomp.go`）
   - 约 60 个白名单 syscall（文件 IO、futex、mmap、时钟、epoll）
   - **没有 `execve`**（子进程隔离代码由 Go 编译成 `python.so`，经 `ctypes.CDLL` 在 Python 进程内部执行——这是全项目最反直觉的设计）
   - `clone/clone3/mkdir` 返回 errno 而非杀进程；网络 syscall 仅在 `enable_network=true` 时追加
   - 未列出的 syscall → `SIGSYS` → 进程直接结束

3. **no_new_privs**：`prctl(PR_SET_NO_NEW_PRIVS)`，setuid 程序位、能力位全部失效

4. **独立 UID 池 + 降权**：池子 10000–11000，每次执行借一个 UID（会往 `/etc/passwd` 追加条目避免 `getpwuid` 撞 seccomp），执行完归还；降权顺序 `Setgroups([])` → `Setgid` → `Setuid`

### 一次执行的链路

Go 服务收到请求 → 借 UID → 生成 bootstrap 脚本（chown 给该 UID）→ `exec.Command(python, bootstrapPath)` 起进程 → **用户代码通过 fd 3 管道传入**（不落盘）→ 子进程加载 `python.so` 完成四层加固 → `exec(compile(code, "<fd3>", "exec"))` → 超时（默认 5s，compose 配 15s）`Process.Kill()` → 归还 UID

### 已知的三个弱点

- **出口代理靠环境变量约定，非强制**：用户代码可直接 `socket.connect()` 绕过 Squid
- **没有资源限额代码**：全仓库搜不到 `setrlimit`，OOM 防护缺位，只有超时
- **并发默认只有 4**（`max_workers`），每次执行付一次解释器冷启动，无池化

---

## 三、Dify：Agent 的沙箱边界与文件工作区

### 服务拓扑（docker-compose.yaml）

- **`agent_backend`**：Agent 本体（Pydantic AI runs + FastAPI），只挂 `default` 网络，无沙箱约束
- **`local_sandbox`**：**刻意不与 `api` 同网**，仅通过 `agent_sandbox_network` 暴露 5004（shellctl）；出站强制走 `agent_ssrf_proxy` 的 Squid
- 执行环境是**可插拔后端**（`dify_agent/runtime_backend/`）：`local.py`（默认）/ `e2b.py`（E2B 云沙箱）/ `enterprise.py` / `openshell.py`，由 `DIFY_AGENT_RUNTIME_BACKEND` 一行切换，Agent 逻辑不改

### 工作区状态模型：Home Snapshot / Binding / Workspace

- **Home（`$HOME`）**：系统空间，装工具和状态，可快照（`/home/dify/.snapshots/home-<id>`）
- **Workspace（`/workspace/<id>`）**：临时工作空间
- **Binding**：`binding_id:workspace_id` 引用。suspend 时快照 `$HOME`；resume 时新 Binding + `cp -a` 物化恢复；destroy 时清理
- Dify API 侧只持久化**不透明的**引用，沙箱凭据/E2B Key 全部留在单次操作内

### shellctl API（Go，`dify-agent-runtime/internal/server/api.go`）

```
POST /v1/jobs/run          # 起 tmux 会话跑脚本（pty 模式）
POST /v1/jobs/{id}/wait    # 等待输出/完成
GET  /v1/jobs/{id}/log/tail
POST /v1/jobs/{id}/input   # stdin（交互式）
POST /v1/jobs/{id}/terminate
POST /v1/snapshot/save | restore
```

Bearer token 鉴权。LLM 侧对应四个工具：`shell_run / shell_wait / shell_input / shell_interrupt`。

### Landlock 配置（`local-sandbox.env.example`）

- 开关 `SHELLCTL_ENABLE_PATH_ISOLATION=true`（默认开）
- 可写：仅 `$HOME`（+ 本 job 的 workspace 路径）
- 只读：`/usr,/bin,/sbin,/lib,/lib64,/etc,/proc,/opt/dify-agent-tools,...`
- 可写设备：`/dev/null,/dev/zero,/dev/urandom,...`

---

## 四、Dify：LLM 代码处理工作区文件的完整执行流

```
① 会话启动 → create_binding：mkdir /workspace/<id> + 从快照 cp -a 物化 $HOME
② LLM 调 shell_run（script 支持 shebang + uv PEP 723 依赖头）
③ POST /v1/jobs/run → Go 服务起 tmux 会话 → Landlock 加固 → 脚本执行
④ 文件访问：cwd 即 workspace，直接 open() 读写
   平台文件：dify-agent file download（CLI）→ agent_stub（可信桥）
   → Dify inner API（强制注入 tenant/user，沙箱不可伪造）→ 签名 /files/*（经 squid）
⑤ 输出：shell_wait 拿 stdout；产物 dify-agent file upload → public_download_url
⑥ suspend → snapshot/save；resume → 新 Binding + restore
```

**关键安全设计——数据面与控制面分离**：沙箱代码不持有平台凭据，每次执行的 JWE token 短期签发（`build_shell_agent_stub_env`），tenant/user 由可信桥注入而非代码自己声明，文件 URI 被限制在签名 `/files/*` 数据面内（`bind_sandbox_file_uri` 校验）。提示注入即使说服了 Agent，拿到的也只是当前上下文的最小凭据。

**对照：Code 节点（dify-sandbox）没有"工作区"概念**——无状态单次执行，入参只有 JSON 变量，文件要以 URL/base64 进参数。要处理工作区文件必须走 Agent shell 线。

---

## 五、Dify：在 local_sandbox 里跑 Python 的安全问题

**Python 怎么跑**：shell 是通道不是限制。镜像预装 python3.12/uv/pip/pnpm，LLM 的 Python 代码以 `python3 -c` / heredoc / uv PEP 723 shebang 脚本（官方 prompt 推荐）三种形态执行，依赖装进 `$HOME/.local`。

**两个关键事实**（源码核实）：

1. **外网是放行的**：`squid-agent.conf.template` 末行 `http_access allow all`，代理只做内网 SSRF 防护（`deny to_private_networks`），不做出站域名白名单——PyPI 装包能通，**数据外传也能通**
2. **Landlock 是路径级不是 syscall 级**：只限制文件读写范围，不限制 fork/exec/网络

### 风险清单

| # | 风险 | 机制 |
|---|---|---|
| R1 | 安装即执行 | `pip install` 的 setup.py / build backend 在沙箱内跑任意代码 |
| R2 | 供应链攻击 | 无 hash pin / 私源强制；包名由 LLM 选，可被提示注入诱导 |
| R3 | 凭据暴露在环境变量 | job env 含 JWE token；prompt 原话警告 env 含密钥；外网放行可直接外传 |
| R4 | **$HOME 快照持久化投毒（最隐蔽）** | `sitecustomize.py` / `.bashrc` / `pip.conf` / uv 配置写入 $HOME → suspend 快照 → 下个会话恢复存活 = 跨会话后门 |
| R5 | 可直调 shellctl | `NO_PROXY=localhost` + env 里的 token，可绕过工具层直调 5004 API |
| R6 | 无资源限额 | compose 无 `mem_limit`/`cpus`，job 级无 setrlimit，fork bomb 可打垮整个容器 |

### 缓解清单（按性价比）

1. 依赖 hash pin + 强制私源镜像（uv `--index-url`）
2. 快照排除配置面（`.config/pip`、`.config/uv`、`.bashrc`、sitecustomize）—— 断 R4
3. 容器级 `mem_limit`/`cpus` + job 级最大生命周期
4. squid 改域名白名单（唯一能同时解决 R2/R3 外传面的手段）
5. 强隔离需求直接切 `DIFY_AGENT_RUNTIME_BACKEND=e2b`（microVM）
6. JWE token 保持短时效（已按单命令粒度设计，不要延长）

---

## 六、Coze：代码执行沙箱（四层链路）

源码：`coze-dev/coze-studio`，`backend/infra/coderunner/impl/{sandbox,direct,script}`。

### 两种 Runner（`CODE_RUNNER_TYPE` 切换）

- **local（默认）/ direct**：直接 `exec.Command(python, "-c", 用户代码)`，源码标注 `// ignore_security_alert RCE`，零隔离。官方 wiki 建议公网部署切到 sandbox。
- **sandbox**：生产模式，四层嵌套：

```
Go 主进程 →(os.Pipe fd3/fd4)→ Python 调度脚本 sandbox.py
  → subprocess → deno run（能力模型）→ jsr:@langchain/pyodide-sandbox（Wasm）
```

| 层 | 职责 | 安全作用 |
|---|---|---|
| ① Go（sandbox/runner.go） | JSON 经管道传子进程 | 不执行代码；JS 明确 not supported yet |
| ② Python（script/sandbox.py） | 组装 Deno 权限参数、超时兜底（默认 60s） | 进程级管理 |
| ③ **Deno**（核心防线） | `--allow-env/read/write/net/run/ffi` | **默认全 false**；read/write 仅 node_modules；net 白名单（如 cdn.jsdelivr.net） |
| ④ Pyodide | CPython 编译成 Wasm，代码在此执行 | 真实 FS/网络/子进程物理不可达 |

资源限制：V8 `--max-old-space-size`（默认 100MB）+ 进程级 timeout。执行前还有静态校验：巨大的 `pythonBuiltinBlacklist`（socket/os/subprocess 等）+ 第三方模块白名单（后台可配）。

**部署形态**：compose 里没有独立沙箱服务，沙箱逻辑跑在 `coze-server` 容器内，零特权要求。本质是**语言运行时级隔离（Wasm + 能力模型）**——与 Dify（chroot+seccomp）、Clawith（bwrap namespace）构成第三种流派。

---

## 七、Coze：代码处理"工作区文件"的执行流

**核心结论：coze-studio 开源版没有"工作区"概念**——backend 全树搜不到 shell/terminal/workspace/持久执行环境实现。代码节点是无状态纯函数：JSON 进 → JSON 出，执行完运行时销毁。

### 流程

1. 用户上传 → upload 域 → MinIO/TOS → `File` 实体 `{id, name, tos_uri, url(签名)}`
2. 文件变量**序列化成 JSON 塞进 Params**——代码拿到的是含 `url` 的 dict，不是文件本体
3. 执行分流：
   - **local（默认）**：网络无限制，`requests.get(url)` 下载可行，但零隔离
   - **sandbox**：默认 `CODE_RUNNER_ALLOW_NET` 仅 `cdn.jsdelivr.net`——**默认配置下连文件 URL 都下载不了**，需加存储域名
4. 结果只能 JSON 返回（文本/base64 字符串），**代码节点不能产生新文件对象**

### 与 Dify 的架构对照

| | Coze：函数式 | Dify：工作区式 |
|---|---|---|
| 文件形态 | 带签名 URL 的 JSON 字段 | cwd 里的真实文件 |
| 代码模型 | 纯函数，单次执行 | shell job，多轮交互、状态保留 |
| 大文件 | 全量过内存 | 流式处理 |
| 依赖 | Pyodide 支持的包子集 | uv/pip 任意装 |
| 产物 | 只能 JSON 返回 | 经 agent_stub 回传真实文件 |
| 状态管理负担 | 零（随便横向扩展） | 有（快照/回收/投毒面） |

注：商业版 Coze（火山引擎）有 IDE/代码解释器与工作区概念，闭源未核实。

---

## 八、三方横向对比与选型启示

### 沙箱技术对比（含前几日调研的 Clawith）

| | Clawith | Dify dify-sandbox | Dify local_sandbox | Coze sandbox |
|---|---|---|---|---|
| 隔离边界 | bwrap namespace | chroot + seccomp 默认 kill | Landlock 路径 + 网络拓扑 | **Wasm + Deno 能力模型** |
| 宿主特权要求 | privileged + SYS_ADMIN | Docker 默认权限 | Docker 默认权限 | **零特权** |
| 默认拒绝粒度 | 文件系统 bind 白名单 + 禁网 | syscall 级 | 路径级 + 代理拓扑 | **能力级（六项逐项授权）** |
| 网络策略 | `--unshare-net` 一键禁网 | enable_network 开关 + 代理约定 | squid 防内网 SSRF（外网放行） | **域名级白名单（原生）** |
| 状态模型 | 会话级长驻 bwrap 进程 | 无状态用完即弃（UID 归还） | 持久工作区 + $HOME 快照 | 无状态 + session_bytes |
| 生态兼容 | 完整 Linux + pip | 大部分 stdlib | 完整（uv/pnpm 任意装） | **最差：Pyodide 包子集** |
| 单次开销 | ~10ms | 几十 ms | shell job 启动开销 | Deno+Pyodide 冷启动较重 |

### 三家的"赌注"

- **Clawith 赌**：外层容器本身是可信边界（代价：宿主容器被削弱为 privileged）
- **Dify 赌**：seccomp 白名单完整（代码线）+ Agent 决策层自律 + 网络拓扑（shell 线）
- **Coze 赌**：Wasm 运行时无逃逸，用生态兼容性换"默认拒绝"的纯度

### 选型启示（面向 bisheng 等平台）

1. **威胁模型先行**：单租户内部 Agent，轻量档位够用；多租户 SaaS 必须独立内核档位（gVisor/Kata/microVM）或云沙箱旁路
2. **"大脑在普通容器、手脚进沙箱"的划分是对的**：只隔离不可信的执行面（生成代码 + shell 命令）
3. **可插拔 runtime backend 是收敛共识**：Dify（local/e2b/enterprise）和 Coze（direct/sandbox）都做成了配置开关，Agent 逻辑不改
4. **数据面与控制面分离**：Dify 的 agent_stub 可信桥（短期 JWE + 强制注入 tenant/user + URI 校验）是文件凭据管理的最佳参考
5. **函数式（Coze）适合轻量数据处理，工作区式（Dify）适合真实文件工作台**——按需求档位选，别用工作区式做简单计算，也别用函数式做文件工程
6. **部署前置条件要做成显式配置**：沙箱的特权要求、网络白名单、资源限额应该在部署清单里一目了然，而不是藏在镜像里
7. **沙箱只是防线的一半**：另一半是资源限额、egress 白名单、依赖来源管控和执行审计

---

## 附：本次调研核实的源码位置索引

**Dify**
- `dify-sandbox/internal/core/lib/{seccomp,syscalls,add_seccomp,set_no_new_privs}.go` — 四层隔离
- `dify-sandbox/internal/static/python_syscall/syscalls_amd64.go` — 白名单三表
- `dify-agent-runtime/internal/server/{api,service,tmux,snapshot}.go` — shellctl
- `dify-agent-runtime/internal/landlock/` — Landlock 隔离
- `dify-agent/src/dify_agent/runtime_backend/{local,e2b,shellctl}.py` — 可插拔后端
- `dify-agent/src/dify_agent/layers/shell/layer.py` — shell 工具层与 prompt
- `dify-agent/src/dify_agent/agent_stub/server/agent_stub_files.py` — 文件可信桥
- `docker/ssrf_proxy/squid-agent.conf.template` — 代理规则（末行 allow all）
- `docker/docker-compose.yaml` — 服务拓扑与网络隔离

**Coze**
- `backend/infra/coderunner/impl/impl.go` — Runner 分流（CODE_RUNNER_TYPE）
- `backend/infra/coderunner/impl/sandbox/runner.go` — Go 层管道通信
- `backend/infra/coderunner/impl/script/sandbox.py` — Deno 权限组装与执行
- `backend/infra/coderunner/impl/direct/runner.go` — 直跑模式（RCE 标注）
- `backend/domain/workflow/internal/nodes/code/code.go` — import 黑白名单
- `backend/domain/upload/entity/file.go` — File 实体（Url 签名链接）
- `docker/docker-compose.yml` — 服务列表（无独立沙箱服务）
