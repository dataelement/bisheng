# Tasks: 代码执行沙箱统一底座（F068）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-20 用户确认 ★；AC-01–AC-28 |
| design.md | ✅ 已评审 | 2026-09-20 用户确认 ★；含实现收口修订 |
| tasks.md | ✅ 已拆解 | 用户已确认审查；29 个任务 / 10 个 Wave |
| 实现 | ✅ 代码 29 / 29 | Wave 1–10；T028 业务 E2E 待 compose 实跑（见实际偏差记录） |

---

## 开发模式

- **后端 Test-First**：测试任务排在配对实现之前；实现任务的「测试」字段写明要转绿的用例。
- **无新表 / 无 Alembic / 无新对外路径**。浏览器与 FastAPI 不直连 runner。错误码模块 **280** 已在 release-contract 登记，落码时回写 constitution C5。
- **自包含**：任务内联文件与逻辑；**为什么这么做指向 design §3 决策编号，不复制论证**。
- **共享文件只做增量**：`load_tools.py` 只改 dispatch；`workbench_impl.py` 只改 `_init_bisheng_code_tool` 的 container 分支（**不要删** E2B `file_list` 预扫，E2B 冻结）；`docker-compose.yml` 只加 `sandbox_net` 与具名 runner；`local_executor.py` 瘦身为 `execute_code`；`settings.py` 只加 `sandbox_conf`。
- **禁止**：`deploy_mode` / `orchestrator` 配置项；runner 向 Redis/API 注册；`else: E2bCodeExecutor`；容器模式装配时预扫 `file_list`；静默回落进程内 `exec`；把 E2B 的 5MB `SIZE_AUTOPUSH` 套到 container。
- **无新 Celery 任务**：执行发生在既有 Linsight / workflow / default worker 进程内，tenant 已由既有 ContextVar 注入；**不得**把 `tenant_id` / MinIO 密钥写进 runner 子进程 env。
- **前端**：只改 Platform 内置工具弹窗；Client 无新页面。
- **Docker / 加固断言**标测试降级（需 compose 实跑），理由见对应任务。

---

## Tasks

### Wave 1 — 基础设施（错误码 / 文案 / 配置）

- [x] **T001**: 错误码模块 280 + constitution C5 回写
  **文件**: `src/backend/bisheng/common/errcode/sandbox.py`, `docs/constitution.md`
  **逻辑**: 新建 `SandboxUnreachableError` 28001、`SandboxCapacityExceededError` 28002、`SandboxExecTimeoutError` 28003、`SandboxCopyInLimitError` 28004、`SandboxCodeNodeOutputError` 28005、`SandboxProtocolError` 28006，继承 `BaseErrorCode`，`Msg` 用英文短句（用户可见文案走 T002）。`constitution.md` 模块登记表补 `28x | 280 sandbox`，并加一句 **280 is assigned**（与 260/270 同款）。`release-contract.md` 已有 280，**不要改表 1 所有权**。无 DDL，无需回滚。
  **设计依据**: design §2 · §4.2 错误码 · C5
  **依赖**: 无

- [x] **T002**: 280 段 `api_errors` 三语文案
  **文件**: `src/frontend/packages/locales/src/api_errors/{en,zh-Hans,ja}.json`
  **逻辑**: 只改 **源文件**，禁止手改 `platform/public/locales/*/api_errors.json` 与 `client/src/locales/*/api_errors.gen.json`。键 `28001`–`28006` 与 T001 语义对齐（不可达 / 容量已满 / 超时且未完成产物不存在 / copy-in 超限已跳过并点名 / 代码节点出参无法序列化 / 执行环境响应不合契约）。三语同一 PR。跑 `pnpm --filter @bisheng/locales check`（或仓库约定的 locales 构建）确认生成物更新。
  **覆盖 AC**: AC-05, AC-16, AC-19, AC-27
  **依赖**: T001

