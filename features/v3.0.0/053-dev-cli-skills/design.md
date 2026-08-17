# Design: 开发者 CLI 与技能包（独立 `bisheng` CLI 包 + 平台分发端点）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（55 条有效 AC、边界、12 条决议）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策（含被否决的备选）、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：实现变化 → 覆盖更新本文档、只留"今天的状态"；每个决策保留"为什么 + 被否方案"和坑。推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design。
>
> **代码事实口径**：本文所有 `文件:行号` 按 `3.0-vibe`（含 F048、F049 已落码 `43e73bfc5`、F054 批 2 已落码 `8e9afaf48`）于 2026-08-17 由探查笔记 `~/.claude/jobs/b4f8a315/tmp/f053-notes/e1-cli-packaging-and-endpoints.md` 核实。行号会漂移、符号名不会——**落地前一律以符号名重定位，不要按行号跳**。
>
> **本文是"要建成的样子"**：`src/bisheng-cli/` 是**全新目录**，全仓**零** `[project.scripts]` / `console_scripts` / `setup.py`（e1 §1.1 实测），CLI 是本仓第一个可发布包工程；平台侧 `bisheng/dev_toolkit/` 模块同样是绿地。实现后按现状覆盖本文。
>
> **裁剪基准 = [`mvp-114-path.md`](../mvp-114-path.md) §6 MVP-核心**：本 Feature 本轮只做「CLI 包工程（wheel + 平台下载端点）+ `login` + `deploy` + `logs` 简版」；`skills sync` / 两包技能包 / `dev` / 接入信息区 / 多平台凭据 / 版本兼容校验**全部顺延**（release 仍必做，落点方向见 §1 非目标与 §8）。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)（待写）· [release-contract.md](../release-contract.md)（表 1 **AppManifest 归 F055**、表 3 F053 行；INV-27 / INV-31 / INV-32）· [mvp-114-path.md](../mvp-114-path.md)（**§6 MVP-核心是本轮裁剪基准**、§3 114 环境事实、§1 演示剧本步 2–3）
**上游 / 姊妹**: [F055 design §4.2 ①③ / §4.2 ⑧](../055-app-publish-pipeline/design.md)（`deploy` / `logs` 端点、AppManifest 形态、失败五元组、162 段错误码——**冲突时一律以 F055 为准**）· [F055 tasks T039](../055-app-publish-pipeline/tasks.md)（端点鉴权顺序与归属判定字段）· [F054 contracts-runtime-manager.md §5](../054-app-domain-runtime/contracts-runtime-manager.md)（注入应用的环境变量清单——`bisheng dev` 顺延，但清单来源在此定死）· [F049 design](../049-openapi-auth-baseline/design.md)（`whoami` / `open_api_subject` / 260 段错误码）
**版本**: v3.0.0
**最后更新**: 2026-08-17

---

## 1. 目标与非目标

**目标**：交付一个**与后端零耦合的独立 Python 包 `bisheng-cli`**（命令名 `bisheng`），让开发者与其本地 coding agent 在纯内网环境里用三条命令完成「拿密钥登录 → 把本地项目打包发布上平台 → 看自己应用的运行日志」；同时在平台侧提供**匿名可达的安装件与版本信息分发端点**，使 CLI 的获取与升级不依赖任何公网 registry。CLI 自身**不做任何权威判定**——密钥有效性、权限位、manifest 合法性、包体上限、归属人、审批状态全部由服务端裁决，CLI 只负责「打包、送达、把服务端的机读结论翻成人话与退出码」。

**非目标**（本轮顺延，落点方向已定，避免后人误扩或另起一套）：

| 顺延项 | 为什么本轮不做 | 将来的落点方向 |
|---|---|---|
| `skills sync` 与 DEV-03 两包技能包 | MVP-核心不集成平台能力，技能包的一半内容（模型 / 检索 / SDK 接线）无处可教 | 端点 `GET /api/v1/dev-toolkit/skills/{pack}`（与安装件同 router、同匿名口径，D10 已留位）；包内容随后端发布件同行，落点同 `linsight/builtin_skills/` |
| `dev` 命令（迷你代理 + 本地 SQLite） | 依赖 F054 app-proxy 的注入头形态与 F057 SDK，两者本轮都不在纵切上 | 命令落 `bisheng_cli/commands/dev.py`；**注入的环境变量清单不得自造**，唯一来源 = [`contracts-runtime-manager.md` §5](../054-app-domain-runtime/contracts-runtime-manager.md)（见 §6.2 表末行，本文已把清单原样登记） |
| 接入信息区（platform 前端） | 属 platform UI，与 CLI 包工程无耦合；MVP-核心的密钥转交靠人工 | F049 服务账号详情页「API 密钥」tab 顶部；下载链接即 D10 的 `download_url` |
| 多平台凭据（`--platform` 参数、profile 切换与列出） | 114 只有一个平台；裁剪基准 `mvp-114-path.md` §6 F053 行把「多平台凭据」整条列在顺延列 | **凭据文件结构本轮就按多 profile 落**（D3，零迁移地基），但 **`--platform` 参数本轮不注册**——命令一律用 `credentials.json` 的 `current` profile。顺延的是整个「命令级选择 + 列出 + 切换」交互层（D11 第 5 条） |
| 版本兼容校验（不兼容即阻断） | 平台侧 `versions` 端点本轮就返回 `min_compatible`，但阻断逻辑需要真实的跨版本样本才有意义 | 本轮**只提示不阻断**（D11）；开启阻断 = 在 `http.py` 的前置探测里把 warning 升为 `CliError(exit=2)` |
| 单文件二进制安装件 | spec 决议-1 定为 v3.1 备选 | 下载端点按 `?platform=&arch=` 分发，`versions` 载荷加 `assets[]` 数组 |
| CLI 侧密钥扫描、`init` / 工程骨架、`--as`、`logout` / `whoami` 子命令、撤回命令、二维码 | spec §范围边界与决议-2 / 决议-12 已逐条否决 | **不做**（§8 有理由，防止后人重复提议） |

**与裁剪基准的两处显式偏离（本轮刻意扩范围，非漏读）**：

| 偏离项 | 基准怎么写的 | 本轮为什么仍做 |
|---|---|---|
| **`login` 拒 `delegate`** | `mvp-114-path.md` §6 MVP-核心表 F053 行把「`login` 拒 `delegate`」列在**顺延**列 | INV-31 要求「三面在通道入口按权限位直接拒绝」，而 CLI 是唯一的通道入口；实现量 = `whoami.scopes` 一个 `in` 判断 + 一条文案 + 一个 mock 单测（D14 / 坑 15），**不做反而要在 spec 里挂一条长期偏离**。⚠️ 该位在 F049 期签不出来（坑 15），本轮**只能单测覆盖、不可在 114 端到端验证** |
| **`--confirm-schema-change` 参数** | 结构演进整体后置（F055 §6 波次表） | 参数存在与否是 CLI 的**对外契约**；现在不做，将来要改 CLI + README 两处（D11 第 4 条；F055 端点参数同理由留位，本期只接受不消费） |

---

## 2. 关键约束

> 全局架构铁律（双 DB / 多租户 / 权限 / 分层 / 错误码 / 安全）遵循 [`docs/constitution.md`](../../../docs/constitution.md) C1–C7，本节不重抄。**注意作用域**：C1–C7 与 `scripts/arch-guard.sh` 约束的是 `src/backend/`，本 Feature 只有**平台侧两个端点**落在那里；`src/bisheng-cli/` 是独立工程，唯一会对它出声的自动守卫是 RULE-7，**且它只输出 WARNING、不是 VIOLATION、不阻断**（`arch-guard.sh:99` 输出 `⚠️ [arch-guard] RULE-7 WARNING`，脚本头注释 `:13` 标「硬编码敏感信息检测（C6，**WARNING**）」；VIOLATION 只有 RULE-4/5/8/9/10）——见坑 10。

- **CON-1 CLI 是独立包，不 import `bisheng`**：不读后端配置、不连任何数据库、不引 SQLModel / FastAPI。推论：**一切权威校验恒在服务端**——CLI 对 `bisheng-app.yaml` 只做「文件存在 + YAML 可解析 + 三个必填项存在」级快速失败（F055 design §D3 逐字要求），对权限位一律不判、不缓存（AC-52）。
- **CON-2 纯内网零公网依赖**：安装件与版本信息由平台自身分发（AC-01）；CLI 运行期只访问 `login` 时给定的**那一个 host**，不做遥测、不查公网 registry、不下载任何东西。推论：**第三方依赖是负债**——每多一条依赖就多一次「内网 pip 装不上」的失败面（依赖预算见 D12）。
- **CON-3 凭据是本地用户资产**：落用户目录、属主可读写、绝不落工程目录、绝不进上传包（AC-07 / AC-32）。密钥**必须以明文保存**（每次请求都要用它），文件权限位是唯一保护——这不是可以省的一步（坑 1）。
- **CON-4 包体量上限来自服务端配置，不是 CLI 常量**：默认 50 MB / 200 MB 解包 / 20000 条目，权威值经 `GET /api/v2/apps/deploy-limits` 取；**取不到时直接上传、由服务端 16201 兜底**，不得让一个软校验挡死发布（F055 design D2 / tasks T050 回写项 3）。
- **CON-5 与 F055 服务端契约强耦合——契约变则 CLI 变**：端点路径与入参、轮询载荷字段、`stage` 取值与顺序、失败五元组 `{stage,code,message,details,hints[]}`、162 段错误码语义，五样任一变更都必须同批改 CLI。本文 §4.2 的所有形状是 F055 design §4.2 ①③⑧ 的**副本**，**冲突时一律以 F055 为准**（同一契约分两处必漂移，这是自觉付的代价，靠 §6.2 的显式登记 + tasks 的同批改任务对冲）。
- **CON-6 跨平台 + Python ≥ 3.11**：Windows / macOS / Linux 三端可跑（坑 4 / 坑 5）；`requires-python = ">=3.11"` 与 `src/runtime-manager/pyproject.toml:1-16` 对齐。
- **CON-7 商业版网关只转发 `/api/v1/**` 与 `/api/v2/**`**（`docs/architecture/11-gateway.md:36-37`；OSS nginx `docker/nginx/conf.d/default.conf:50` 同形）→ 分发端点的落点没有选择余地（D10）。
- **CON-8 F053 不申请错误码模块编码段**：`login` 消费 F049 的 260 段、`deploy` / `logs` 消费 F055 的 162 段与 F054 的 161 段；分发端点在开关关闭时**靠不注册路由呈 404**（D10），零新错误码 → C5 的「新增错误码须同批回写 constitution 表」在本 Feature 不触发。
- **CON-9 MVP-核心边界**：只做 `login` / `deploy` / `logs`。顺延命令**不注册进解析器**（D11），不做"占位报错"。

---

## 3. 方案对比与选定

### D1：包工程形态 = Python wheel + 平台下载端点；发行名 / 包名 / 命令名三分离

- **备选**：
  - A. **单文件二进制**（PyInstaller / Nuitka）— 优点：开发者机器零 Python 依赖；缺点：三平台各打一份、体量 30 MB+、信创国产 CPU（龙芯 / 鲲鹏）要再加两个构建目标，且仓内零构建先例
  - B. **仅推私有 PyPI 镜像**（组织内确有 Nexus：`.github/workflows/test.yml:55-66` 的 `PY_NEXUS: 110.16.193.170:50083`）— 缺点：那段是 backend 换 uv 前的**过期残留**、不是可依赖的发布通道；且客户现场的内网镜像不归我们控制，AC-01「平台自身分发」落不了
  - C. **wheel + 平台自身的下载端点**（选定），私有镜像作为**可选**加速路径
- **选定**：**C**（spec 决议-1 已定案，本文只补落地形状）。
- **原因**：目标用户是"会用 coding agent 的业务技术员"，Python 环境常备；wheel 是唯一能同时满足「一份产物 × 三平台」「可直接 `pip install <url>`」「可放进内网镜像」的形态；`src/runtime-manager/pyproject.toml`（hatchling + uv.lock，`:25-30`）是仓内最新的独立包先例，照抄可省掉一轮工具链选型。
- **落地形状**（照抄基准 = `src/runtime-manager/pyproject.toml`）：
  - `[build-system]` hatchling；`[tool.hatch.build.targets.wheel] packages = ["bisheng_cli"]` —— **这一行是关键**：目录名带连字符（`src/bisheng-cli/`）时 hatchling 无法自动推断包目录，缺了它 `uv build` 打出的 wheel 是空的。
  - `[tool.ruff]` 照抄 `:41-67`，**`RUF001/002/003` 必须 ignore**——CLI 的人读输出全是中文，不 ignore 的话 ruff 会把中文全角括号"修"成 ASCII，把产品文案改错。
  - `[tool.pytest.ini_options]` 照抄 `:32-39`，自定义 marker 由 `docker:` 换成 **`network:`**（需要真平台的用例默认跳过，CI 不跑、114 手验跑）。
- **三个名字刻意分离**：发行名 `bisheng-cli` · **import 包名 `bisheng_cli`** · 命令名 `bisheng`。理由有两条且都不是洁癖：① 若 import 包取名 `bisheng`，开发者机器上同时装了后端依赖时会与 `src/backend/bisheng/` 顶层包**同名冲突**；② `arch-guard.sh:115,126` 的 RULE-8/9 守卫条件是 `grep -q "/bisheng/"`，目录里出现 `bisheng/` 段会被扫进来产生无谓噪声。
- **何时该重新考虑**：客户反馈"装不上 Python"成为主要阻碍（表现：现场支持工单里安装类占比过半）→ 补单文件二进制，`versions` 端点改按 `platform/arch` 分发 `assets[]`（形状 §4.2 已留位）。

### D2：命令与参数面 = argparse 三命令 + 全局 `--json`（机读走 stdout、人读走 stderr）