- [x] **T003**: `sandbox_conf` 缺省 / env / 无编排枚举 单测
  **文件**: `src/backend/test/sandbox/test_sandbox_conf.py`
  **逻辑**: 构造 `Settings`：① YAML **无** `sandbox_conf` 段仍能实例化，字段为内置默认（`discover_host_pattern=code-runner-{n}`、`discover_index_start=1`、`discover_ttl_s` 15～30、`pool_lease_ttl_s=900`、`max_sessions_per_replica=1`、`code_node_enabled=True`）。② `BS_SANDBOX_CONF__DISCOVER_HOST_PATTERN` 能覆盖 pattern。③ 模型 **没有** `deploy_mode` / `orchestrator` 字段（赋值应被拒绝或 extra ignore 后读不到）。④ `endpoints` 字段存在且默认空列表（DNS 跳过行为在 T015 测，本任务不 import discover）。⑤ `max_sessions_per_replica>1` 时须有显式 uid 隔离开关，否则校验失败（决策 11/13）。
  **覆盖 AC**: AC-13, AC-21, AC-25
  **依赖**: 无

- [x] **T004**: `Settings.sandbox_conf` + 发布稿注释掉该段
  **文件**: `src/backend/bisheng/core/config/settings.py`, `docker/bisheng/config/config.yaml`
  **逻辑**: 新增 `SandboxConf`（字段见 design §4.2，**不要**加 `deploy_mode`）。`Settings.sandbox_conf: SandboxConf = Field(default_factory=SandboxConf)`。发布 `config.yaml` **整段注释**（坑 9：旧镜像遇未知顶层 key 会起不来）。env 形如 `BS_SANDBOX_CONF__TOKEN`。`token` 不要写进代码常量。
  **设计依据**: design 决策 12 · §4.2 · §5 坑 9、18
  **跨 Feature 影响**: `Settings` 被全平台加载；只加可选段 + 默认值，不得改其它 Conf 的校验。
  **测试**: T003 全绿
  **覆盖 AC**: AC-21, AC-25
  **依赖**: T003

### Wave 2 — 上提 `run_with_dir`（决策 4）

- [x] **T005**: `execute_code` / `run_with_dir` 契约单测
  **文件**: `src/backend/test/sandbox/test_execute_code_contract.py`
  **逻辑**: 用可注入的 `execute_code` 假实现挂在 `BaseExecutor` 子类上。①成功：根级新文件被归位到 `output/`，`file_list` 只含本轮新增/修改，形状 `{exitcode, log, file_list}`。②失败非 0：`file_list` 为空且 stdout 仍在 `log`。③ `sync_to_workspace` 被调用且入参含归位后的 `output/` 路径（monkeypatch 假 backend，不断 MinIO）。④超限文件不在本测（属 copy-in）。本文件 **不** 起真实 runner。现有 `test/linsight/test_code_interpreter_*` 必须在 T006 后仍绿（本任务列出作为回归名单即可）。
  **覆盖 AC**: AC-03, AC-07, AC-08, AC-09
  **依赖**: 无

- [x] **T006**: `run_with_dir` 上提到 `BaseExecutor`，本地只留 `execute_code`
  **文件**: `src/backend/bisheng_langchain/gpts/tools/code_interpreter/base_executor.py`, `src/backend/bisheng_langchain/gpts/tools/code_interpreter/local_executor.py`
  **逻辑**: `BaseExecutor.execute_code` 改为抽象；把 `LocalExecutor.run_with_dir` 的快照 diff / 根级归位 / `upload_minio` / `sync_to_workspace` / `sync_files_to_local` 上提为共享实现。`LocalExecutor.execute_code` 仍是本机 `subprocess`（现有实现可原样上提为实例方法）。`run()` 出口形状不变。禁止在本任务引入 HTTP。
  **设计依据**: design 决策 4 · §4.3
  **跨 Feature 影响**: 本地 / E2B 调用链；E2B **本任务不改** `e2b_executor.py`（冻结）。
  **测试**: T005 全绿；既有 `test_code_interpreter_*` 全绿
  **覆盖 AC**: AC-03, AC-07, AC-08, AC-09
  **依赖**: T005

### Wave 3 — runner HTTP（独立包，不 import `bisheng`）

- [x] **T007**: 租约协议单测（ASGI + httpx）
  **文件**: `src/backend/test/sandbox/conftest.py`, `src/backend/test/sandbox/test_runner_leases.py`
  **逻辑**: `conftest.py` 把仓库 `src/sandbox-runner` 加入 `sys.path`（backend pytest 默认收集不到该独立包）。对 runner 应用（可先对将在 T008 落地的模块做 import，红灯允许）。全局 `token` 才能 `POST /v1/sessions`，成功返回 `session_id` + `lease_token` + `lease_expires_at`。槽满（默认 1）→ 503。错 token → 401。用 A 的 `lease_token` `DELETE` B → 403。`DELETE` 后同 id 再 exec → 404。idle 超过 TTL 视同 DELETE。路径字符串不得包含 `config`。
  **覆盖 AC**: AC-17, AC-27
  **依赖**: T004

- [x] **T008**: runner 租约：`POST /v1/sessions` + `DELETE` + idle 扫描
  **文件**: `src/sandbox-runner/app.py`, `src/sandbox-runner/leases.py`
  **逻辑**: **禁止** `import bisheng`。Starlette/FastAPI 迷你应用监听 8080。内存租约表；默认 `max_sessions_per_replica=1`；工作目录 `/tmp/sessions/<uuid>/`。`GET /health` 200。idle 扫 `pool_lease_ttl_s`。子进程 env **不得**出现全局 token / 任何 lease_token。
  **设计依据**: design 决策 2、11 · §4.5
  **测试**: T007 全绿
  **覆盖 AC**: AC-15, AC-17, AC-27
  **依赖**: T007

- [x] **T009**: tar copy-in/out + zip-slip 单测
  **文件**: `src/backend/test/sandbox/test_runner_files.py`
  **逻辑**: `PUT /v1/sessions/{id}/files` 要该会话 `lease_token`。成员含 `../` 或绝对路径 → 4xx，工作目录外无新文件。md5 命中的路径不覆盖。`GET` 只返回相对执行前快照新增/修改，且 **递归**（`output/sub/a.txt` 必须出现）。超 `max_copy_in_bytes` 的单个成员跳过并在响应/日志点名，其它文件仍写入。
  **覆盖 AC**: AC-07, AC-10
  **依赖**: T008

- [x] **T010**: runner `PUT/GET .../files`（流式 tar.gz + md5 清单）
  **文件**: `src/sandbox-runner/files.py`（在 `app.py` 注册路由，不新开第三文件以外的包）
  **逻辑**: 解包前校验每个成员落在该 UUID 目录内。清单与 tar 二选一旁路（实现选定后写进 design 一行，tasks 不改协议）。不要按文件拆多次 HTTP。copy-in upsert；worker 侧删除本期不从 runner 删。
  **设计依据**: design 决策 3 · §4.2 · §5 坑 12、15
  **测试**: T009 全绿
  **覆盖 AC**: AC-10, AC-17
  **依赖**: T008, T009

- [x] **T011**: exec 超时 / env 白名单 / OOM 回收 单测
  **文件**: `src/backend/test/sandbox/test_runner_exec.py`
  **逻辑**: `POST .../exec` `{code, lang, timeout_s}` → `{exitcode, stdout, stderr, duration_ms}`。超时：进程组被杀，无半成品 copy-out。子进程 env 无 `MINIO`/`MYSQL`/`token`/`lease_token`。模拟 137：租约被 DELETE（半残目录不可复用）。同一 session 两次 exec 串行。`HOME`/`TMPDIR` 指向该 UUID。断言 runner 对子进程设置了内存 / nproc / CPU 的 `setrlimit`（可用 monkeypatch 捕获参数；compose 的 `mem_limit` 在 T026 测）。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17
  **依赖**: T010

- [x] **T012**: runner `POST .../exec` + `killpg` + 异常回收
  **文件**: `src/sandbox-runner/execute.py`（注册到 `app.py`）
  **逻辑**: `start_new_session=True`、超时 `killpg`、`setrlimit`。默认 uid 65534；`max_sessions_per_replica>1` 时走决策 13（独立 uid + 目录 0700 + 父目录 0711 + `/tmp` 0755），否则启动拒绝。可观测：单次 `duration_ms`、exitcode（137 单列）。
  **设计依据**: design 决策 8、11、13 · §4.5 · §5 坑 3、5
  **测试**: T011 全绿
  **覆盖 AC**: AC-13, AC-14, AC-16, AC-17, AC-26
  **依赖**: T011

### Wave 4 — `ContainerExecutor`