- **备选**：
  - A. **typer / click**（生态标配）— 优点：子命令、类型转换、`--help` 全自动；缺点：多一条内网安装链（typer 还带 rich + click 两个传递依赖），违反 CON-2 的依赖预算
  - B. **标准库 `argparse` + 手写 `--help` 文案**（选定）
  - C. 自己写解析器 — 无收益，`--help` 与错误提示要重造
- **选定**：**B**。`argparse` 在标准库、支持子命令与互斥组、`--help` 自动生成，唯一损失是彩色输出与自动补全——两者都不是 AC 要求的（AC-04 要求的是"非交互可用 + 机器可读"，与好看无关）。
- **机读 / 人读双形态的落地（AC-04 的实质）**：
  - **`--json` 时：机读 NDJSON 走 stdout，人读文本走 stderr**。这样 agent 可以直接 `bisheng deploy --wait --json | jq -c 'select(.event=="stage")'` 而不被进度文本污染，同时人在终端仍能看到过程。反过来（把两者混在 stdout 靠标记区分）会让任何一个 jq 管道在第一行进度文本上炸掉。
  - 事件形状固定三种：`{"event":"stage",...}` / `{"event":"progress",...}` / `{"event":"result","ok":bool,"exit_code":int,...}`；**每条命令恒以且仅以一条 `result` 结尾**（agent 可以只读最后一行做判定）。
  - 非 TTY 自动降级：不打进度条、不发交互提问，只打里程碑（25/50/75/100%）。
- **交互确认一律有参数等价物**（AC-04）：`--confirm-schema-change`（AC-36）· `--yes`（迭代 deploy 前的目标应用确认）· `--api-key-stdin`（免命令行明文，AC-07）。**非交互环境下缺参数 = 明确拒绝**，绝不"默认同意"。
- **`--wait` 的定位**：默认不等（审批是人工动作、可跨天，spec 决议-10）；`--wait` 是纵切演示剧本的等待手段，带 `--wait-timeout`（默认 1800 秒），**超时不是失败**（退出码 23，见 §4.2 退出码表）。
- **何时该重新考虑**：命令数超过 5 个且开始出现多层子命令（如 `bisheng app logs`）→ 那时 argparse 的手写 `--help` 维护成本会超过一条依赖的成本，可换 typer；或需要 shell 补全成为客户诉求 → 同上。

### D3：凭据存储 = `~/.bisheng/credentials.json`，`0600` + 多 profile 结构本轮就落

- **备选**：
  - A. **系统钥匙串**（keyring / DPAPI / Keychain）— 优点：最安全；缺点：`keyring` 是第三方依赖且在无 GUI 的 Linux 上要 D-Bus + secretstorage，服务器 / 容器里必炸，与"开发者可能在跳板机上用"直接冲突
  - B. **环境变量**（每次命令都要 `BISHENG_API_KEY=...`）— 缺点：AC-06 明写"通过后把凭据写入本地用户目录"；且 agent 反复拼环境变量比读文件更易泄漏到 shell history
  - C. **用户目录下的 `0600` JSON 文件**（选定），环境变量作为**覆盖**通道保留
- **选定**：**C**。路径 `~/.bisheng/credentials.json`（目录 `0700`、文件 `0600`）；Windows 上 `%USERPROFILE%\.bisheng\`，用 `icacls` 等价的"仅当前用户"ACL（坑 1）。
- **原因**：形态与开发者熟悉的 `~/.docker/config.json`、`~/.kube/config`、`~/.aws/credentials` 一致，学习成本为零；纯标准库可实现；跳板机 / 容器 / WSL 全部可用。**密钥必然明文存**（每次请求都要原值），所以权限位不是"加固"而是**唯一**保护——写文件必须 `os.open(path, O_CREAT|O_WRONLY|O_TRUNC, 0o600)` 一步到位，不能"先 write 再 chmod"（那中间有一个 world-readable 的窗口）。
- **多 profile 结构本轮就落**（顺延的只是交互层）：文件顶层 `{"version":1,"current":<base_url>,"profiles":{<base_url>: {...}}}`。理由：结构一旦按单平台写死（顶层直接放 `api_key`），加多平台就是一次带迁移的破坏性变更；按 profile 落只多写十行，而顺延项开启时零迁移。
- **不存 `scopes`**（AC-52 的直接落点）：服务端有 3 秒正向缓存上界（`core/config/open_platform.py:31-35`，默认 3、硬顶 5），权限位编辑"即时生效"由服务端保证；CLI 一旦缓存权限位就会出现"管理员补勾了但 CLI 还说没权限"。存的是 `service_account` / `resource_owner` / `key_mask` / `tenant_id` 这类**展示用快照**，且每次 `login` 覆盖。
- **何时该重新考虑**：出现"密钥被同机其他用户窃取"的真实事件（表现：审计里同一把 key 出现不同来源）→ 上系统钥匙串，但必须保留文件后端作为无 GUI 环境的回落，而不是替换。

### D4：打包 = `tar.gz` + 三层忽略规则（git 优先 / 自研子集回落 / `.bishengignore` 收口）

- **备选（包格式）**：zip vs **tar.gz**（选定）。runtime-manager 的解包端两种都收（`src/runtime-manager/runtime_manager/builder.py:168-181`，先 `zipfile.is_zipfile()` 再 `tarfile.open()`），但 F055 端点参数逐字写的是 `package`（tar.gz）、对象键是 `apps/{app_id}/versions/{version_id}/code.tar.gz`（F055 design `:103`）→ **产 zip 等于和字面契约、对象键名、未来分片方案三处同时错位**，没有任何收益。
- **备选（忽略规则）**：
  - A. **`fnmatch` 硬顶 gitignore 语义** — **绝对不要**：`fnmatch` 的 `*` 跨 `/` 匹配、且**根本没有 `**`**（`linsight/domain/services/workspace_backend.py:616-619` 的注释逐字记录了这两个坑）。这个坑在本仓已经真实咬过一次（memory `project_taskmode_selftest_114_glob_bug`：提示词逐字教的 `glob("/uploads/**/*.xlsx")` 一直 0 匹配）
  - B. **加 `pathspec` 依赖**（gitignore 语义的事实标准库，纯 Python）— 缺点：一条内网安装链换一个只在"非 git 项目"才用得上的完备性
  - C. **三层规则**（选定）
- **选定**：**C**，三层从内到外：
  1. **结构性排除**（与忽略文件无关，恒定生效）。分两类：
     - **硬排除、不可取回**：`.git/` `.hg/` `.svn/` `node_modules/` `.venv/` `venv/` `env/` `__pycache__/` `*.pyc` `.pytest_cache/` `.ruff_cache/` `.mypy_cache/` `*.egg-info/` `.DS_Store` `.bisheng/`。判据：**这些目录的内容在目标机器上一定是错的或无意义的**（宿主平台的虚拟环境 / 二进制、版本控制元数据、缓存），上传它们只有害处。
     - **软排除、可被 `.bishengignore` 的 `!` 取回**：`*.db` `*.sqlite` `*.sqlite3`、本地附件目录、**`dist/` `build/`**。
     - ⚠️ **`dist/` / `build/` 刻意不进硬排除**（评审修订）：存量 python3.11 应用把前端构建产物放 `dist/` 交后端静态托管是常见形态，硬排会把它静默剥掉，故障要到 `precheck_probe` / 16228 才暴露、且排查方向指向"平台构建有问题"（正是坑 20 那类误导）。这与本节第一条硬规矩「绝不静默截断——包被悄悄截断 = 线上跑的不是本地那份」（判据照 `linsight/domain/services/workbench_impl.py:1255-1257`）是同一条约束的两面：**凡"真实应用可能需要它"的目录，一律软排 + 在忽略统计里列出**，只有"上传必然错"的才硬排。
     - **凭据文件天然不在工程目录（D3），"不进包"由结构性排除 + 一条 assert 型单测双重保证**（AC-07）。
  2. **`.gitignore` 语义**：项目是 git 仓库且 `git` 可执行 → 直接 `git ls-files -c -o --exclude-standard -z` 让 git 自己算（零依赖、100% 语义一致；关联 memory `reference_remote_dev`「要比就用 `git ls-files` 全量」的正向用法）；否则 → 自研子集解析器（`#` 注释 / 空行 / 前导 `!` 取反 / 目录后缀 `/` / `**` / 段内 `*` `?`），并**在输出里明说**"本项目非 git 仓库，忽略规则按子集解析，复杂规则请写进 `.bishengignore`"。
  3. **`.bishengignore`**（可选，同语法、最后加载、优先级最高）——子集解析器兜不住的复杂规则的显式出口。
- **打包的四条硬规矩**（每条都是坑的对偶）：
  - **绝不静默截断**：超限 / 遇到不可打包成员时**整包拒绝**并列清单，判据注释照抄 `linsight/domain/services/workbench_impl.py:1255-1257`——"包被悄悄截断 = 线上跑的不是本地那份"。
  - **符号链接 / 设备文件 / FIFO / socket 本地就跳过并列出**：服务端 tar 解包闸会拒它们（F055 design D2 的四类拒绝），本地不跳等于必然吃一个 16202。
  - **⚠️ 硬链接不在跳过之列（2026-08-17 订正，原文写的「硬链接一律跳过」是错的）**：服务端拒的是 tar 里的 **hardlink 成员**，而 hardlink 成员只在 tarfile 自己挑成员类型时才产生（`TarFile.add` / `gettarinfo` 查 `self.inodes`）。`packaging.py` 逐条手工构造 `TarInfo`（默认 `REGTYPE`）再 `addfile` 流式写内容，**这条写入路径产不出 hardlink 成员**。按 `st_nlink > 1` 跳过，等于为一个不会发生的成员类型丢掉一个普通文件的内容——而 `st_nlink > 1` 既不是作者选的、他也看不见。→ 硬链接文件按普通文件打包，内容照进。
  - **可复现打包**：成员按路径排序、`mtime` 归一、`uid=gid=0`、`uname=gname=""`、路径用 posix 分隔符且无前导 `./`——同样内容产出同样 sha256，便于"本地包 == 服务端收到的包"的核验。
  - **保留可执行位**：文件模式归一为 `0644`，**但原本有 owner 执行位的保留 `0755`**——否则 entrypoint 脚本上线后不可执行，而这类故障要到构建/探活阶段才暴露（坑 20）。
- **体量自查**：打包后先 `GET /api/v2/apps/deploy-limits`（`{max_package_mb, max_unpacked_mb, max_package_entries}`），超限 → 拒绝 + 打印当前体量 + **Top 10 最大文件 / 目录**（"忽略建议"不能是一句空话，要指名道姓）；端点取不到 → **按内置默认值只提示不拦、直接上传**，由服务端 16201 兜底。
- **何时该重新考虑**：真实项目频繁顶穿 50 MB 且 `.gitignore` 已清干净 → 运维改 `settings.app_runtime.max_package_mb`（这是运维动作不是改码）；或子集解析器被投诉误伤（表现：同一个项目 `git ls-files` 与子集解析结果差异 > 5%）→ 那时才值得引 `pathspec`。

### D5：上传 = 一次性 multipart POST（流式读文件），不做分片

- **备选**：
  - A. **分片 + 断点续传** — 缺点：需要服务端两段式 `init + parts + complete`（F055 design D2 明写"那时接收端点要改成两段式"），本轮 F055 端点是单次 multipart；50 MB 上限下分片是纯粹的过度设计
  - B. **一次性 multipart POST**（选定）
- **选定**：**B**。`httpx.post(url, files={"package": (name, fileobj, "application/gzip")}, data={"app_id":..., "confirm_schema_change":...})`——**传 file object 而不是 `path.read_bytes()`**，httpx 会流式读、`Content-Length` 由文件大小得出，50 MB 不进内存。
- **原因**：nginx `client_max_body_size 1024m`（`docker/nginx/conf.d/default.conf:60`）远高于 50 MB 上限，**无需改 nginx**；服务端侧 F055 也已明确 `UploadFile` 落临时盘再 `put_object(file=Path(...))`、不整包进内存——两端都不放大内存，分片的唯一理由（大对象）不存在。
- **超时取值**：连接 10 s；**上传请求读超时 240 s**（刻意 < nginx `proxy_read_timeout 300s`，`default.conf:53`），让 CLI 自己先超时并给出可读信息，而不是拿到一个被 nginx 掐断的 504；普通请求读超时 60 s。
- **进度**：人读模式用计数包装器打印 `已上传 12.3 MB / 41.0 MB (30%)`；`--json` 模式只在里程碑发 `{"event":"progress"}`，不刷屏。
- **何时该重新考虑**：包体上限被放宽到 > 200 MB，或出现跨机房上传的真实丢包 → 那时同时改 F055 端点与 CLI（两处必须同批，登记在 §6.2）。

### D6：`deploy` 的分阶段输出 = 服务端 `stage` 直投，CLI 不自造阶段名

- **备选**：
  - A. CLI 自定义一套面向人的阶段名（"正在检查配置 / 正在构建镜像"）并映射服务端 `stage` — 缺点：映射表就是第二份契约，F055 加一个 stage 就出现"CLI 不认识的阶段"，且 agent 拿不到机读值
  - B. **服务端 `stage` 原样作为机读值 + 一张纯展示用的中文短语表**（选定）
- **选定**：**B**。`--json` 里 `stage` 恒为服务端原值，`STAGE_LABELS` 是一张**纯展示用**的中文短语表，**遇到未知 stage 就原样打印英文**（不认识 ≠ 报错）。
- **`stage` 的权威枚举照抄 F055，一个不能少**（`055-app-publish-pipeline/design.md:86` 逐字定义）：

  ```
  received · secret_scan · precheck_manifest · precheck_build · precheck_probe
  · version_recorded · approval_created · approved · publishing · online · pending_online
  ```
  `status ∈ {running, waiting_approval, succeeded, failed}`（同处）。⚠️ **`approval_created` 是机读值，不要写成中文「审批单生成」**——那是 `STAGE_LABELS` 里的展示串，混淆会让 `--json` 的 `stage` 字段与服务端对不上；同样，**第一条轮询响应的 `stage` 就是 `received`**，漏登记它会让每次 deploy 的第一行输出都掉进"未知 stage"兜底分支。