- [x] **T013**: `FakeRunnerClient` + `ContainerExecutor` 单测
  **文件**: `src/backend/test/sandbox/test_container_executor.py`, `src/backend/test/sandbox/fake_runner.py`
  **逻辑**: Fake **必须尊重路径参数**（坑 12）。① `endpoints` 非空：跳过 DNS，shuffle 后 `POST /v1/sessions`，503 换下一台，全 503 → 抛 `SandboxCapacityExceededError`（28002），与 28001/超时/协议错误在断言上可区分。② 一台都不可达 → 28001。③ 成功路径出口 `{exitcode, log, file_list}` 与本地模式字段名一致。④ copy-in 在 `run()` 时刻扫描 `dir_path`（含 `skills/`）；超限点名且不静默；记录 copy-in 字节数。⑤ `keep_session=True` 第二次 exec 打同一 URL，不再 discover。⑥ 协议乱响应 → 28006，**不得**调用 `LocalExecutor`。⑦ 超时映射 28003。⑧ `description` 含 design §4.4 库清单中的 `pandas` / `openpyxl` / `python-pptx` / `pymupdf`（与镜像声明对齐，二进制是否真装在 T025）。本任务不写实现文件。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-10, AC-11, AC-26, AC-27
  **依赖**: T001, T006, T012

- [x] **T014**: 实现 `ContainerExecutor`
  **文件**: `src/backend/bisheng_langchain/gpts/tools/code_interpreter/container_executor.py`
  **逻辑**: 只实现 `execute_code` / `close`（领租约、tar、exec、copy-out、finally DELETE 除非 `keep_session`）。产物收割走 T006 共享 `run_with_dir`。`description` 与本地模式库清单对齐且 `path_namespace_rules(include_skills=True)`。错误映射 T001 的 28001–28004、28006。记录 copy-in 字节数。禁止 import docker / kubernetes。**禁止**实现 DNS `discover()`：本任务只消费已注入的 `endpoints`（T013 ①）；主机名展开留给 T016，避免本文件被下一波重写。
  **设计依据**: design 决策 4、5、9、10 · §4.1–§4.2 · §5 坑 1、4、17
  **测试**: T013 全绿
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-05, AC-06, AC-11, AC-26
  **依赖**: T001, T013

### Wave 5 — 副本发现（决策 12）

- [x] **T015**: `discover()` 单测
  **文件**: `src/backend/test/sandbox/test_discover.py`
  **逻辑**: mock `getaddrinfo` / health。pattern `code-runner-{n}`、start=1：1、2 命中，3 NXDOMAIN → 缓存两台 **主机名** URL 不是 IP。K8s pattern `code-runner-{n}.code-runner`、start=0：从 0 扫到 NXDOMAIN。TTL 内不重探。已 bind 的 sticky 实例不 rediscover。`endpoints` 非空完全跳过 DNS。连续连不上即停（不跳号）。
  **覆盖 AC**: AC-01, AC-05
  **依赖**: T004

- [x] **T016**: 实现 `discover()` 并接到 `ContainerExecutor`
  **文件**: `src/backend/bisheng_langchain/gpts/tools/code_interpreter/discover.py`（T014 文件可改为调用它，本任务最多再改 `container_executor.py`）
  **逻辑**: 替换 `{n}`、解析 `host:discover_port`、可选 `GET /health`。缓存 `discover_ttl_s`。无 `deploy_mode` 分支。
  **设计依据**: design 决策 9、12 · §4.5–§4.6 · §5 坑 18
  **测试**: T015 全绿；T013 在注入 `endpoints` 时仍绿
  **覆盖 AC**: AC-01, AC-05
  **依赖**: T014, T015

### Wave 6 — dispatch 与灵思装配