- **⚠️ 同步段的 stage 客户端永远轮询不到**（本节最容易写错的地方，与 §4.1 B 步 6/7 同源）：F055 design §4.1 ①（`055-app-publish-pipeline/design.md:411-427`）把**归属判定 · 大小闸 · 解包闸 · manifest 校验 · 本地引用校验 · 在途单 / 待上线闸**全部放在 `POST /api/v2/apps/deploy` 的**同步前段**，端点直到这些都过了才 `INSERT app_deployment(stage=received)` 并返回 `{deployment_id}`。→ **`precheck_manifest` 的失败根本不会出现在轮询里**，它是 `POST` 的**同步错误响应**；轮询里能看到的只有 `received` 之后的阶段。CLI 若"等一个 `stage=precheck_manifest` 的失败事件"，等到的是超时——而首发最常见的失败（manifest 缺字段）恰好全在这一侧。
- **顺序不得擅自调换**：异步段顺序 `secret_scan → precheck_build → precheck_probe → version_recorded → approval_created`（阶段名以 F055 为准；spec AC-31a 的人话顺序「托管预检 → 安全扫描 → 审批单」是同一条链路的产品级表述）。⚠️ **F055 design D5 里挂着一个"把 `secret_scan` 提前到构建之前"的待 ★ 确认偏离**——若那条被确认，**CLI 的输出顺序、`STAGE_LABELS` 与 AC-31a 必须同批改**（§6.2 已登记）。
- **失败即终止 + 五元组原样透传**（AC-31a / AC-35）：任一阶段 `status=failed` → 立即停止轮询、按 `failure.code` 映射退出码、人读打印 `message` + `hints[]` 逐条、机读把整个 `{stage,code,message,details,hints[]}` **原样**放进 `result.failure`。**CLI 绝不吞 `details` / `hints`**——那是本地 agent 自动修复的全部输入（AC-47 的成立前提）。
- **密钥扫描命中的呈现**：`hits: [{rule_id, name_i18n_key, file, line}]` 逐条打印 `file:line` + 规则名，**绝不回显任何值**（服务端连脱敏值都不给，F055 design D5）。CLI 也不得"贴心地"去本地文件里把那一行读出来打印——那等于把服务端刻意不给的东西自己补回来（AC-04 / AC-35 红线）。
- **何时该重新考虑**：阶段数超过 8 个或出现分支（如 `runtime=static` 跳过构建）→ 线性进度条要换成阶段树；或 F055 把 `failure` 拆成 machine/human 两个字段 → 那时 CLI 的透传逻辑要改（但应先反对那个拆分，理由见 F055 design D4）。

### D7：审批状态轮询 = 短轮询 + 指数退避，终态一态一退出码（AC-31c 的四终态 + 两个必须收口的异常终态）

- **备选**：
  - A. **长连接 / SSE** — **物理上不可行**：nginx `proxy_read_timeout 300s`（`default.conf:53`），而审批是人工动作可跨天
  - B. **WebSocket** — 服务端无此接口，且要为一个 CLI 建长连接通道
  - C. **短轮询 `GET /api/v2/apps/deployments/{deployment_id}` + 指数退避**（选定）
- **选定**：**C**。间隔 2 s 起，每 5 次 ×1.5 封顶 10 s；`--wait-timeout` 默认 1800 s。
- **两段轮询语义要分开**（这是最容易写错的地方）：
  - **默认（无 `--wait`）**：轮询到 **`status=waiting_approval`（审批单已生成）** 即返回 0，输出审批单标识与三条跟踪路径（应用详情页·发布 / MCP 应用状态工具 / `deploy --wait`）——spec 决议-10。
  - **`--wait`**：继续轮到 `approval.status` 终态与 `app_state` / `pending_reason` 落定。终态映射（AC-31c 要求的四种 + 两种**必须收口否则会卡死**的异常终态）：

    | 终态 | 判据（轮询载荷） | 退出码 | 输出 |
    |---|---|---|---|
    | 通过并上线 | `app_state=已上线`（`stage=online`） | **0** | 应用标识 + 入口地址；**⚠️ 入口地址不在轮询载荷里**，见下方"entry_url 的取值缺口" |
    | 待上线 | `pending_reason ∈ {"capacity","deploy_failed"}`（`stage=pending_online`） | **22** | 成因 + owner 手动上线路径（应用详情页·发布） |
    | 驳回 | `approval.status=rejected` | **20** | `reject_reason` **全文**（不截断） |
    | 撤回 | `approval.status=withdrawn` | **21** | 提示撤回发生在应用详情页·发布 |
    | **取消（应用被删除）** | `approval.status=cancelled` | **24** | 明说"目标应用已被删除，该审批单已取消"——**这单永远不会有结论** |
    | **审批异常（审批人为空）** | `approval.status=exception`（Gate `decision=EXCEPTION` / approver_empty） | **25** | 明说"平台未能解析出审批人、已通知管理员，请联系管理员处理审批异常"——**同样永远不会有结论** |
    | （非终态）超时 | 到 `--wait-timeout` 仍未落定 | **23** | 明说"这不是失败"，给审批单标识与跟踪方式 |
- **⚠️ 为什么必须收 `cancelled` / `exception`（评审修订）**：这两个态在 F055 是**确定会发生**的——① 审批人解析为空时 Gate 返回 `ApprovalGateResult(decision=EXCEPTION)`（`055-app-publish-pipeline/design.md:44` K2 ②、§4.1 A `approver_empty` 分支，AC-18「不放行也不静默卡死」）；② 应用被删除时 F054 钩子调 `cancel_instance_by_business` 把 instance 置 `CANCELLED`（F055 D10 / §4.1 B）。若只认四终态，`--wait` 会一路轮到 `--wait-timeout` 后退 23 并打印"这不是失败，请继续等审批"——而真实情况恰恰相反：**这单已经死了**，等下去毫无意义。两个码与 AC-31c 不冲突（四种终态仍各自可区分，这是超集）。
- **⚠️ `entry_url` 的取值缺口（回写项 3）**：`entry_url` 在 F055 契约里**只出现在 `POST /deploy` 的返回**（`055-app-publish-pipeline/design.md:492`），`GET /api/v2/apps/deployments/{id}` 的轮询载荷是 `{stage, status, failure, app_id, version_no, approval{...}, app_state, pending_reason}`——**没有 `entry_url`**；而首发时 `POST` 那一刻应用还是草稿、`entry_url` 大概率为 `null`。→ AC-31c「通过并上线（输出入口地址）」/ AC-33 / spec 决议-12 目前落不了地。**已登记为跨 Feature 回写项 3**（§6.2 / §8）：请 F055 给轮询载荷补 `entry_url`（`app_state=已上线` 时非空）。**在补上之前的降级行为**：`POST` 返回的 `entry_url` 非空则回显；为空则打印"入口地址请在应用详情页·发布获取"并照常退 0——**明确指路而不是打印一个空串或 `None`**（tasks 里对应任务标 `[受阻于 F055 回写]`）。
- **原因**：可区分的退出码是 AC-31c 的字面要求，也是 agent 在无 TTY 下唯一可靠的分支依据；把"超时"单列一个码是因为它与"驳回"的后续动作完全相反（等 vs 改），共用非零码会让 agent 把等待当失败处理；把 `cancelled` / `exception` 单列同理——它们的后续动作是"去找管理员"而不是"改代码"或"继续等"。
- **何时该重新考虑**：出现真实的审批推送通道（站内信 webhook / MCP 订阅）→ `--wait` 可以改成"挂起 + 事件唤醒"，但短轮询必须保留为回落（客户环境未必开推送）。

### D8：`logs` = 服务端判权限、CLI 只呈现；`--follow` 用 `since` 短轮询

- **备选**：
  - A. CLI 侧先查一次应用归属再决定要不要请求 — **错的**：会引入第二处归属判定，且 CLI 拿不到权威数据（AC-42 的判据是"密钥的**资源归属人**"，只有服务端有）
  - B. **直接打端点，把 403 / 16205 / 16254 翻成人话**（选定）
- **选定**：**B**。`GET /api/v2/apps/{app_id}/logs?tail=&since=&keyword=` → `{lines[]}`。**owner-only 由服务端判**（F055 tasks T039：读 `OpenApiPrincipal.resource_owner_user_id`，**不是** `subject_user_id`）；即使密钥属于租户管理员名下的服务账号也照拒（AC-42），CLI 对此零逻辑。
- **`--follow` 的实现**：无流式接口（服务端链路是 `GET /api/v2/.../logs` → F054 `GET /api/v1/apps/{id}/logs` → runtime-manager `docker logs`，全是一次性响应），所以只能**携 `since` 短轮询**（3 s）。⚠️ **必须做去重**：docker 时间戳是秒级，同一秒的多行在下一轮 `since` 里会重复返回（同类坑在本仓咬过：memory `project_chat_history_sameSecond_order`「create_time 秒级打平」）→ 保留上一轮最后 N 行的内容哈希集合，命中则跳过。
- **AC-43（无运行实例时提示应用态）目前落不全**：F055 的 logs 返回**只有 `{lines[]}`**，没有 `app_state`。→ 已登记为**跨 Feature 回写项 2**（§6.2），建议 F055 把返回补成 `{lines[], app_state, pending_reason}`。**在补上之前的降级行为**：`lines` 为空时输出"未取到日志：应用可能没有运行实例（草稿 / 待上线 / 已停运），请在应用详情页确认应用态"——**明确提示而不是空白**，满足 AC-43 的精神但不满足其字面（tasks 里对应任务标 `[受阻于 F055 回写]`）。
- **日志保留期不做承诺**：runtime-manager 侧是 docker 日志轮转窗口（30 MB/应用，F054 design `:334`）——CLI 对 `--since` 取到空结果只说"该时间段无日志或已轮转"，不说"没有发生过"。
- **何时该重新考虑**：runtime-manager 实现了**流式** logs（其 `GET /v1/apps/{id}/logs` 已由批 4 落码〔commit `d693feeb3`〕，但只回 `{lines:[...]}` 快照、非流式）→ `--follow` 可换 chunked 流，但仍要保留短轮询回落（nginx 300 s 上限对流式同样成立）。

### D9：错误呈现 = 「原始 code + 一句人话 + 下一步」三件套，且必须两套信封都认

- **备选**：
  - A. 只打服务端 `message` — 缺点：平台的 message 面向"平台使用者"，不含"你该改哪"；agent 拿不到可执行的下一步
  - B. CLI 完全重写文案、藏起 code — 缺点：出问题时开发者报给支持的是一句翻译过的中文，支持侧无法定位
  - C. **三件套：原始 `code`（永远打印）+ CLI 的中文一句话 + 下一步指引**（选定）
- **选定**：**C**。`errors.py` 里一张 `ERROR_HINTS: dict[int, tuple[str, str]]`（code → (人话, 下一步)），未登记的 code 一律降级为"平台返回错误 {code}：{message}"并原样打 `message`、**以退出 19 结束**（**未知不等于崩溃，也不等于成功**；退出码确定是 AC-04 的要求，不能让未登记 code 落进 exit 1「CLI 内部异常」那一格）。
- **⚠️ 必须两套信封都认**（坑 12）：`/api/v2` 有**专属异常处理器**，真 HTTP 状态在状态行（401/403/404/500/503），body 仍是平台信封 `{status_code, status_message, data}`（`open_api/api/exception_handlers.py:36-61`）；而 `/api/v1`（分发端点所在）**照旧 HTTP 200 + 信封**（`:61`）。解析顺序固定为：先读 body 里的 `status_code`（存在且 ≠ 200 即业务错误码），再看 HTTP 状态——反过来会把 `/api/v1` 的所有业务错误当成功。
- **登记的主要 code**（全表见 §4.2 ②，来源 = F049 `common/errcode/open_api.py` + F055 design §4.2 ⑧ `:588-591`）：`26001/26002/26027` → 退出 4；`26003` → 退出 5 且**逐字打出 `data.required` 里缺的位名**（AC-34）；`26030`（503，fail-closed）→ 退出 7 且明说**可重试**；`16207` → 退出 8「本环境未启用应用工场」（AC-40）；`16201/16202/16203` → 退出 6（改本地再传）；`16221/16222/16223/16224/16227/16228/16230/16231` → 退出 10；`16241` → 退出 11；`16205/16229/16251/16252/16254` → 退出 12；**`16225` → 退出 13**、**`16226` → 退出 14**（见下条）。
- **⚠️ 三条"绝不能合并"的映射（评审修订，`ERROR_HINTS` 落码前逐条对照）**：
  1. **`16225`（审批场景未启用）≠ `16226`（运行环境容量不足）**——F055 design D4 `:149` 与 §4.2 ⑧ `:596` 两处逐字警告过："二者的 CLI 处置南辕北辙"，前者是"平台没 seed 审批场景，找管理员"（改代码无用，退出 **13**），后者是"机器没资源，等一会儿或让 owner 手动上线"（可重试，退出 **14**）。把它们一起塞进"托管预检失败"就等于把这条警告作废。
  2. **`16231`（本环境未启用能力总线）的处置是"删掉 `capabilities` 声明"，不是"找管理员开开关"**——能力总线本轮整体后置（F055 §6 波次表），CLI 的下一步指引必须写"本版不支持能力声明，请从 `bisheng-app.yaml` 删除 `capabilities` 后重发"，映射退出 **10**（要改 manifest）而不是退出 8（环境未启用）。`16230`（能力声明含密钥引用）同理。
  3. **`16203`（缺 `bisheng-app.yaml`）必须单独有话说**——CLI 本地就该拦住它（AC-30 / §4.1 B 步 2），服务端仍回 16203 只有一种可能：**包根与项目根不一致**（打包起点选错）。文案要指向"检查 `deploy` 的 PATH 参数与包根"，而不是"请创建 manifest"。
- **`16229` 本轮无写入方但必须登记**：结构演进整体后置（F055 §6 波次表，`confirm_schema_change` 只接收不消费），所以 16229 本轮不会出现；但 `--confirm-schema-change` 参数本轮就实现（D11 第 4 条），映射不登记就会在结构演进上线那天变成"未知 code"。同理 `16253` / `16255` 属发布面动作、CLI 触发不到，走 D9 的降级分支（退出 19）即可，不单独登记。
- **两个"看起来像 CLI 出错、其实不是"的码要特别标注**：`26004`（带了 `X-Bisheng-On-Behalf-Of` / `X-Bisheng-End-User`）——CLI **绝不发这两个头**，出现即 CLI bug，文案直接写"这是 CLI 缺陷，请报障"；`26031`（端点漏 `@open_api_scope` 标记）——平台缺陷，文案写"请报平台故障"。把它们翻成"你的密钥有问题"会让排障走上完全错误的方向。
- **何时该重新考虑**：`ERROR_HINTS` 超过 40 条 → 那时该考虑让服务端在 `hints[]` 里直接给面向 CLI 的下一步（F055 的失败五元组已有 `hints`，只是 260 段还没有），CLI 退化为纯呈现。

### D10：平台分发端点 = `/api/v1/dev-toolkit/*`，匿名可达，开关关闭时**不注册路由**

- **备选（落点）**：
  - A. `/api/v2/**` 下 — **结构性否决**：F049 计划把 `verify_open_api_access` 提升到整个 `router_rpc`（`src/backend/bisheng/api/router.py:123-126` 的注释），届时 `/api/v2` 下任何端点都必须持密钥；在那里放匿名端点是永久例外
  - B. 裸路径 `/cli/download`（照 `/health` 的挂法，`main.py:145-147`）— **不可达**：商业版网关只转发 `/api/v1/**` 与 `/api/v2/**`（CON-7），OSS nginx 同形
  - C. **`/api/v1/dev-toolkit/**` 下一个不挂 `Depends(UserPayload.get_login_user)` 的新 router**（选定）
- **选定**：**C**。两个端点：
  - `GET /api/v1/dev-toolkit/versions` → 版本与兼容信息（形状见 §4.2，**一次留够 SDK 字段位**）
  - `GET /api/v1/dev-toolkit/cli/download` → `FileResponse(wheel_path, filename=...)`
  模板 = `GET /api/v1/env`（`api/v1/endpoints.py:62-63`：普通 `@router.get`，函数签名里没有任何 auth `Depends` 即匿名）；`FileResponse` 写法照 `open_endpoints/api/endpoints/filelib.py:496-506`（自动 `Content-Length`、支持 Range、零内存放大）。**不用 MinIO 预签 URL**：安装件是随镜像发布的静态物，不该进对象存储，且 `clear_minio_share_host`（`minio_storage.py:686`，docstring `:687-691` 逐字说明"让前端通过 nginx 代理访问资源"）会返回依赖前端 nginx 的相对路径，CLI 直连时拿不到可用 URL。
- **AC-05「开放能力层未部署 → 端点呈不存在」的落地 = 条件注册，不是抛 404**：`settings.open_platform.enabled`（`core/config/open_platform.py:16-20`，**进程级 YAML 配置、非 DB 热配置**）为假时**根本不 `include_router`** → FastAPI 天然 404。收益有三：① 字面满足"呈不存在"；② **零新错误码**（CON-8）；③ 不给未认证方留一个"这里有个功能但没开"的探测面。代价：改配置要重启后端——这正是进程级配置的既有语义，不是新增负担。
- **⚠️ AC-05 的一半本轮做不到，此处显式登记为偏离（评审修订）**：spec §范围边界逐字写「**平台侧 login 校验入口**（含 `delegate` 拒绝）由本 Feature 拥有」、AC-05 要求开放能力层未部署时「安装件下载端点、技能包分发端点**与 login 校验入口**均不可达（呈不存在）」。但 `login` 校验打的是 **F049 已实现的 `GET /api/v2/auth/whoami`**，它挂在 `router_rpc` 上**恒在注册**（`api/router.py:123-126`），且服务账号模块「**恒在、不随 open_platform 开关消失**」是 F049 的显式设计（`core/config/open_platform.py:17-18` 注释逐字："gates only the local-dev-toolkit scopes and the connect-info panel …; the service-account module is always on"）。
  - **本轮的处置**：F053 只交付**两个分发端点**的条件注册；「login 校验入口不可达」这一半**不实现**。**CLI 侧的等价保证**：`login` 的**前置探测**先打 `versions`，404 且 `env.open_platform_enabled=false` → 判定「本环境未部署开放能力层」并**在打 whoami 之前**退出 8（§4.1 A）——开发者观感上 `login` 在该环境确实不可用，AC-10「可读原因」照落。
  - **为什么不建议改实现**：把 whoami 也置于开关下，等于让"服务账号模块恒在"这条 F049 设计破例，且会波及 F049 已落码的鉴权面。→ **建议改 spec 措辞**（把 AC-05 的"login 校验入口"改成"CLI 的 login 在该环境不可用并给出可读原因"），已登记为**回写项 4**（§6.2 / §8）。对比参照：AC-06（D14）与 AC-43（D8）也都是"上游未就位 → 明写降级"的同一种处置，本条与它们同档。
- **必须同批做的两件事**：① 新 router 加进 `src/backend/bisheng/api/router.py`（`:66-112` 那一片）；② **路径前缀 `/api/v1/dev-toolkit` 加进 `TENANT_CHECK_EXEMPT_PATHS`**（`utils/http_middleware.py:16-44`）。第二条不是可选优化：多租户开启时无 JWT 的请求**不会**调 `set_current_tenant_id`（`http_middleware.py:107-112` 只在 `not multi_tenant.enabled` 时兜底），任何 DAO SELECT 都会 `NoTenantContextError`；豁免名单会把整棵调用树置于 `_bypass_tenant_filter`（`:321-323`）。本端点若严格只读磁盘可以不加，但**版本端点要回 `open_platform_enabled` / `app_runtime_enabled` 且将来极可能读表**，现在就加更省事。
- **wheel 怎么到镜像里**（坑 11，最容易在生产翻车的一条）：backend 镜像的 build context 只有 `./src/backend/`（`.github/workflows/ci.yml:54` 的 `docker buildx build … ./src/backend/` + `src/backend/Dockerfile:13` `COPY ./ ./`）→ **`src/bisheng-cli/` 不在镜像内**。解法照 `linsight/builtin_skills/` 的判据（`builtin_skill_seeder.py:45-47` 逐字："inside the package so every deployment shape (docker COPY, rsync, pip install) carries it automatically"）：**wheel 产物随后端包同行**，放 `src/backend/bisheng/dev_toolkit/artifacts/`，由 `scripts/pack_cli_wheel.sh`（骨架照 `scripts/pack_linsight_skill.sh:1-40`）构建后拷入；端点用 `Path(__file__).resolve().parents[N] / "artifacts"` 定位（同款写法）。⚠️ **artifacts 目录名不能叫 `build` / `lib` / `wheels` / `sdist`**——`.gitignore:137,148,150,152` 这几条是**无前导斜杠的全局规则**，任何层级同名目录都会被忽略，产物提交不上去（`git check-ignore` 实测：`src/bisheng-cli/dist/` 不被忽略，因为 `/dist/` 是根锚定的；但 `build/x` 命中）。
- **何时该重新考虑**：安装件从一个 wheel 变成多产物矩阵（二进制 × 平台 × 架构）→ `versions` 载荷升级为 `assets[]`，下载端点加 `?asset=`；或平台开始热更新技能包 → 那时分发端点要读 DB（届时 `TENANT_CHECK_EXEMPT_PATHS` 那条就是必需而不是预防）。

### D11：MVP-核心边界 = 顺延命令**不注册**，顺延契约**先留形状**

- **备选**：
  - A. 顺延命令注册但执行时报"本版本未提供" — 缺点：`--help` 会列出五个命令，agent 会去调，然后拿到一个非标准失败；且 AC-03「提供且仅提供五个子命令」在本轮本来就做不到，假装提供只是把缺口藏起来
  - B. **顺延命令不注册；顺延的数据契约先在载荷里留字段位**（选定）
- **选定**：**B**。落地为三条具体规矩：
  1. **`skills sync` / `dev` 不进解析器**：`bisheng --help` 本轮只列 `login` / `deploy` / `logs`。README 与 `--help` 尾部注明"`dev` / `skills sync` 随后续版本提供"。
  2. **`versions` 端点的 SDK 字段位一次留够**（`sdk.version` / `sdk.min_compatible` / `sdk.download_path`，本轮值为 `null`）：F057 AC-01/03 消费**同一端点**，不先留就会在 F057 期出现第二个端点或一次破坏性改形。
  3. **版本兼容只提示不阻断**：CLI 每次命令前置探测 `versions`，`cli.min_compatible > 本地版本` → 打 warning + 下载链接，**不拒绝执行**；开启阻断只需把那句 warning 换成 `CliError`（AC-02 的完整落地随顺延项）。
  4. **`--confirm-schema-change` 本轮就实现**：F055 端点"只接收不消费"（design D3），但参数存在与否是 CLI 的对外契约——现在不做，将来要改 CLI 与文档两处（F055 自己也是按这个理由留的端点参数）。
  5. **多平台只落数据结构、不落交互**（评审修订，与 §1 非目标表和 `mvp-114-path.md` §6「多平台凭据」顺延列对齐）：凭据文件本轮就按多 profile 结构写（D3，将来零迁移），但 **`--platform` 参数本轮不注册**——`deploy` / `logs` 一律用 `credentials.json` 的 `current`（由最近一次 `login` 覆盖）。顺延的是整个交互层：`--platform` 选择、`profile` 列出与切换默认平台。判据同本决策原则：**数据形状改一次、交互层改一次**，而 `--platform` 属交互层。
- **原因**：区分"顺延项"的判据是**改一次 vs 改两次**——顺延交互层（命令、UI、阻断策略）改一次就够；顺延数据形状（端点载荷、文件结构、参数集）会让消费者写两遍。
- **何时该重新考虑**：MVP 之后启动顺延波次时，本决策整体退役——届时删掉本节并把 §1 非目标表相应行迁进 §4。

### D12：依赖预算 = `httpx` + `PyYAML` 两条，其余全标准库

- **备选**：
  - A. 零第三方（`urllib.request` + 手写 YAML 子集解析）— 缺点：multipart 上传要手拼 boundary、超时/代理/重试语义要自己实现、YAML 自研解析器在真实 manifest 上必错；错误面比省下的依赖大得多
  - B. `httpx` + `PyYAML` + `typer` + `rich`（生态标配四件套）— 缺点：四条内网安装链
  - C. **`httpx` + `PyYAML` 两条**（选定）
- **选定**：**C**，每条都有"为什么不能用标准库"的一句话论证：
  - **`httpx`**：需要流式 multipart 上传、细分的 connect/read 超时、`trust_env` 开关（坑 2）。`urllib` 三样都要手写，且 multipart 手拼是典型的低级 bug 温床。（备选 `requests` 亦可，选 httpx 是因为 backend 已在用、行为对齐）
  - **`PyYAML`**：`bisheng-app.yaml` 解析。必须 `yaml.safe_load`——`full_load` / `unsafe_load` 的 `!!python/object` 是 RCE（F055 design D3 逐字红线）。
  - **标准库覆盖其余全部**：`argparse`（命令面）· `tarfile` + `gzip`（打包）· `fnmatch` 的**段级**用法 + 手写段匹配（忽略规则，**不用它顶 gitignore 全语义**）· `getpass`（隐藏输入）· `json` / `pathlib` / `os` / `subprocess`（git 探测）/ `hashlib` / `time`。
- **原因**：CON-2。每条依赖都要在客户内网 pip 镜像里存在；两条都是纯 Python、无二进制扩展、在任何镜像里都是最常见的包。
- **何时该重新考虑**：出现"客户内网连 httpx 都没有"的真实案例 → 那时 wheel 改打 **vendored**（把两个依赖打进包）而不是回退到 urllib；或引入第三条依赖时，必须在本节补一行论证（这是刻意设的门槛）。

### D13：应用标识保存 = 项目根 `.bisheng/app.json`，**接收成功即写**

- **备选**：
  - A. 写进 `bisheng-app.yaml` — **否决**：manifest 形态归 F055 且 `extra='forbid'`（F055 design §4.2 ③），CLI 加字段会被服务端当场拒；spec 决议-6 也明写"不要求开发者手写"
  - B. 存在全局凭据文件里（按项目绝对路径索引）— 缺点：项目移动 / 复制后失效，且团队成员之间无法共享
  - C. **项目根 `.bisheng/app.json`**（选定）
- **选定**：**C**。结构按平台 base URL 分键（同一项目将来可发到多个平台），`--app-id` 可显式覆盖。**建议开发者把 `.bisheng/` 提交进 git**（团队共享同一个 app_id），但它**结构性排除出上传包**（D4）——"进 git"与"进包"是两件事。
- **⚠️ 关键时序：`POST /deploy` 返回 200 的那一刻就写盘，不等管线成功**。理由来自 F055 design D2 的选定（"接收成功后立即创建草稿应用"）：**首发预检失败时平台已经建好了草稿应用并分配了 `app_id`**，返回载荷里就有它。若 CLI 只在成功时才保存，开发者修完 manifest 重跑就会**再建一个应用**，构建页上堆一串同名草稿——而 F055 明确说"CLI 会把 app_id 随项目保存、重试 deploy 复用同一个 app_id"，这条依赖是双向的。
- **误投护栏**（AC-33 / spec §3）：迭代 `deploy` 在上传前**必须**打印目标应用的名称与标识；交互环境下要确认（`--yes` 跳过），非交互环境下这行输出是唯一护栏。理由：指定了归属人不同的应用会被 16205 拒（安全），但指定了**同一归属人的另一个应用**会真的更新那个应用（无声的错误）。
- **何时该重新考虑**：出现"一个项目目录发布多个应用"的真实诉求 → `app.json` 加 `profiles` 层（结构已按 dict 分键，扩展无破坏）。