- [x] **T017**: `load_tools` 三分支 + 未知 type 单测
  **文件**: `src/backend/test/sandbox/test_load_tools_dispatch.py`
  **逻辑**: `type=local` → `LocalExecutor`；`container` → `ContainerExecutor`；`e2b` → `E2bCodeExecutor`。未知 `type` **报错**，不得落入 e2b。`config.e2b.type`（private/official）经 `kwargs.update` 不得变成执行器构造参数（坑 7：断言构造 kwargs 无该键）。缺 `type` 时默认 **local**（AC-23：存量 extra 为空的行升级后不得变 container）。另用源码级断言（读文件或 AST，不断真实会话）确认五条路径仍只经 `ToolExecutor.init_by_tool_id(s)`，没有直接 `LocalExecutor(`：`workbench_impl.py`、`chat_service.py`、`assistant_agent.py`、`workflow/nodes/agent/agent.py`、`workflow/nodes/tool/tool.py`。
  **覆盖 AC**: AC-01, AC-02, AC-22, AC-23
  **依赖**: T014

- [x] **T018**: `load_tools._get_native_code_interpreter` 显式三分支
  **文件**: `src/backend/bisheng_langchain/gpts/load_tools.py`
  **逻辑**: 去掉 `else: E2bCodeExecutor`。`container` 读 `config.container`（timeout/profile），池参数 **不** 从 extra 读。切换不需要重启（无模块级全局单例绑死 type）。
  **设计依据**: design 决策 10 · §4.7 · §5 坑 7
  **跨 Feature 影响**: 所有走 `bisheng_code_interpreter` 的路径共用此函数；未知 type 从静默 e2b 变为显式失败。
  **测试**: T017 全绿
  **覆盖 AC**: AC-01, AC-02, AC-22, AC-23
  **依赖**: T017

- [x] **T019**: 灵思 container 绑定单测（不预扫 `file_list`）
  **文件**: `src/backend/test/linsight/test_init_config_tools.py`（增量，不改 E2B 5MB 用例的既有断言）
  **逻辑**: 当工具 `type=container`：`config.container` 含工作区路径 / `keep_session` 语义；**没有**为 container 生成 E2B `file_list`。`path` 规则含 `skills/`。`type=e2b` 的 oversized 过滤用例保持原样（冻结）。
  **覆盖 AC**: AC-06, AC-09, AC-11
  **依赖**: T018

- [x] **T020**: `_init_bisheng_code_tool` 增加 `config.container`，容器模式不预扫
  **文件**: `src/backend/bisheng/linsight/domain/services/workbench_impl.py`
  **逻辑**: `keep_session` / `local_sync_path` / `workspace_prefix` 与本地模式对齐。container **不要** `os.walk` 填 `file_list`（copy-in 在 `run()`，AC-11）。E2B 分支原样保留。
  **设计依据**: design §4.1 路径 1 · §5 坑 4
  **跨 Feature 影响**: 仅灵思工具装配；日常/助手不走此函数。
  **测试**: T019 全绿
  **覆盖 AC**: AC-06, AC-09, AC-11
  **依赖**: T019

### Wave 7 — 工作流代码节点（档 B）

- [x] **T021**: wrapper / `ast.parse` / 28005 / 开关 单测
  **文件**: `src/backend/test/sandbox/test_sandbox_code_parser.py`
  **逻辑**: ①语法错误在 `parse_code()` 阶段抛出，不调 runner。②合法 `main` 经 wrapper 跑 Fake `execute_code`，出参 dict 字段与改造前一致。③返回不可 JSON 序列化 → 28005，不是空 dict。④ `code_node_enabled=False` → 走改造前 `exec_method` 进程内 exec（可用 monkeypatch 断言未 HTTP）。
  **覆盖 AC**: AC-18, AC-19, AC-20, AC-21
  **依赖**: T006, T001

- [x] **T022**: `SandboxCodeParser`：本地 `ast.parse` + wrapper 调同一 `execute_code`
  **文件**: `src/backend/bisheng/workflow/nodes/code/code_parse.py`, `src/backend/bisheng/workflow/nodes/code/code.py`
  **逻辑**: 执行侧不认识 `main`。wrapper：`json.loads` 入参 → 调 `main` → 哨兵行 `json.dumps`。`CodeNode._run` 改调新解析器；`code_node_enabled=False` 回退旧 `exec`。失败禁止回落（开关关闭是唯一回退）。
  **设计依据**: design 决策 8 · §4.1 档 B · §5 坑 8
  **跨 Feature 影响**: 存量工作流出参仍是 dict；不可序列化从静默空值改为 28005。
  **测试**: T021 全绿
  **覆盖 AC**: AC-18, AC-19, AC-20, AC-21
  **依赖**: T021, T014