### D14：`login` 的输出 = `whoami` 载荷 + 资源归属人；**`whoami` 目前缺该字段，需 F049 补**

- **备选**：
  - A. **请 F049 给 `WhoamiResponse` 加 `resource_owner: {user_id, user_name}`**（选定）
  - B. F053 降级：只输出服务账号名，提示"去详情页看归属人"
  - C. CLI 另调一个查归属人的端点 — **否决**：等于为 CLI 单开一条身份查询面，且那个端点的鉴权口径要重新论证
- **选定**：**A**，B 作为 F049 未补前的**降级行为**。
- **事实**：`login` 打的是 `GET /api/v2/auth/whoami`（`open_api/api/endpoints/auth.py:19-50`），它是 `/api/v2` 下**唯一 `@open_api_scope(None)` 的端点**（`auth.py:23`，"不需要任何权限位、只验密钥有效"）——正是 AC-06「不校验任何权限位」的落点。但返回的 `WhoamiResponse`（`open_api/domain/schemas/credential.py:108-116`）只有 `subject_kind` / `service_account` / `tenant_id` / `scopes` / `key_mask` / `expires_at`，**没有资源归属人**；而 `OpenApiPrincipal.resource_owner_user_id` 在服务端是存在的（`open_api/domain/context.py:37-39`）。
- **为什么值得让 F049 改**：AC-06 要求 `login` 输出资源归属人，理由不是"信息完整"而是**误配防线**——资源归属人就是此后 `deploy` 出的应用 owner，管理员把归属人选错（选成自己而不是开发者）是 F049 自己在签发表单上加风险提示的那个错误；如果开发者在 `login` 那一刻看不到它，这个错要等到 deploy 之后、甚至换人接手时才暴露。改动量 = 一个可选字段 + 一次 user 名查。
- **降级行为（F049 补上之前）**：输出服务账号名 + `key_mask` + 租户，并明打一句"资源归属人请在服务账号详情页确认"；对应 AC 标 `[受阻于 F049 回写]`。
- **`delegate` 的处置（AC-09 / AC-13）**：`whoami.scopes` 含 `"delegate"` → 拒绝写凭据、给委托专用文案、退出码 5。⚠️ **F049 期根本签不出这一位**（`open_api/domain/scopes.py:186-188` 的 NOTE 逐字："deliberately NOT registered … ships with F050"），所以这段代码在 MVP 期**无法端到端验证**，只能用构造 mock 响应的单测覆盖——tasks 里对应任务必须写清这一点，否则实现者会去 114 上试然后判定"功能不生效"。
- **何时该重新考虑**：F050 落地后 `delegate` 可签发 → 那时补一条真实的端到端用例；`whoami` 若被扩成"返回主体的完整画像"，CLI 要重新审视存哪些字段（D3 说过只存展示用快照）。

---

## 4. 系统现状（接手必读）

> 本 Feature 尚未开工，以下是**要建成的样子**。实现后按现状覆盖。

### 4.1 数据流

**A. `login`**

```
bisheng login <base-url> [--api-key … | BISHENG_API_KEY | 隐藏输入 | --api-key-stdin]
  → 前置探测 GET /api/v1/dev-toolkit/versions        # 匿名，无需密钥
      ├ 404 → 再探 GET /api/v1/env 判别（三支各有确定退出码，AC-04/AC-10）：
      │        能通且无 open_platform_enabled → "平台版本过老，不支持 CLI"                 → exit 9
      │        open_platform_enabled=false     → "本环境未部署开放能力层"（AC-05/AC-10）  → exit 8
      │        env 也不通                       → "平台不可达"                            → exit 7
      │        ⚠️ 判定后**直接结束、不再打 whoami**——AC-05 的"login 不可用"由这里兑现（D10 偏离登记）
      └ 200 → 记下 cli.min_compatible（本轮只提示不阻断，D11）
  → GET /api/v2/auth/whoami   Authorization: Bearer bs-sak-…
      ├ 26001/26002/26027 → 密钥无效/撤销/过期/账号停用（彼此可区分，AC-10/AC-11） → exit 4
      ├ 26030 (503)       → 平台鉴权服务暂不可用，可重试                             → exit 7
      ├ scopes 含 "delegate" → 拒绝、不写凭据、委托专用文案（AC-09，D14）            → exit 5
      └ 200 → 写 ~/.bisheng/credentials.json（0600，覆盖同 base_url 的 profile，D3）
  → 输出：目标平台 / 服务账号名 / 资源归属人（或降级提示）/ key_mask / 到期时间
    ⚠️ 本轮不自动执行 skills sync（AC-08 随顺延项）
```

**B. `deploy`**（人读文本走 stderr、`--json` NDJSON 走 stdout，D2）

```
bisheng deploy [PATH] [--app-id] [--wait] [--confirm-schema-change] [--yes] [--json]
  1 载入凭据（无 → "请先 bisheng login"，AC-51）                                  → exit 3
  2 定位项目根 + 读 bisheng-app.yaml（yaml.safe_load）
      缺文件 / YAML 不可解析 / 缺 name|runtime|port → 本地拒绝、列缺失项、不上传（AC-30） → exit 6
  3 解析忽略规则（git ls-files 优先 / 子集解析器回落 / .bishengignore 收口，D4）
      → 打包 tar.gz（结构性排除、跳过链接与设备文件、可复现、保留可执行位）
      → --dry-run 到此为止：打印条目数 / 体量 / 被忽略统计
  4 GET /api/v2/apps/deploy-limits → 超限则拒绝 + Top10 大文件 + 忽略建议（AC-32） → exit 6
      取不到 → 只提示、继续（服务端 16201 兜底）
  5 迭代场景：读 .bisheng/app.json 的 app_id → 打印目标应用名称 + 标识（误投护栏，D13）
      交互环境要确认（--yes 跳过）；非交互直接打印
  6 POST /api/v2/apps/deploy  (multipart: package + app_id? + confirm_schema_change)
      ⚠️ 服务端在这一次同步响应里就跑完了「归属判定 · 大小闸 · 解包闸 · manifest 校验
         · 本地引用校验 · 在途单 / 待上线闸」（F055 design §4.1 ① `:411-427`），
         **首发最常见的失败（manifest 缺字段）全部在这里返回、轮询里永远看不到**（D6）
      → 200：{deployment_id, app_id, version_id, entry_url?}   # 服务端此刻才 INSERT stage=received
        ★ 立即把 app_id 写进 .bisheng/app.json（哪怕后续失败，D13）
        ★ entry_url 非空则记下——轮询载荷里没有这个字段（D7 回写项 3）
      → 同步错误分支（一条都不能漏，按 code 映射退出码后直接终止，不进轮询）：
          16207 本环境未启用应用工场（AC-40）              → exit 8
          26003 缺 app:manage（逐字打 data.required）      → exit 5
          16205 该应用归属他人（含归属谁，AC-38）           → exit 12
          16201 包超上限 ／ 16202 包解析失败或非法路径条目   → exit 6（改本地再传）
          16203 缺 bisheng-app.yaml（多半是包根选错，D9）   → exit 6
          16221 manifest 校验失败（details 指出缺哪个字段）  → exit 10
          16222 runtime 不支持 ／ 16223 档位不存在或已停用
          ／ 16224 能力声明不可解析 ／ 16230 含密钥引用
          ／ 16231 本环境未启用能力总线（提示删 capabilities）→ exit 10
          16229 结构变更未确认（提示 --confirm-schema-change；本轮无写入方，D9）→ exit 12
          16251/16252 在途单 / 待上线态（提示撤回路径在应用详情页·发布）→ exit 12
  7 轮询 GET /api/v2/apps/deployments/{deployment_id}（2s 起，×1.5 封顶 10s，D7）
      能看到的 stage 只有 received 之后的（服务端权威枚举见 D6）：
        received → secret_scan → precheck_build → precheck_probe → version_recorded → approval_created
        （--wait 续轮还会看到 approved → publishing → online ／ pending_online）
      任一 failed → 打印 failure{message, hints[]}、机读原样透传 details → 按 code 映射退出码，终止
        16227 依赖构建失败 ／ 16228 启动探活失败 → exit 10
        16241 扫描命中（只打 file:line，永不回显值）→ exit 11
        16225 审批场景未启用（找管理员 seed）    → exit 13   ← 与 16226 绝不同码（D9）
        16226 运行环境容量不足（等资源 / 稍后重试）→ exit 14
        未登记 code → 原样打印 code + message   → exit 19
  8a 无 --wait：轮到 status=waiting_approval 即返回 0，输出审批单标识 + 三条跟踪路径（AC-31b）
  8b 有 --wait：续轮至终态（D7 终态表）
        0 通过并上线（入口地址取 POST 返回的 entry_url；为空则指路应用详情页·发布 —— 回写项 3）
        20 驳回 / 21 撤回 / 22 待上线 / 24 取消（应用已删）/ 25 审批异常（审批人为空）/ 23 超时
```

**C. `logs`**

```
bisheng logs [--app-id] [--tail N] [--since TS] [--keyword K] [--follow] [--json]
  → 凭据 + app_id 解析（同 deploy 第 1/5 步）
  → GET /api/v2/apps/{app_id}/logs?tail=&since=&keyword=  → {lines[]}
      16254 仅 owner 可执行 / 16205 归属他人 → "该应用不属于当前密钥的资源归属人"（AC-42，服务端判，D8） → exit 12
      26003 缺 app:manage 位（逐字打 data.required）                                      → exit 5
      lines 为空 → 提示可能无运行实例（AC-43 降级行为，D8）
  → --follow：每 3s 带 since 再拉，按内容哈希去重（秒级时间戳会重复，D8）
```

### 4.2 关键数据结构 / 字段约定（对外契约）

**① 命令与参数面**（本轮实现三条；`skills sync` / `dev` 不注册，D11）

| 命令 | 位置参数 | 参数 | 说明 |
|---|---|---|---|
| `login` | `<base-url>` | `--api-key` · `--api-key-stdin` · `--json` | 密钥来源优先级：`--api-key` > `BISHENG_API_KEY` > `--api-key-stdin` > TTY 隐藏输入；四者皆无 → exit 2（AC-07） |
| `deploy` | `[PATH]`（默认 `.`） | `--app-id` · `--wait` · `--wait-timeout`（默认 1800）· `--confirm-schema-change` · `--yes` · `--dry-run` · `--json` | `--dry-run` 只打包 + 本地校验 + 打印体量统计，不上传。**无 `--platform`**：本轮恒用 `credentials.json` 的 `current`（D11 第 5 条） |
| `logs` | — | `--app-id` · `--tail`（默认 200）· `--since` · `--keyword` · `--follow` · `--json` | `--follow` 短轮询 3 s（D8）。**无 `--platform`**，同上 |
| 全局 | — | `--version` · `--help` · `--verbose` · `--quiet` · `--timeout` | `--verbose` 打印请求方法/路径/状态码；**Authorization 头恒掩码** |

**② 退出码表**（AC-04「确定的退出码」/ AC-31c「四种终态各有可区分退出码」的权威定义）

> **一码一处置**：本表的分格判据是**开发者/agent 的下一步动作**，不是"错误的严重程度"。凡两个 code 的下一步动作不同，就必须落在不同的码上（D9 三条红线）。

| 码 | 含义 / 下一步动作 | 典型来源 |
|---|---|---|
| 0 | 成功（`--wait` 下 = 通过并上线） | — |
| 1 | CLI 内部未预期异常 | traceback 仅在 `--verbose` 打印 |
| 2 | 用法 / 参数错误 | 缺必填参数、互斥参数同用 |
| 3 | **未登录**（AC-51） → 先 `bisheng login` | 无凭据文件或无该平台 profile |
| 4 | 鉴权失败 → 换 / 重签一把密钥 | `26001` / `26002` / `26027` |
| 5 | 权限不足 / `delegate` 拒绝 → 找租户管理员编辑密钥位 | `26003`（打出 `data.required`）· AC-09 |
| 6 | 本地校验失败 / 包不合法 → 改本地再传 | manifest 缺失或不合法（本地）· 路径不存在 · `16201` 超上限 · `16202` 解析失败或非法路径条目 · `16203` 缺 `bisheng-app.yaml`（多半包根选错） |
| 7 | 平台不可达 / 服务暂不可用 → 稍后重试 | 网络错误 · `26030`（**可重试**） |
| 8 | 环境未启用 → 找管理员开开关并重启后端 | 分发端点 404（开放能力层）· `16207`（工场运行时层） |
| **9** | **平台版本过老，不支持本 CLI** → 升级平台，或换用与平台同版的 CLI | `versions` 404 且 `/api/v1/env` 无 `open_platform_enabled`（§4.1 A） |
| 10 | 托管预检失败 → 改 manifest / 改代码后重发 | `16221` · `16222` · `16223` · `16224` · `16227` · `16228` · `16230` · `16231`（后两者的下一步是**删掉 `capabilities` 声明**，D9 红线 2） |
| 11 | 密钥扫描命中 → 移除密钥后重发 | `16241` |
| 12 | 发布流程冲突 / 归属与操作权限 → 撤回在途单、或换归属人正确的密钥 | `16205` · `16229` · `16251` · `16252` · `16254`（仅 owner 可执行） |
| **13** | **平台未 seed 审批场景** → 找平台管理员，**改代码无用** | `16225`（D9 红线 1） |
| **14** | **运行环境容量不足** → 等资源 / 稍后重试 / 让 owner 手动上线 | `16226`（D9 红线 1，**绝不与 13 合并**） |
| **18** | **缺陷类：CLI 或平台的实现缺陷** → 停下报障，**重试与改参数都无用** | `26004`（CLI 发了它从不该发的身份传递头 = CLI 缺陷）· `26031`（平台端点缺权限位标记 = 平台缺陷） |
| **19** | **平台返回未登记的错误码** → 原样打印 `code` + `message`，按其内容处置 | `16253` / `16255` 等 CLI 触发不到的码；F055 将来新增的码（D9 降级分支） |
| 20 / 21 / 22 | `--wait` 终态：驳回 / 撤回 / 待上线 | `approval.status` · `pending_reason` |
| 23 | `--wait` 超时（**非失败**） → 继续等或换跟踪方式 | 到 `--wait-timeout` 仍未落定 |
| **24** | `--wait` 终态：**审批单已取消**（目标应用被删除）→ 这单不会有结论 | `approval.status=cancelled`（F055 D10 `cancel_instance_by_business`） |
| **25** | `--wait` 终态：**审批异常**（审批人解析为空）→ 找管理员处理审批异常，这单不会有结论 | `approval.status=exception`（F055 K2 ② `decision=EXCEPTION` / approver_empty） |