### Wave 8 — 前端 Platform（工具配置弹窗）

- [x] **T023**: 隔离执行方式三语文案
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/tool.json`
  **逻辑**: 新增 `executionContainerLabel`（及必要 hint：接入参数在系统配置，弹窗不填 endpoint）。禁止硬编码中文。不要借用「副本」「租约」等内部词。三语同一任务。
  **覆盖 AC**: AC-01, AC-22
  **依赖**: 无

- [x] **T024**: `CodeExecutor` 增加 `container` 选项
  **文件**: `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/CodeExecutor.tsx`
  **逻辑**: `RadioGroup` 增加 `value="container"`（非空字符串）。选 container **不**展示 E2B domain/key。submit `type: "container"`，可带 `config.container: { timeout }`，**禁止**把 runner token/URL 写入 extra。保留 local/e2b 原校验。无新 API、不 `import axios`。
  **设计依据**: design §4.2 工具配置 · AC-22
  **覆盖 AC**: AC-01, AC-22
  **手动验证**:
  - 打开管理端构建 → 工具 → 代码执行器，看到三种执行方式
  - 选隔离执行并保存，再打开仍是 container，且 extra 无 endpoint
  - 存量 e2b 配置打开仍显示 e2b
  **依赖**: T023, T018

### Wave 9 — 镜像与 compose（本期交付）

- [x] **T025**: `dataelement/bisheng-sandbox` Dockerfile
  **文件**: `docker/bisheng-sandbox/Dockerfile`（从 `src/backend/base.Dockerfile` 派生，COPY `src/sandbox-runner`）
  **逻辑**: 全量 venv + 完整 LibreOffice/pandoc/fonts-wqy-zenhei + ffmpeg + runner 为 PID 1。不拷 `config.yaml` / `entrypoint.sh` / 平台业务代码。不装 Chromium 浏览器二进制。多架构同一 Dockerfile。
  **设计依据**: design 决策 7 · §4.4
  **覆盖 AC**: AC-04, AC-12, AC-15, AC-28
  **测试降级**: 镜像构建与 office 二进制需 CI/本地 docker，单测无法替代；加固/网络在 T026 手动 + inspect
  **依赖**: T012

- [x] **T026**: compose：具名 `code-runner-1/2` + `sandbox_net` + worker 双挂
  **文件**: `docker/docker-compose.yml`
  **逻辑**: **不用** `deploy.replicas`。`sandbox_net.internal: true`。runner 只挂该网、**无** `ports:`。`backend_worker`（及实际跑灵思的 worker 服务）挂 `default` + `sandbox_net`。加固：`cap_drop: ALL`、`read_only: true`、`mem_limit`（≥2g，坑 5）、`pids_limit`、`security_opt: no-new-privileges`、`tmpfs` `/tmp` `mode=755`、`user: "65534"`。平台容器上 `config.yaml` / `entrypoint.sh` 改为 `:ro`（AC-28）；runner **不挂**这两文件。只增量服务与网络，不改 mysql/redis 口令。
  **设计依据**: design 决策 2、12 · §4.6 · §5 坑 5、6、13
  **跨 Feature 影响**: compose 是全平台启动面；runner 失败不得让 mysql healthcheck 挂掉（runner 不要写进中间件 `depends_on` 链的关键路径，或允许 worker 在 28001 下降级可见而非卡死启动）。
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-28
  **测试降级**: 需 docker compose；用下面手动验证代替 CI 中间件
  **手动验证**:
  - `docker compose up -d` 后 `getent hosts code-runner-1` 在 worker 容器内可解析
  - `docker inspect` 断言 CapDrop / ReadonlyRootfs / Memory / PidsLimit
  - worker 内 `curl -sS http://code-runner-1:8080/health` 200；runner 内连 `mysql:3306` 失败
  - `docker compose exec code-runner-1 env` 无 minio/mysql/hmac
  **依赖**: T025, T016

### Wave 10 — 新装默认、可观测、收口

- [x] **T027**: 新装默认 / 升级不改存量 单测
  **文件**: `src/backend/test/sandbox/test_code_interpreter_seed_default.py`
  **逻辑**: 解析 `t_gpts_tools.json` 中 `tool_key=bisheng_code_interpreter` 的 `extra.type == container`（红灯直到 T029）。读 `init_data.py`（或它调用的预设工具函数）断言对已存在的 `gpts_tools` **没有** `UPDATE extra` / 按 id upsert extra。本任务不改 JSON、不改 `init_data.py`。
  **覆盖 AC**: AC-23, AC-24
  **依赖**: T018

- [x] **T029**: 种子 JSON 写入 `type=container`
  **文件**: `src/backend/bisheng/database/data/t_gpts_tools.json`
  **逻辑**: 仅 `tool_key=bisheng_code_interpreter` 那条 `extra` 增加 `"type": "container"`（AC-24）。**禁止**改 `init_data.py`、禁止给其它内置工具改 extra。
  **设计依据**: design §4.7 · AC-23 / AC-24
  **跨 Feature 影响**: `t_gpts_tools.json` 是全平台内置工具种子；只动代码执行器这一行，其它 `tool_key` 字节级不变。
  **测试**: T027 全绿
  **覆盖 AC**: AC-23, AC-24
  **依赖**: T027

- [x] **T028**: 回归 + 端到端手动验证 + 落档
  **文件**: 本文件「实际偏差记录」段
  **逻辑**: ①重跑 `test/sandbox/`、`test/linsight/test_code_interpreter_*`、`test/linsight/test_init_config_tools.py`、T021。②确认 `e2b_executor.py` 无功能改动（git diff）。③按 design §7：管理端切 container → 日常勾选工具跑一段写 `output/` 的脚本；灵思任务模式技能包可见；代码节点存量 `main` 出参仍进下游。④实现期改变系统认知的偏差回写 design，此处只留一行指针。
  **覆盖 AC**: AC-02, AC-04, AC-12, AC-18, AC-22, AC-26
  **手动验证**:
  - 日常：隔离模式生成含中文的 `output/report.docx`，结果区可下载；附件原件仍不进沙箱
  - 灵思：`skills/` 下脚本可 `open`；sticky 第二轮能读到上一轮 `output/`
  - 代码节点：语法错误仍在搭建/初始化报；运行期不可序列化见 28005
  - 停掉全部 runner → 工具失败为 28001，worker 进程内无用户代码 `exec`
  **依赖**: T020, T022, T024, T026, T029

---

## AC 覆盖对照

| AC | 覆盖任务 |
|----|----------|
| AC-01 | T013, T014, T015, T016, T017, T018, T023, T024 |
| AC-02 | T017, T018, T028 |
| AC-03 | T005, T006, T013, T014 |
| AC-04 | T013, T014, T025, T028 |
| AC-05 | T002, T013, T014, T015, T016 |
| AC-06 | T013, T014, T019, T020 |
| AC-07 | T005, T006, T009 |
| AC-08 | T005, T006 |
| AC-09 | T005, T006, T019, T020 |
| AC-10 | T009, T010, T013 |
| AC-11 | T013, T014, T019, T020 |
| AC-12 | T025, T026, T028 |
| AC-13 | T003, T012, T026 |
| AC-14 | T011, T012, T026 |
| AC-15 | T008, T011, T012, T025 |
| AC-16 | T002, T011, T012 |
| AC-17 | T007, T008, T010, T011, T012 |
| AC-18 | T021, T022, T028 |
| AC-19 | T002, T021, T022 |
| AC-20 | T021, T022 |
| AC-21 | T003, T004, T021, T022 |
| AC-22 | T017, T018, T023, T024, T028 |
| AC-23 | T017, T018, T027, T029 |
| AC-24 | T027, T029 |
| AC-25 | T003, T004 |
| AC-26 | T012, T013, T014, T028 |
| AC-27 | T002, T007, T008, T013 |
| AC-28 | T025, T026 |

---

## 实际偏差记录

> **只留一行指针**，论证写进 design.md（决策 / 坑），这里不重复。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认，再记录。

- 2026-09-20 实现收口：`execute_code` 非 `@abstractmethod`、镜像 `--no-install-project`、runner `SANDBOX_TOKEN`。见 design 修订历史 2026-09-20。T028 业务 E2E（日常 docx / 灵思 sticky / 代码节点 28005 / 停 runner→28001）待 compose 实跑。