> **⚠️ exit 18 为什么不并进 1 或 19（2026-08-17 裁决，此前 D9 只说要"特别标注" `26004` / `26031` 却没给退出码）**：这张表存在的唯一理由是让本地 coding agent 不读散文就能决定下一步，所以分格的判据是**动作是否不同**，不是"错误看起来有多严重"。三者的动作各不相同：exit **1**（CLI 内部崩了）——重试一次是合理的；exit **19**（没有登记的码）——读 `message` 后可以改参数重试；exit **18**——重试与改参数**都保证无用**，唯一正确动作是停下报障。这是第三种动作，所以是第三个码。另外把 `26031` 映到 19 还会**给出假标签**：19 的语义是"未登记的码"，而这两个码 CLI 认得清清楚楚。

**③ 凭据文件** `~/.bisheng/credentials.json`（目录 `0700` / 文件 `0600`；Windows 用等价 ACL）

```jsonc
{ "version": 1,
  "current": "https://bisheng.example.com",
  "profiles": {
    "https://bisheng.example.com": {
      "base_url": "https://bisheng.example.com",
      "api_key": "bs-sak-…",                      // 明文，权限位是唯一保护（D3）
      "key_mask": "bs-sak-********abcd",
      "tenant_id": 1,
      "service_account": {"id": 123, "name": "…"},
      "resource_owner": {"user_id": 7, "user_name": "…"} | null,   // 待 F049 补（D14）
      "expires_at": "2026-12-31T00:00:00" | null,
      "logged_in_at": "2026-08-17T10:00:00+08:00"
    } } }
```
**恒不存 `scopes`**（AC-52，D3）。

**④ 项目级应用标识** `<项目根>/.bisheng/app.json`（建议进 git、**结构性排除出上传包**）

```jsonc
{ "version": 1,
  "apps": { "https://bisheng.example.com": {
      "app_id": "…", "app_name": "…", "slug": "…",
      "last_deployment_id": "…", "updated_at": "…" } } }
```

**⑤ 分发端点**（本 Feature 拥有；`settings.open_platform.enabled=false` 时**路由不注册** → 404，D10）

| 端点 | 鉴权 | 返回 |
|---|---|---|
| `GET /api/v1/dev-toolkit/versions` | **匿名** | 见下 |
| `GET /api/v1/dev-toolkit/cli/download` | **匿名** | `FileResponse`（wheel，`application/octet-stream` + `Content-Disposition`） |

```jsonc
{ "status_code": 200, "status_message": "SUCCESS", "data": {   // /api/v1 恒 HTTP200 + 信封（坑 12）
  "cli": { "version": "3.0.0", "min_compatible": "3.0.0",
           "filename": "bisheng_cli-3.0.0-py3-none-any.whl",
           "sha256": "…", "download_path": "/api/v1/dev-toolkit/cli/download" },
  "sdk": { "version": null, "min_compatible": null, "download_path": null },   // F057 消费，本轮留位（D11）
  "platform": { "version": "3.0.0",
                "open_platform_enabled": true, "app_runtime_enabled": true } } }
```
> ⚠️ `platform.version` **不得**取 `/api/v1/env` 的 `version`——那是硬编码 `'2.6.0-fix'`（`src/backend/bisheng/__init__.py:7`，3.0-vibe 分支实测），CLAUDE.md §7「版本字段不可靠」在本分支依然成立。本端点自带版本真相（读 CLI 产物旁的 `artifacts/manifest.json`）。

**⑥ 机读输出（`--json`，NDJSON，stdout）**

```jsonc
{"event":"stage","command":"deploy","stage":"precheck_build","status":"running|passed|failed","ts":"…",
 "failure":{"stage":"…","code":16227,"message":"…","details":{…},"hints":["…"]}}     // 服务端五元组原样透传
{"event":"progress","command":"deploy","phase":"upload","sent_bytes":…,"total_bytes":…}
{"event":"result","command":"deploy","ok":false,"exit_code":10,
 "data":{"deployment_id":"…","app_id":"…","version_id":"…","entry_url":null,
         "stage":"…","app_state":"…","pending_reason":null,"approval":{"instance_id":"…","status":"…"}},
 "failure":{…}}                                                                       // 恒为最后一行
```
> - **`stage` 恒为服务端原值**，取值集见 D6（含 `received` / `version_recorded` / `approval_created` / `approved` / `publishing` / `online` / `pending_online`）；未知值原样透传，不翻译、不报错。
> - **同步段的失败没有 `stage` 事件**：`POST /deploy` 的同步错误直接落进 `result.failure`（`failure.stage` 用服务端给的值，缺省时为 `null`），因为那时 `deployment_id` 可能还不存在（D6 / §4.1 B 步 6）。
> - **`data.entry_url` 只可能来自 `POST /deploy` 的返回**——轮询载荷里没有这个字段（D7 回写项 3）。首发时它大概率为 `null`，agent 不得把 `null` 当成"上线失败"，应用是否上线看 `result.exit_code` 与 `data.app_state`。

**⑦ 消费但不拥有的形状**（全部以 F055 design §4.2 为准，CON-5）
`POST /api/v2/apps/deploy` 入参与返回（**`entry_url` 只在此出现**）· `GET /api/v2/apps/deployments/{id}` 轮询载荷（`stage`（枚举见 D6）/ `status ∈ {running, waiting_approval, succeeded, failed}` / `failure` / `app_id` / `version_no` / `approval{instance_id,status,reject_reason}` / `app_state` / `pending_reason ∈ {"capacity","deploy_failed",null}`；**无 `entry_url`**）· `GET /api/v2/apps/deploy-limits` · `GET /api/v2/apps/{app_id}/logs` · **AppManifest 字段表**（必填 `name`/`runtime`/`port`；可选 `description`/`icon`/`slug`/`tier`/`capabilities`/`database`/`egress`/`manifest_version`；`extra='forbid'`）。
`approval.status` 的取值 CLI 必须认全六种：`pending` / `rejected` / `withdrawn` / **`cancelled`**（应用被删除致取消，F055 D10）/ **`exception`**（审批人为空，F055 K2 ②）/ `executed|approved`（通过，后续看 `app_state`）——后两个异常终态漏认 = `--wait` 死等到超时（D7）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `src/bisheng-cli/pyproject.toml` | 包元数据；`[project.scripts] bisheng = "bisheng_cli.main:main"`（**全仓第一条**）；hatchling + `packages=["bisheng_cli"]` | 不引除 `httpx` / `PyYAML` 外的运行期依赖（D12） |
| `bisheng_cli/main.py` · `cli.py` | 入口与 argparse 子命令注册、全局参数、异常 → 退出码收口 | 不含任何业务逻辑；**不注册顺延命令**（D11） |
| `bisheng_cli/http.py` | httpx 客户端封装：base URL、Bearer 头、超时、**两套信封解析**（坑 12）、代理处理（坑 2）、前置版本探测 | 不判权限位、不缓存 `scopes`（AC-52） |
| `bisheng_cli/credentials.py` | 凭据读写、`0600` 原子创建、profile 选择 | 不做加密（明文 + 权限位是既定取舍，D3） |
| `bisheng_cli/project.py` | 项目根定位、`bisheng-app.yaml` `safe_load` + 三必填快速失败、`.bisheng/app.json` 读写 | **不做完整 manifest 校验**（权威在 F055，CON-1）；不写 manifest |
| `bisheng_cli/ignore.py` | 三层忽略规则（git 优先 / 子集解析 / `.bishengignore`） | 不用 `fnmatch` 顶 gitignore 全语义（坑 9） |
| `bisheng_cli/packaging.py` | tar.gz 打包、结构性排除、体量与条目统计、Top10 报告 | 不静默截断；不上传 |
| `bisheng_cli/errors.py` | `CliError` 体系、`ERROR_HINTS` 翻译表、退出码映射 | 不吞 `details` / `hints`（D6） |
| `bisheng_cli/output.py` | 人读（stderr）/ NDJSON（stdout）双形态、进度、**掩码器** | 不做彩色/表格（无 rich，D2） |
| `bisheng_cli/commands/{login,deploy,logs}.py` | 三条命令的编排 | 不直接用 httpx（走 `http.py`） |
| **平台侧** `bisheng/dev_toolkit/api/{router.py,endpoints/distribution.py}` | 两个匿名端点；开关关闭时**不注册**（D10） | 不直接 import `database/models`（RULE-3）；不查 DB |
| **平台侧** `bisheng/dev_toolkit/artifacts/`（**目录名不能叫 build/lib/wheels/sdist**，坑 11） | 随后端包同行的 wheel + `manifest.json`（版本 / sha256） | 不进 MinIO（D10） |
| **平台侧存量改动** `bisheng/api/router.py` · `bisheng/utils/http_middleware.py` | 挂新 router；`/api/v1/dev-toolkit` 进 `TENANT_CHECK_EXEMPT_PATHS` | — |
| `scripts/pack_cli_wheel.sh` | `uv build` → 校验 → 拷进 `artifacts/` → 写 `manifest.json`（骨架照 `scripts/pack_linsight_skill.sh:1-40`） | 不发布到任何 registry |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **`open()` 后再 `chmod(0600)` 中间有一个 world-readable 窗口**；且 Windows 上 `os.chmod` 对"其他用户可读"基本无效（只影响只读位） | 密钥在多用户机器 / 跳板机上被同机用户读走；Windows 上"已设权限"是假的 | `credentials.py`：`os.open(..., O_CREAT\|O_EXCL\|O_WRONLY, 0o600)` 一步到位 + 父目录 `0700`；Windows 走 `icacls` 等价 ACL，**做不到就明确警告而不是假装成功** |
| 2 | **httpx / requests 默认读 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`**。开发者机器上常年挂着科学上网代理，而平台是内网地址 → 请求被送去代理、超时或拿到代理的 502 | 表现为"平台不可达"，实际平台好好的；本仓已因缺 socksio 吃过整批误报（memory `reference_local_backend_pytest_socks_proxy`） | `http.py`：默认 `trust_env=True` 但**在连接失败时检测代理环境变量并在错误里明说**"检测到 `ALL_PROXY=…`，内网地址请加入 `NO_PROXY`"；提供 `--no-proxy` 直接 `trust_env=False` |
| 3 | **`.venv/` `node_modules/` 不排除时 50 MB 上限秒破**，而开发者的第一反应是"平台上限太小" | 每个新用户的第一次 deploy 都失败；支持工单里全是"包太大" | `packaging.py` 结构性硬排除（D4）+ 超限报告里**先列被排除了多少**，再列 Top10 |
| 4 | **tar 成员路径必须是 posix 相对路径**；Windows 上 `Path` 给出 `\` 分隔、可能带盘符 | 服务端解包出 `src\main.py` 这样的**单个文件名**（Linux 不认 `\` 为分隔符），应用目录结构全平；或触发 16202 非法路径条目 | `packaging.py`：`arcname = PurePosixPath(*rel.parts)`，且落包前逐条 assert 无 `\`、无绝对路径、无 `..` |
| 5 | **Windows 控制台默认 GBK**，打印中文 hints 里的生僻字或 emoji 会 `UnicodeEncodeError` 直接崩，掩盖真正的错误 | 用户看到的是 Python traceback 而不是"缺 `app:manage` 位" | `main.py` 启动时把 `sys.stdout/stderr` 用 `errors="replace"` 的 UTF-8 wrapper 包一层；输出文案不用 emoji |
| 6 | **`--wait` 绝不能靠长连接**：nginx `proxy_read_timeout 300s`（`docker/nginx/conf.d/default.conf:53`），而审批是人工动作、可跨天 | 演示时等到第 5 分钟连接被掐、退出码变成网络错误，看起来像"审批失败" | D7 短轮询 + 退避；`--wait-timeout` 到点退 23 并明说"这不是失败" |
| 7 | **密钥被吊销后的错误码有三种，处置各不相同**：`26002`（无效/撤销/过期）· `26027`（服务账号停用）· 而多租户下**默认租户被禁用**会给一个与密钥无关的 `20001`/403 | 把 `20001` 当成"密钥不对"，让用户反复重新签发密钥；实际要去解禁默认租户 | `errors.py` 三条分别登记；排障口径写进 README：**先看 body 的 `status_code` 是 20001 还是 260xx** |
| 8 | **中间件会把 `Authorization: Bearer bs-sak-…` 当 JWT 取走**（`utils/http_middleware.py:60-73`），解码失败后把租户置成 `DEFAULT_TENANT_ID`（`:81-84`, `:99-106`），再由 `verify_open_api_access` 重新播种真租户 | 不知道这一段，就无法解释"为什么 `/api/v2` 请求会先撞默认租户的禁用黑名单"（`:344-355`）；排障方向全错 | 平台侧既有行为，CLI 不修；坑 7 的排障口径依赖它 |
| 9 | **`fnmatch` 的 `*` 跨 `/` 匹配，且根本没有 `**`**（`linsight/domain/services/workspace_backend.py:616-619` 自己的注释记录了这两点） | 忽略规则静默失效或过度匹配；本仓已真实咬过一次——提示词逐字教的 `glob("/uploads/**/*.xlsx")` 一直 0 匹配（memory `project_taskmode_selftest_114_glob_bug`） | `ignore.py` 手写段匹配（每段单独 `fnmatch`，`**` 单独处理），**并有一张覆盖 `**` / 前导 `!` / 目录后缀 `/` 的用例矩阵** |
| 10 | **`arch-guard.sh` 的 RULE-7 会扫到 CLI 的 `.py`**（`:96-100`，匹配 `(password\|secret_key\|api_key\|access_token)\s*=\s*['"][^'"]{8,}['"]`），尽管其余 9 条规则对 `src/bisheng-cli/` 都不生效。**但它输出的是 `⚠️ [arch-guard] RULE-7 WARNING`（`:99`），不是 VIOLATION、不阻断**——脚本头注释 `:13` 标「硬编码敏感信息检测（C6，**WARNING**）」，VIOLATION 只有 RULE-4/5/8/9/10 | 测试里写一个 `api_key = "bs-sak-xxxxxxxxxxxx"` 的样例常量，每次 Write/Edit 都被 hook 刷一条 warning：**不会拦住你，但会被当成噪声长期忽略，真的硬编码密钥那天也就没人看了**。反向误解同样有害——以为它是 VIOLATION（CLAUDE.md §5「VIOLATION must be fixed immediately」）会让实现者以为 hook 阻断了提交而去改错地方 | 测试用 fixture / 环境变量 / 短占位符；**长密钥字面量一律不写进 `.py`**，让 RULE-7 在本工程保持零输出 |
| 11 | **backend 镜像的 build context 只有 `./src/backend/`**（`ci.yml:53` + `Dockerfile:13`）→ `src/bisheng-cli/` 不在镜像里；而 `.gitignore` 的 `build/` `lib/` `sdist/` `wheels/` 是**无前导斜杠的全局规则**，任何层级同名目录都被忽略 | "本地能下载、生产 404"；或产物目录取名 `build/` 后 `git add` 静默失败，CI 打出的镜像里没有 wheel | `scripts/pack_cli_wheel.sh` 把 wheel 拷进 `bisheng/dev_toolkit/artifacts/`（**这个名字是刻意挑的**）；114 是真 git 检出 + `deploy.sh`、不走镜像，两条路径都要验 |
| 12 | **`/api/v2` 有真 HTTP 状态码，`/api/v1` 恒 HTTP 200 + 信封**（`open_api/api/exception_handlers.py:36-61`，`:61` 是 v1 分支） | 只按 HTTP 状态判断 → `/api/v1` 的所有业务错误被当成功；只按 body 判断 → `/api/v2` 的 503 被当成有效响应 | `http.py` 统一解析：**先读 body `status_code`，再看 HTTP 状态**（D9） |
| 13 | **`deploy` 返回 200 不代表发布成功**——F055 在"接收成功"时就已创建草稿应用并分配 `app_id`（F055 design D2 选定 B） | CLI 只在成功时保存 `app_id` → 预检失败后重跑会**再建一个应用**，构建页堆一串同名草稿；且 F055 明确依赖"CLI 保存 app_id 以复用" | `commands/deploy.py`：拿到 200 立即写 `.bisheng/app.json`（D13） |
| 14 | **服务端 tar 解包闸会拒符号链接 / hardlink 成员 / 设备文件 / FIFO**（F055 design D2） | 本地不跳过 → 每次都吃 16202，且错误发生在上传之后（浪费一次上传） | `packaging.py` 本地就跳过并**列出被跳过的项**（不静默）。**但 hardlink 成员不靠「跳过硬链接文件」规避**——手工构造 `TarInfo` 的写入路径根本产不出该成员类型，跳过只会白丢内容（见 D4 订正） |
| 15 | **`delegate` 位在 F049 期根本签不出来**（`open_api/domain/scopes.py:186-188` 的 NOTE 逐字："deliberately NOT registered … ships with F050"） | 实现者去 114 上试 AC-09，试不出来，判定"功能没生效"并去改代码 | AC-09 / AC-13 的验收方式**只能是单测**（构造 mock `whoami` 响应）；tasks 里必须写明（D14） |
| 16 | **服务端权限位有 3 秒正向缓存上界**（`core/config/open_platform.py:31-35`，默认 3、硬顶 5） | 以为"编辑权限位立刻生效"是零延迟，测试里补勾后立刻验证会偶发失败 | AC-52 的验收留 5 秒余量；CLI 侧零缓存（D3） |
| 17 | **`GET /api/v2/apps/deploy-limits` 取不到时不能挡死发布**（F055 design D2 逐字） | 端点还没上线 / 网络抖动时 `deploy` 直接不可用——一个软校验把主流程打死 | `commands/deploy.py`：取不到 → 用内置默认值只提示、继续上传，由 16201 兜底 |
| 18 | **`GET /api/v2/apps/{id}/logs` 的服务端链路目前是断的——但断点不在 runtime-manager**：manager 侧 `GET /v1/apps/{id}/logs` 批 4 已实现（`contracts-runtime-manager.md` §2 已列为就绪端点），真正缺的是**链路中段** F054 T057（backend 转发）与 F055 T039（权限判定）| 按契约写完 CLI 后在 114 上验不通，误判为 CLI bug 或误以为要等编排器 | `logs` 联调排在 F054 T057 / F055 T039 之后；CLI 侧单测用 mock。manager 侧口径已定：`since` 收 epoch 秒或 `30m/2h/7d`；带 `keyword` 时行数 < `tail` 是设计；dockerd 宕机返 503→`16121`（**不是** 404，404 只表示实例不存在）|
| 19 | **`docker logs` 时间戳是秒级**，`--follow` 用 `since` 续拉时同一秒的行会重复返回 | 日志刷屏重复，看起来像应用在疯狂打同一行（同类坑：memory `project_chat_history_sameSecond_order`） | `commands/logs.py` 按最后 N 行内容哈希去重（D8） |
| 20 | **tar 里丢掉可执行位，上线后 entrypoint 脚本不可执行**，而故障要到构建 / 探活阶段才暴露（16227 / 16228） | 排查方向跑偏到"平台构建有问题"，实际是打包把 `0755` 归一成了 `0644` | `packaging.py` 模式归一时**保留 owner 执行位**（D4） |
| 21 | **`/api/v1/env` 的 `version` 是硬编码 `'2.6.0-fix'`**（`src/backend/bisheng/__init__.py:7`，3.0-vibe 实测） | 拿它做 CLI 与平台的版本比对 → 永远判"不兼容"或永远判"兼容"，两种都错 | 分发端点自带版本真相（D10 / §4.2 ⑤）；CLAUDE.md §7 已列此陷阱 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/dev-toolkit/versions`（§4.2 ⑤，含 `sdk.*` 字段位） | HTTP（**匿名**） | CLI 自身前置探测 · **F057**（SDK 版本与最低兼容版本，AC-01/03 消费同一端点）· 接入信息区（顺延） |
| `GET /api/v1/dev-toolkit/cli/download` | HTTP（**匿名**，`FileResponse`） | 开发者 / 管理员转发的下载链接（AC-01「是链接不是文件」）· 接入信息区（顺延） |
| **CLI 退出码表**（§4.2 ②） | 进程契约 | 本地 coding agent（AC-04 / AC-47 的自动化判定依据）· 114 演示脚本 · 未来 CI |
| **`--json` NDJSON 事件流**（§4.2 ⑥） | 数据契约 | 同上；`result` 恒为最后一行是 agent 可依赖的不变量 |
| **凭据文件格式**（§4.2 ③） | 文件契约 | `dev`（顺延，读同一凭据）· 顺延的多平台管理命令 |
| **`.bisheng/app.json`**（§4.2 ④） | 文件契约 | 团队成员共享同一 `app_id`；`logs` 与迭代 `deploy` |
| `bisheng/dev_toolkit/artifacts/` 布局 + `scripts/pack_cli_wheel.sh` | 构建契约 | 发版流程（wheel 必须在打镜像前拷入）· 顺延的 SDK 与技能包分发复用同一目录与脚本 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| **F055 `POST /api/v2/apps/deploy` / `GET /deployments/{id}` / `GET /deploy-limits` / `GET /{app_id}/logs`**（design §4.2 ①） | HTTP | **CON-5**：路径、入参、载荷字段任一变更 → CLI 当场坏。尤其 `stage` 取值与顺序（D6）、`failure` 五元组（D6）、`pending_reason` 与 `approval.status` 枚举（D7） |
| **F055 的同步段 / 异步段划分**（design §4.1 ① `:411-427`） | 控制流契约 | **归属判定 · 大小闸 · 解包闸 · manifest 校验 · 本地引用校验 · 在途 / 待上线闸全在 `POST /deploy` 的同步响应里**，轮询只能看到 `received` 之后的阶段。若 F055 把某一闸挪进异步段（或反之），CLI 的"哪些 code 走同步分支、哪些走轮询分支"必须同批改（§4.1 B 步 6/7、D6） |
| **F055 `entry_url` 的返回位置** | HTTP | **⚠️ 回写项 3：`entry_url` 只在 `POST /deploy` 的返回里（`055-.../design.md:492`），轮询载荷没有**，且首发时应用是草稿、大概率为 `null` → AC-31c「通过并上线（输出入口地址）」/ AC-33 / 决议-12 只能降级（D7）。请 F055 给 `GET /deployments/{id}` 补 `entry_url`（`app_state=已上线` 时非空） |
| **F055 `secret_scan` 的执行位置**（design D5 挂着一个"提前到构建之前"的**待 ★ 确认偏离**） | 顺序契约 | 若确认提前 → CLI 的 `STAGE_LABELS` 顺序、README 与 **spec AC-31a** 必须**同批**改；不同批 = CLI 打印的阶段顺序与实际不符 |
| **F055 162 段错误码语义**（design §4.2 ⑧ `:588-598`） | 错误码 | **一码一义红线**：`16225`（审批场景未启用，找管理员）vs `16226`（容量不足，等资源）—— F055 早期版本曾把两者写成同码；CLI 的 `ERROR_HINTS` 若跟着写错，用户会按完全错误的方向排障。→ **本文 §4.2 ② 已把二者分成 exit 13 / exit 14 兑现该红线**，落码时不得回退成同一格 |
| **F055 AppManifest 形态**（design §4.2 ③，`extra='forbid'`） | 数据契约（YAML） | CLI 只校验三必填；**CLI 与技能包都不得自造字段**，否则"本地过、上传被拒" |
| **F049 `GET /api/v2/auth/whoami`** + 260 段错误码与真 HTTP 状态 | HTTP | `WhoamiResponse` 若改字段名 → `login` 输出坏；**⚠️ 回写项 1：需 F049 给它加 `resource_owner: {user_id, user_name}`**，否则 AC-06 只能降级（D14） |
| **F049 `open_api_subject("app:manage")` 与 3 秒缓存上界** | 服务端行为 | 缓存上界变化 → AC-52 的验收余量要跟着改 |
| **F049 `whoami` 恒在注册 + 服务账号模块恒在** | 部署形态 | **⚠️ 回写项 4（spec 侧）**：`open_api_v2_router` 挂在 `router_rpc` 上恒在（`api/router.py:123-126`），服务账号模块「恒在、不随 open_platform 开关消失」是 F049 显式设计（`core/config/open_platform.py:17-18` 注释）→ **AC-05 的"login 校验入口不可达"这一半本轮不实现**，CLI 用前置探测在打 whoami 之前退出 8 作等价保证（D10 偏离登记）。建议改 spec 措辞而非改 F049 实现 |
| **F055 `logs` 返回形状** | HTTP | **⚠️ 回写项 2：目前只有 `{lines[]}`，缺 `app_state` / `pending_reason`**，AC-43「明确提示应用态」只能降级实现（D8） |
| **F054 `GET /api/v1/apps/{id}/logs` → runtime-manager `GET /v1/apps/{id}/logs`** | 服务端链路 | manager 段**已实现**（批 4 `d693feeb3`）；缺的是中段 **F054 T057 + F055 T039** → `logs` 联调排在这两条之后（坑 18） |
| **F054 `contracts-runtime-manager.md` §5 注入环境变量清单** | 数据契约 | `bisheng dev` 顺延，但**将来必须同名注入**：`BISHENG_APP_DB_URL` · `BISHENG_APP_DB_PATH` · `BISHENG_APP_ID` · `BISHENG_APP_SLUG` · `BISHENG_APP_VERSION` · `BISHENG_APP_VERSION_ID` · `BISHENG_PLATFORM_API_BASE` · `PORT` 与 `BISHENG_APP_PORT`（恒等）· `BISHENG_APP_BASE_PATH`（dev 期为空串）· `BISHENG_APP_HEALTH_PATH`。**清单唯一来源是该文件，不得在 CLI 侧另抄一份定义**；平台保留 env 名**覆盖**调用方同名值 |
| **平台 `settings.open_platform.enabled` / `settings.app_runtime.enabled`** | 部署配置 | 进程级 YAML；`load_settings_from_yaml` 对未知顶层键 `raise KeyError`（`common/services/config_service.py:107`）→ **先发代码、再改 YAML、最后重启** |
| `bisheng/api/router.py` 的 include 顺序 · `TENANT_CHECK_EXEMPT_PATHS` | 注册点 | 漏加豁免 → 多租户环境下端点一旦读表即 `NoTenantContextError`（D10） |
| nginx `client_max_body_size 1024m` / `proxy_read_timeout 300s`（`docker/nginx/conf.d/default.conf:60,53`；114 上是 `/etc/nginx/conf.d/bisheng-lilu.conf`） | 基础设施 | 上传超时取 240 s 是**贴着 300 s 定的**，改任一个要同时看另一个（D5 / D7） |
| `httpx` · `PyYAML`（客户内网 pip 镜像） | 第三方依赖 | 装不上 = CLI 装不上；引入第三条依赖必须在 D12 补论证 |

---

## 7. 测试与可观测

**分层策略**（CLI 是独立工程，测试也独立跑：`cd src/bisheng-cli && uv sync && uv run pytest`）

- **单元测试（默认全跑，零网络）**——CLI 的价值密度几乎全在这一层：
  - 忽略规则矩阵：`**` / 前导 `!` / 目录后缀 `/` / 段内 `*` / `.bishengignore` 覆盖 `.gitignore`；git 路径与子集解析器**跑同一份样本目录并断言结果一致**（坑 9）。
  - 打包断言：`.venv/` `node_modules/` `.git/` 不在包内；**凭据文件绝不在包内**（AC-07 的 assert 型测试）；成员路径无 `\`、无绝对路径、无 `..`（坑 4）；符号链接被跳过且被列出（坑 14）；可执行位保留（坑 20）；两次打包 sha256 相同（可复现）。
  - 错误翻译：`ERROR_HINTS` 逐条一个用例，断言输出**不含任何密钥子串**（AC-04）；未登记 code 走降级分支不抛异常。
  - 退出码映射：§4.2 ② 每一行一个用例；**额外三组必测**：① `16225` → 13 与 `16226` → 14 **断言不同码且下一步文案不同**（D9 红线 1）；② `POST /deploy` 的同步错误体（16221 / 16203 / 16251…）走同步分支并终止，**断言不进轮询循环**（D6）；③ 未登记 code → exit 19 且原样打印 code。
  - `--wait` 终态机：`rejected` / `withdrawn` / `cancelled` / `exception` / `app_state=已上线` / `pending_reason` 各一个 mock 轮询序列，**断言 `cancelled` 与 `exception` 立刻结束（24 / 25）而不是等到超时 23**（D7）。
  - 轮询 `stage` 全枚举（含首条 `received`）都能翻译或原样打印，**断言 `received` 不落进未知兜底**（D6）。
  - 凭据：`0600` / 目录 `0700`（POSIX）；不写 `scopes`；同平台重复 login 覆盖。
  - `delegate` 拒绝：**只能用 mock `whoami` 响应**（坑 15）。
  - 信封两解：`/api/v1` HTTP200+信封 与 `/api/v2` 真状态码各一组（坑 12）。
- **`@pytest.mark.network`（默认跳过，CI 不跑、114 手验跑）**：打真平台的 `versions` / `whoami` / `deploy-limits`。marker 形态照 `src/runtime-manager/pyproject.toml:32-39` 的 `docker:` marker。
- **平台侧端点**：`src/backend/test/dev_toolkit/test_distribution_api.py`——匿名可达、`open_platform.enabled=false` 时 404（**断言是路由不存在，不是错误码**）、`FileResponse` 的 `Content-Disposition` 与 `Content-Length`、多租户开启且无 JWT 时不抛 `NoTenantContextError`。
- **CI**：仓内 CI 目前**不跑** runtime-manager / app-proxy 的任何测试（`.github/workflows/{ci,test,release,base_ci}.yml` 零命中）。CLI 至少要把 `ruff check` + `pytest -m "not network"` 接进 `frontend-quality.yml` 同级的一个新 job，否则它会和 runtime-manager 一样长期无人验证。

**114 手动验证**（对应 `mvp-114-path.md` §1 演示剧本步 2–3；⚠️ 部署用 `bash /opt/bisheng-ops/deploy.sh`，不要 rsync）

```bash
# 0. 平台侧：确认开关与端点（匿名，无需密钥）
curl -s http://<114>/api/v1/env | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["data"]["open_platform_enabled"], d["data"]["app_runtime_enabled"])'
curl -s http://<114>/api/v1/dev-toolkit/versions          # 开关关 → 404（这就是 AC-05 的验证）
# 1. 装 CLI（两条路径都要验）
curl -sO http://<114>/api/v1/dev-toolkit/cli/download && pip install ./bisheng_cli-3.0.0-py3-none-any.whl
bisheng --version
# 2. login（key 来自演示剧本步 1 签发的 bs-sak-…，勾了 app:manage）
BISHENG_API_KEY=bs-sak-… bisheng login http://<114>
ls -l ~/.bisheng/credentials.json                          # 必须是 -rw-------
# 3. deploy（表单问卷小应用：python3.11 + bisheng-app.yaml）
bisheng deploy --dry-run                                   # 先看打包体量与忽略统计
bisheng deploy --wait --json | tee deploy.ndjson; echo "exit=$?"
tail -1 deploy.ndjson | python3 -m json.tool               # result 行
# 4. logs
bisheng logs --tail 200
```
- **AC-42（owner-only）必须用第二把「资源归属人不同」的密钥验证**，不能用同一把——同一把永远通过，测了等于没测。
- **⚠️ `health 200` 会骗人**（admin 短路 ReBAC，memory `reference_remote_dev`）：CLI 的所有权限相关判定都走服务账号（非 admin），但**平台侧任何用浏览器 admin 账号做的旁证都不算数**。
- **失败面演练**：把 `bisheng-app.yaml` 的 `runtime` 改错验 16222；塞一个含 `bs-sak-` 字面量的文件验 16241（**断言输出里没有那个值**）；把 `.venv/` 造大验超限报告。

**可观测**：CLI 无服务端日志。`--verbose` 打请求方法 / 路径 / HTTP 状态 / 耗时，**Authorization 头恒掩码**（AC-04）。服务端侧的观测走 F055 的 `app_deployment` 表与 `app.release.*` 审计事件——排障时"CLI 说失败了"要以 `deployment_id` 去那两处对账，而不是只看终端输出。

---

## 8. 后续改进 / 不打算做的事

**必须回写上游的四项**（已在 §6.2 登记，tasks 里各一条任务）：
1. **F049 给 `WhoamiResponse` 加 `resource_owner: {user_id, user_name}`**——否则 AC-06 只能降级（D14）。
2. **F055 给 `GET /api/v2/apps/{id}/logs` 的返回补 `app_state` / `pending_reason`**——否则 AC-43 只能降级（D8）。
3. **F055 给 `GET /api/v2/apps/deployments/{id}` 的轮询载荷补 `entry_url`**（`app_state=已上线` 时非空）——目前它只在 `POST /deploy` 的返回里、首发时大概率为 `null`，否则 AC-31c「通过并上线（输出入口地址）」/ AC-33 / 决议-12 只能降级为"指路应用详情页"（D7）。
4. **F053 spec 的 AC-05 措辞**——「login 校验入口在开放能力层未部署时不可达」与 F049「服务账号模块恒在 + `whoami` 恒在注册」的既成实现冲突（D10 偏离登记）。建议把该半句改成「CLI 的 `login` 在该环境不可用并给出可读原因」，由前置探测 + exit 8 兑现；**改 spec 而不是改 F049**。
（另有一项由 F055 侧发起、F053 只需接受：F055 tasks T050 回写项 3 已登记「AC-32 的上限经 `deploy-limits` 取、取不到由 16201 兜底」——**本文 §D4 已按该口径写，不要另立一套**。）

**顺延波次的落点**（§1 非目标表已给方向，此处只补优先级）：`skills sync` + 两包技能包（优先级最高，它是 AC-47「agent 全程不离开本地对话」的前提）→ 接入信息区（前端，低成本）→ 版本兼容阻断（一行 warning 升 error）→ `dev`（最重，依赖 F054 app-proxy 与 F057 SDK）→ 多平台管理命令 → 单文件二进制。

**已知短板，暂不投入**：
- **无 shell 补全、无彩色输出**——D2 的依赖预算取舍，客户明确要求前不做。
- **`--follow` 是短轮询不是流**——服务端无流式接口（坑 18），有了再改。
- **CLI 不做本地密钥预扫**——spec 决议-2：同一规则集分两处必漂移，扫描只在 F055 服务端做一次。**这条被提议过不止一次，不要再提**。
- **不提供 `logout` / `whoami` 子命令**——spec §范围边界：登出 = 删凭据文件或重新 `login` 覆盖；`whoami` 的信息已在 `login` 输出里。
- **不提供 `init` / 工程骨架生成**（PRD-1 DEV-04「命令数刻意收在最少」）、**不提供 `--as`**（PRD-1 §5.1 / INV-32）、**不提供撤回命令**（撤回只在应用详情页·发布做，AC-37）、**不生成二维码**（spec 决议-12）。
- **不做分片上传 / 断点续传**——D5，50 MB 上限下是过度设计。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-17 | 初版（14 决策 / 21 坑）。按 `mvp-114-path.md` §6 MVP-核心裁剪：只做 CLI 包工程 + `login` + `deploy` + `logs` + 平台分发端点；顺延项在 §1 与 §8 留落点。上游契约逐条贴 F055 design §4.2 / F049 已实现鉴权面 / F054 `contracts-runtime-manager.md` §5 | 探查笔记 `f053-notes/e1-cli-packaging-and-endpoints.md` + spec 55 AC |
| 2026-08-17 | **评审修订（12 条，2 high / 6 medium / 4 low）**：① **`deploy` 控制流按 F055 同步 / 异步段重建**——归属判定 · 大小闸 · 解包闸 · manifest 校验 · 本地引用校验 · 在途 / 待上线闸全部改挂 `POST /deploy` 的同步响应（`055-.../design.md:411-427`），轮询只保留 `received` 之后的阶段（§4.1 B 步 6/7、D6、§6.2 新增一行）；② **`entry_url` 取值缺口登记为回写项 3**——它只在 `POST /deploy` 返回、轮询载荷没有，`--wait` 上线分支改为"有则回显、无则指路应用详情页"的降级（D7 / §4.1 B 8b / §4.2 ⑥⑦ / §8）；③ **`stage` 改用 F055 权威枚举 11 值**（`:86`），`approval_created` 不再写成中文、补 `received` 等六个漏项（D6）；④ **退出码表重排**——`16225`→13 与 `16226`→14 拆开兑现 F055 一码一义红线，补 `16201/16202/16203/16223/16224/16230/16231/16254` 映射、新增 exit 9（平台版本过老）与 exit 19（未登记 code 降级）（§4.2 ② / D9 / §4.1 A）；⑤ **`--wait` 终态补 `cancelled`（24）与 `exception`（25）**——否则应用被删或审批人为空时死等到超时（D7 / §4.2 ⑦）；⑥ **`--platform` 本轮不注册**，与 §1 非目标表和裁剪基准对齐，只保留多 profile 数据结构（§1 / D11 第 5 条 / §4.2 ①）；⑦ **AC-05 的"login 校验入口不可达"登记为显式偏离 + 回写项 4**——`whoami` 挂 `router_rpc` 恒在、服务账号模块恒在（`api/router.py:123-126`、`open_platform.py:17-18`），CLI 用前置探测退出 8 作等价保证（D10 / §6.2 / §8）；⑧ **`dist/` `build/` 从硬排除降为软排除**——真实应用会带前端构建产物，硬排 = 静默截断（D4）；⑨ 坑 10 订正为 **RULE-7 是 WARNING 不是 VIOLATION**（`arch-guard.sh:99` / `:13`，§2 同改）；⑩ 行号订正 `clear_minio_share_host:686`（docstring `:687-691`）、`ci.yml:54`；⑪ §1 补「与裁剪基准的两处显式偏离」表（`login` 拒 `delegate` / `--confirm-schema-change` 本轮提前做及其理由）；⑫ §7 补三组新增单测（同步 / 异步分支路由、13 vs 14 不同码、`cancelled` / `exception` 不等超时、`received` 不落兜底）。**未采纳 1 项**：`config_service.py` 的 `raise KeyError` 实测在 **`:107`**（`sed -n '104,110p'` 核实），原文引用正确，评审建议的 `:108` 有误 | design 评审 12 条 ISSUE 逐条处理 |

---

<!-- self-check -->
<!--
按 .claude/skills/sdd-review/references/design-checklist.md 24 项自检（2026-08-17，写手自检）：

已满足：1,2,3,4,5,6,7,8,9,10,11,13,14,15,16,17,18,19,20,21,22,23

未完全满足 / 需知悉：
- 第 12 项（与 spec §5-§7 的实际实现一致）：**本 Feature 尚未开工**，本文是"要建成的样子"而非现状快照；spec §5 是指针表、无内容冲突。实现后须按现状覆盖本文（文首已声明）。
- 第 24 项（反映 tasks.md 的实际偏差记录）：**tasks.md 尚未编写**，无偏差可反映。tasks 落笔后若出现偏差需回补本文。
- 第 4 项的 Constitution Check 补充说明：CLI 是 `src/backend/` 之外的独立工程，C1–C7 与 arch-guard 仅作用于本 Feature 的平台侧两个端点（§2 CON-7/CON-8 已声明）；**F053 不申请错误码模块编码段**，C5 的"新增错误码须同批回写 constitution 表"在本 Feature 不触发。

四项跨 Feature 阻塞 / 偏离（已在 §6.2 / §8 登记，非本文缺陷）：
- AC-06 的"资源归属人"待 F049 给 whoami 补字段，在此之前降级（D14）。
- AC-43 的"提示应用态"待 F055 给 logs 返回补 app_state，在此之前降级（D8）。
- AC-31c / AC-33 的"输出入口地址"待 F055 给轮询载荷补 `entry_url`，在此之前降级为"指路应用详情页"（D7，回写项 3）。
- AC-05 的"login 校验入口不可达"与 F049「服务账号模块恒在」的既成实现冲突，本轮不实现、以 CLI 前置探测 exit 8 作等价保证，建议改 spec 措辞（D10，回写项 4）。
-->
