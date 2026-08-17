# Tasks: 开发者 CLI 与技能包（独立 `bisheng` CLI 包 + 平台分发端点）

**关联规格**: [spec.md](./spec.md)（55 条有效 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D14 / 坑 1–21 / §4.1 数据流 / §4.2 契约 / §6 依赖 / §8 回写四项）
**版本**: v3.0.0
**纵切**: [mvp-114-path.md](../mvp-114-path.md) **§6 MVP-核心**（预算受限版，本轮裁剪基准）——**Wave 1–2 全部标 `[MVP-核心]`**（CLI 包工程 + `login` + `deploy` + `logs` 简版 + 平台分发端点）；**Wave 3–5 为 release 必做但本轮顺延**（`skills sync` 与两包技能包 / `dev` / 接入信息区 / 多平台凭据交互层 / 版本兼容阻断），只列标题 + 文件 + 覆盖 AC，不展开逻辑。
**§6 字面读法的三处显式偏离**（①② 见 design §1「与裁剪基准的两处显式偏离」表，③ 为 2026-08-17 tasks 审查补记的计数订正，三处均非漏读）：① **`login` 拒 `delegate` 本轮就做**（T019/T020）——INV-31 要求「三面在通道入口按权限位直接拒绝」而 CLI 是唯一通道入口，实现量 = 一个 `in` 判断 + 一条文案 + 一个 mock 单测，不做反而要在 spec 里挂长期偏离；② **`--confirm-schema-change` 参数本轮就实现**（T021/T022）——参数存在与否是 CLI 的对外契约，现在不做将来要改 CLI + README 两处；③ **多平台凭据的「数据结构」本轮就落**（T012）——§6 把「多平台凭据」整条列在顺延列，但 design §1 非目标表与 D3 明写「结构本轮就落、`--platform` 交互层顺延」（结构写死成单平台，将来加多平台就是一次带迁移的破坏性变更）；**顺延的只有交互层**（T047），实现量 = 顶层一层 dict。
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe`，2026-08-17 核实；后端路径以 `src/backend/bisheng/` 为根，CLI 路径以 `src/bisheng-cli/` 为根）。**行号会漂移、符号名不会——落地前一律以符号名重定位。**

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 初稿 + 同日独立审查 13 项就地修订，55 条有效 AC 定稿（决议 1–12） |
| design.md | ✅ 已评审 | 2026-08-17 初版 + 同日评审 12 条修订（D1–D14 / 21 坑）；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-08-17） | 本文；**50 任务 / 5 Wave / 35 条 `[MVP-核心]`**；55 条 AC 全覆盖（AC-39 为墓碑、AC-48 / AC-50 为跨 Feature 旅程引用，见追溯表）；**+ 同日 `/sdd-review tasks` 14 条修订**（2 high：F054 `logs` 链路事实回正〔runtime-manager 端点已落码〕· 依赖上界与 wheel 安装冒烟〔app-proxy 生产事故同型敞口〕；9 medium：161 段错误码登记 · 未登记码按 HTTP 状态兜底 · `26002` 三成因不可分 · `data.required` 是字符串 · base_url 归一化 · T022/T026 伪依赖 · T002 拆 T002a · 产物缺失时端点行为 · F055 扫描顺序偏离进依赖表；3 low：偏离计数补第三处 · CI 改 `--frozen` · T031 落点改独立 workflow 文件） |
| 实现 | 🚧 进行中 | **19 / 50 完成**（Wave 1 全部：T001–T018 含 T002a；落点 `src/bisheng-cli/`，`uv run pytest` **135 passed / 0 failed**、`ruff check` 全绿、wheel 构建 + 干净 venv 安装冒烟通过）。Wave 2 未开工。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

**按 Wave 组织任务**：
- **Wave 1**（T001–T018，含 T002a）= `[MVP-核心]` **CLI 包工程 + 测试基建 + CLI 内核**（errors / output / http / 入口 / 凭据 / 项目层 / 忽略规则 / 打包）。T001 / T002 / T002a 是基础设施、无测试配对、排最前；T003 起全部 Test-First 成对。
- **Wave 2**（T019–T034）= `[MVP-核心]` **三条命令（`login` / `deploy` / `logs`）+ 平台分发端点 + 打包脚本 + CI + README + 114 手动验证 + 上游回写四项**。
- **Wave 3–5** = release 必做、本轮顺延（design §8 的优先级顺序：`skills sync` + 两包技能包 → 接入信息区 → 版本兼容阻断 → `dev` → 多平台管理命令）。**只列标题 + 文件 + 测试载体 + 覆盖 AC**，展开在开工那一刻做。

**执行序 = 任务编号序**（本 Feature 无 F055 那样的跨 Wave 拓扑倒挂）：Wave 1 内 T001/T002/T002a 可与任何测试任务并行落盘，实现任务一律按 `依赖:` 行排；Wave 2 的三条命令彼此独立，可三路并行（`login` / `deploy` / `logs`），平台侧 T027–T031 与 CLI 侧完全并行。
> ⚠️ **三条命令之间没有依赖**（2026-08-17 审查订正）：它们共享的是 `http.py`（T008）· `credentials.py`（T012）· `project.py`（T014），**不是 `login` 命令本身**。`deploy` / `logs` 的 `依赖:` 行**不写 T020**——写了会把"三路并行"变成一条串行链，而 `login` 的实现里没有任何 `deploy` / `logs` 要复用的产出（鉴权客户端构造在 `http.py`，凭据载入在 `credentials.py`）。

**Test-First（CLI 版）**：测试任务先于其配对的实现任务，`覆盖 AC` **逐条列举**（禁 `AC-01~AC-05` 范围写法）。
- **CLI 单测一律零网络**：所有平台交互经 `httpx.MockTransport` 或 `tests/helpers/platform_mock.py`（T002a）的响应工厂构造，**不连任何真平台**（T002 的 `no_network` autouse fixture 把 `httpx.Client` 的默认 transport 换成会抛异常的哨兵，漏 mock 当场失败而不是静默走网络）。
- **需要真平台的用例**统一挂 `@pytest.mark.network`，**默认跳过、CI 不跑、只在 114 手验跑**（marker 形态照 `src/runtime-manager/pyproject.toml:32-39` 的 `docker:` marker）。
- 测试目录 `src/bisheng-cli/tests/`，与包同仓不同工程：`cd src/bisheng-cli && uv sync && uv run pytest`。**不放进 `src/backend/test/`**——CLI 不 import `bisheng`（CON-1）。
- 平台侧两个端点的测试是唯一落 `src/backend/test/` 的部分：`src/backend/test/dev_toolkit/`（不放 `test/` 根，`asyncio_mode=auto`）。

**自包含任务**：每个任务内联文件、逻辑、依赖、AC 覆盖；设计论证指向 design §X / D-x / 坑-x，**不复制**（避免第三处漂移）。

**⚠️ 本 Feature 只有 T028 / T029 / T030 / T031 改 `src/backend/` 与仓库共享文件，其余全部落全新目录 `src/bisheng-cli/`**。冲突面见下方「跨 Feature 副作用登记」。

**⚠️ 三条实现红线（落码前逐条对照，全部来自 design 的评审修订）**：
1. **同步段 / 异步段不得混淆**（D6 / §4.1 B 步 6-7）：`POST /api/v2/apps/deploy` 的**同步响应**里已经跑完「归属判定 · 大小闸 · 解包闸 · manifest 校验 · 本地引用校验 · 在途单 / 待上线闸」（F055 design §4.1 ① `:411-427`），**首发最常见的失败（manifest 缺字段 = 16221）永远不会出现在轮询里**。CLI 若"等一个 `stage=precheck_manifest` 的失败事件"，等到的是超时。
2. **`16225` 与 `16226` 绝不同码**（D9 红线 1）：前者「平台没 seed 审批场景，找管理员，改代码无用」→ exit 13；后者「机器没资源，等一会儿或让 owner 手动上线」→ exit 14。
3. **`--wait` 必须认 `cancelled` / `exception` 两个异常终态**（D7）：不认 = 应用被删或审批人为空时死等到 `--wait-timeout` 再打印"这不是失败，请继续等"，而真实情况是这单已经死了。

**⚠️ 两处"本轮无法端到端验证、只能单测"的地方，实现者不要去 114 上试然后判定功能不生效**：
- **`delegate` 拒绝（AC-09 / AC-13）**——该位在 F049 期**根本签不出来**（`open_api/domain/scopes.py:186-188` 的 NOTE 逐字："deliberately NOT registered … ships with F050"，坑 15）→ 只能用构造 mock `whoami` 响应的单测覆盖。
- **`logs` 的服务端链路（AC-41 / AC-43）**——⚠️ **2026-08-17 审查事实回正**：坑 18 与 design §6.2 写的「runtime-manager 的 logs 端点尚未实现」**已过时**——F054 **T030/T031 已完成并落码**（commit `d693feeb3`「F054 批 4——reconciler 自愈与三个只读端点」；`contracts-runtime-manager.md` §2 已把 `GET /v1/apps/{app_id}/logs?tail=&since=&keyword=` → `{lines: []}` 列进「已就绪端点」并注明消费方含 **F053 CLI `logs`**，§8 标题逐字写「批 4，T028–T031 已实现」；原引用的 `:64` 行号现指向 §6，勿再照抄）。**现在真正缺的是链路中段的两截**：F054 **T057**（backend `GET /api/v1/apps/{app_id}/logs` 只读 API，tasks 仍 `[ ]`）与 F055 **T039**（`GET /api/v2/apps/{app_id}/logs` 转发 + `app:manage` + 归属人判定）。→ CLI 侧单测照常用 mock；114 联调排在 **F054 T057 → F055 T039** 之后（不再是"等 runtime-manager"）。**顺带可用的两条实测口径**（manager 已实现，写单测时按它对齐）：`since` 接受 **epoch 秒或 `30m`/`2h`/`7d` 相对窗口**，不可解析 → 400；**带 `keyword` 时返回行数可能 < `tail`**（manager 内过滤，这是设计不是 bug）。

**跨 Feature 依赖（签名 / 契约变更须回头改本文）**：
| 依赖方 | 具体任务 / 已落码 | 本文哪些任务会当场坏 |
|---|---|---|
| **F049（已实现，commit `43e73bfc5`）** | `GET /api/v2/auth/whoami`（`open_api/api/endpoints/auth.py:19-50`，`/api/v2` 下唯一 `@open_api_scope(None)`，`auth.py:23`）· `WhoamiResponse`（`open_api/domain/schemas/credential.py:108-116`）· 260 段错误码与真 HTTP 状态 · `settings.open_platform.enabled`（`core/config/open_platform.py:16-20`） | T019/T020（`login`）· T007/T008（信封解析与探测）· T028（条件注册） |
| **F055 T039**（`/api/v2/apps` router + 四端点实现） | `POST /apps/deploy` · `GET /apps/deployments/{id}` · `GET /apps/deploy-limits` · `GET /apps/{app_id}/logs`；**同步段 / 异步段划分**（F055 design §4.1 ① `:411-427`）；`stage` 11 值枚举与 `status` 四值（`055-.../design.md:86`）；失败五元组 `{stage,code,message,details,hints[]}`；162 段错误码语义 | T021–T026（三条命令的全部平台交互）· T003/T004（`ERROR_HINTS`） |
| **F055 T050**（上游回写三项） | 「AC-32 的上限经 `deploy-limits` 取、取不到由 16201 兜底」已在其回写项 3 登记——**本文 T017/T021 按该口径写，不另立一套** | T017/T018 · T021/T022 |
| **F054 T030/T031**（runtime-manager 只读接口 status / logs） | ✅ **已实现**（commit `d693feeb3`，`contracts-runtime-manager.md` §2 已列为已就绪端点）——坑 18 的"未实现"口径**已过时**；`logs` 的链路终点形状 = `{lines: []}`，`since` 收 epoch 秒或 `30m`/`2h`/`7d`，`keyword` 在 manager 内过滤（**带 keyword 时行数可 < tail**）；dockerd 不可达返 **503 → backend 映射 `16121`**（非 404） | T025/T026 的 `since` 入参形态与 `16121` 分支（**不是**"等它实现"） |
| **F054 T057 + F055 T039**（链路中段：backend `GET /api/v1/apps/{app_id}/logs` 与 v2 转发端点） | **两者仍未实现**——`logs` 的 114 联调排在它们之后（单测不受影响） | T025/T026 的 114 联调 · T033 步 4 |
| **F055 design D5**（`secret_scan` 相对 `precheck_*` 的顺序，挂着**待 ★ 确认的偏离**） | 该 ★ 若确认"扫描提前到构建之前"，`STAGE_LABELS` 的展示顺序、README §④ 与**本 spec AC-31a 的字面顺序**必须**同批**改（design §6.2 已登记） | T023（阶段顺序说明）· T024（`STAGE` 常量）· T032（README） |
| **F057** | 消费 **同一个** `GET /api/v1/dev-toolkit/versions` 端点的 `sdk.*` 字段位（AC-01 / F057 AC-01·AC-03） | T028（字段位本轮一次留够，值为 `null`；不留就会在 F057 期出现第二个端点或破坏性改形） |

**跨 Feature 副作用登记**（release-contract 表 1 / 清单检查项 17）：
- **T028**（`bisheng/api/router.py` 挂新 router）—— **与 F054 T035/T057（挂 `app_runtime` router）、F055 T039/T041（挂 `app_publish` router）改同一文件的同一片区域（`:66-112`）**。三方都是**纯追加一行 `include_router`**，无逻辑耦合；合并冲突是文本级的，**解冲突时三行都要保留**。本任务的 include 是**条件的**（`if settings.open_platform.enabled:`），与另两方的无条件 include 形态不同，review 时不要"顺手统一"。
- **T029**（`bisheng/utils/http_middleware.py` 的 `TENANT_CHECK_EXEMPT_PATHS`，`:16-44`）—— 追加一条前缀 `/api/v1/dev-toolkit`。该元组也被 F054 的 app-proxy 相关任务读到（同文件 `:60-73` / `:263-279` 的解 JWT 与租户播种逻辑，F054 K7 明确"本地解 JWT 会绕过它们"），**但 F054 不写这个元组**，冲突面只在文本相邻行。
- **T031**（`.github/workflows/cli-quality.yml` **新建独立 workflow 文件**）—— 冲突面为零：不改任何既有 workflow（既有 `ci.yml` 的 backend 镜像构建 `:51-54` 与 `frontend-quality.yml` 一律不碰）。
- **T030**（`scripts/pack_cli_wheel.sh` 新增 + 产物落 `bisheng/dev_toolkit/artifacts/`）—— **构建契约**：wheel 必须在打后端镜像前拷入并**提交进 git**（backend 镜像 build context 只有 `./src/backend/`，`ci.yml:54` + `src/backend/Dockerfile:13`，坑 11）；顺延的 SDK 与技能包分发复用同一目录与脚本。
- **T034**（回写 F049 / F055 / 本 spec 四项）—— 只追加文档条目，不改他人代码。

---

## Tasks

### Wave 1 · `[MVP-核心]` 包工程与测试基建（无测试配对，排最前）

- [x] **T001**: `[MVP-核心]` CLI 包工程骨架（全仓第一个可发布包工程）
  **文件**: `src/bisheng-cli/pyproject.toml`（新）, `src/bisheng-cli/bisheng_cli/__init__.py`（新）, `src/bisheng-cli/uv.lock`（新，`uv lock` 生成后**提交进 git**，同 `src/runtime-manager/uv.lock` / `src/app-proxy/uv.lock`）
  **逻辑**: 照抄基准 = `src/runtime-manager/pyproject.toml`（仓内最新的独立包先例，D1）。`[project]` name=`bisheng-cli`、version=`3.0.0`（与平台版本同号，决议-7）、`requires-python = ">=3.11"`（与 `runtime-manager/pyproject.toml:1-16` 对齐，CON-6）；`dependencies = ["httpx>=0.27,<1.0", "PyYAML>=6.0,<7.0"]` —— **依赖预算就这两条**（D12，引第三条必须先在 design D12 补一行论证），且**两条都必须带上界**（见下方 ⚠️）；`[project.scripts] bisheng = "bisheng_cli.main:main"`（**全仓第一条 console script**）；`[build-system]` hatchling + **`[tool.hatch.build.targets.wheel] packages = ["bisheng_cli"]`**（⚠️ 目录名带连字符时 hatchling 无法自动推断包目录，**缺这一行 `uv build` 打出的是空 wheel**，D1）；`[tool.ruff]` 照抄 `runtime-manager/pyproject.toml:41-67` 但**必须 ignore `RUF001/RUF002/RUF003`**——CLI 的人读输出全是中文，不 ignore 会把全角括号"修"成 ASCII、改错产品文案；`[tool.pytest.ini_options]` 照 `:32-39`，自定义 marker 由 `docker:` 换成 **`network:`**（"needs a real platform — skipped by default, runs only in the 114 manual verification"）。`__init__.py` 只放 `__version__ = "3.0.0"`（**单一版本真相**，`--version` 与 T030 的 `manifest.json` 都读它）。
  **三个名字刻意分离**（D1，两条理由都不是洁癖）：发行名 `bisheng-cli` · import 包名 **`bisheng_cli`** · 命令名 `bisheng`。① import 包若取名 `bisheng`，开发者机器上同时装了后端依赖时与 `src/backend/bisheng/` 顶层包**同名冲突**；② `arch-guard.sh:115,126` 的 RULE-8/9 守卫条件是 `grep -q "/bisheng/"`，目录里出现 `bisheng/` 段会被扫进来产生无谓噪声。
  **⚠️ 只有下界的依赖会在生产炸、且 CLI 的敞口比其它子工程更大**（2026-08-17 审查新增，本轮真事故）：app-proxy 的 `fastapi>=0.115` 在开发机解析到 0.121 时测试全绿，生产 `uv sync` 解析到 0.141 后 `uvicorn` **模块级 import 当场崩** —— 单测全过、部署即死。**三件套缺一不可**：① `pyproject.toml` 两条依赖都写上界（上面已给）；② `uv lock` 产物**提交进 git**，CI 与 114 一律 `uv sync --frozen`（照 `src/backend/Dockerfile:7` `uv sync --frozen --no-dev` 的仓内既定口径）；③ 打包脚本自带**装 wheel 后 import 生产入口**的冒烟（T030）。**为什么 CLI 比 runtime-manager / app-proxy 更需要上界**：那两个是仓内进程、`uv.lock` 在部署路径上真的生效；**CLI 的分发路径是开发者机器上的 `pip install <wheel>`，lock 在那条路径上完全不参与解析**——能约束它的只有 wheel metadata 里的这两条上界。**放宽上界是一次显式决定**（跑通 T030 冒烟 + T031 的 highest-resolution leg 后再改），不是顺手升。
  **⚠️ 产物目录命名禁区**（坑 11）：`.gitignore:137,148,150,152` 的 `build/` `lib/` `wheels/` `sdist/` 是**无前导斜杠的全局规则**，任何层级同名目录都被忽略；`src/bisheng-cli/dist/` 不受影响（`/dist/` 是根锚定的）。T030 的落点 `bisheng/dev_toolkit/artifacts/` 这个名字是刻意挑的，**不要改名**。
  **依赖**: 无

- [x] **T002**: `[MVP-核心]` pytest 基建之一：零网络哨兵 + 家目录隔离 + 样本项目树
  **文件**: `src/bisheng-cli/tests/conftest.py`（新）, `src/bisheng-cli/tests/fixtures/`（新，样本项目素材）
  **逻辑**: fixtures：
  - **`no_network`（autouse）**——把 `httpx.Client`/`httpx.AsyncClient` 的默认 transport 换成会 `raise AssertionError("unmocked network call")` 的哨兵，**漏 mock 当场失败而不是静默走网络**；同时清 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY` env（缺 `socksio` 会整批误报，memory `reference_local_backend_pytest_socks_proxy`；且坑 2 的代理提示逻辑要在受控 env 下测）。
  - **`home_dir`**——`monkeypatch` `Path.home()` 到 tmp_path，凭据读写全落临时目录（POSIX 下可直接断言 `0600`/`0700`）。
  - **`sample_project` / `sample_project_git`**（`tests/fixtures/`）——最小应用树：`bisheng-app.yaml`（`name`/`runtime: python3.11`/`port`）+ `main.py` + `requirements.txt` + 噪声目录 `.venv/`、`node_modules/`、`__pycache__/`、`dist/`（软排，D4）、`.gitignore`、一个符号链接、一个 `0755` 脚本、一个 `*.sqlite`。`sample_project_git` 版本额外 `git init && git add`（**用例内先探测 `git` 可执行，缺 git 则 `pytest.skip`**——CI 有 git，开发者机器不保证）。
  **⚠️ 测试里绝不写长密钥字面量**（坑 10）：`arch-guard.sh:96-100` 的 RULE-7 会扫到 CLI 的 `.py`（`(password|secret_key|api_key|access_token)\s*=\s*['"][^'"]{8,}['"]`）。它输出的是 **WARNING、不是 VIOLATION、不阻断**（`arch-guard.sh:99` / 脚本头注释 `:13`），但长期噪声会让真的硬编码密钥那天没人看 —— 一律用 fixture 常量 `FAKE_KEY = "bs-sak-" + "x" * 8` 这类拼接形式，让 RULE-7 在本工程保持零输出。
  **依赖**: T001

- [x] **T002a**: `[MVP-核心]` pytest 基建之二：mock 平台响应工厂（本 Feature 对 F049 / F055 契约的可执行快照）
  **文件**: `src/bisheng-cli/tests/helpers/platform_mock.py`（新）
  **逻辑**: 基于 `httpx.MockTransport` 的响应工厂，可编程：`versions_ok()` / `versions_404()` / `env_ok(open_platform_enabled=…)` / `env_unreachable()` / `whoami_ok(scopes=[…], resource_owner=…|None)` / `whoami_err(code, http_status=…)` / `deploy_accept(...)` / `deploy_sync_err(code, details=…)` / `deployment_seq([...])`（一串轮询响应，按调用次序返回）/ `logs(lines=[…])`。**响应体形状必须照 design §4.2 ⑦ 的 F055 契约逐字构造**（`stage` 用服务端原值、`failure` 五元组、`approval.status` 六种取值），**不得在 helper 里"顺手规整"字段名**——helper 就是本 Feature 对上游契约的可执行快照。
  **两套信封工厂**：`v1_envelope(data)`（HTTP 200 + `{status_code,status_message,data}`）与 `v2_error(http_status, code, message, data=…)`（真 HTTP 状态 + 信封 body），对应坑 12。
  **⚠️ 260 段错误体照 F049 已落码的形状构造**（`common/errcode/base.py:29-33` `return_resp_instance`）：`data = {"exception": <str>, **kwargs}`，所以 `26003` 的载荷是 **`data.required` = 单个字符串**（`OpenApiScopeMissingError(required: str)`，`common/errcode/open_api.py:63-68`）**不是数组**；HTTP 状态取各错误类的 `http_status`（`26001`/`26002`/`26027` → **401**，`26003`/`26004` → **403**，`26030` → **503**，`26031` → **500**，`test/open_api/test_open_api_auth_api.py:67-149` 逐条实测）。**工厂里不许自造更"合理"的形状**——真实的形状就是这个，改了等于把 CLI 测成对着一个不存在的服务端编程。
  **依赖**: T001

- [x] **T003**: `[MVP-核心]` 退出码表与错误翻译测试
  **文件**: `src/bisheng-cli/tests/test_errors.py`（新）
  **逻辑**: 断言 design §4.2 ② 退出码表**每一行**与 D9 的三条"绝不能合并"红线。
  **测试**: `test_exit_code_table_is_total`（表里每个 code 都有 (人话, 下一步) 两段文案，且下一步非空）→ AC-04 / `test_16225_and_16226_map_to_different_codes_and_different_next_step`（13 vs 14，**断言两条下一步文案不相等**，D9 红线 1）→ AC-35 / `test_16231_and_16230_next_step_is_delete_capabilities_not_ask_admin`（映射 exit 10 而**不是** exit 8，D9 红线 2）→ AC-35 / `test_16203_next_step_points_to_package_root_not_create_manifest`（D9 红线 3）→ AC-30, AC-35 / `test_26003_prints_required_scope_verbatim`（逐字打 `data.required` 的位名 → exit 5；⚠️ **`data.required` 是单个字符串不是数组**——`OpenApiScopeMissingError(required: str)`（`common/errcode/open_api.py:63-68`）+ `data = {"exception": …, **kwargs}`（`errcode/base.py:29-33`），对字符串 `", ".join(...)` 会逐字符拆成 `a, p, p, :, m…`，本用例传一个真实位名 `"app:manage"` 并断言整串原样出现）→ AC-34 / `test_26001_26002_26027_are_distinguishable`（三条文案互不相同 → exit 4；⚠️ **只有三条**——`26002` 一个码同时覆盖「不存在 / 已撤销 / 已过期」（`common/errcode/open_api.py:50-55`），服务端不给区分这三者的信号，别写"四种成因"的用例，见 T019 同名订正）→ AC-10, AC-11 / `test_26030_marked_retryable`（exit 7 且文案含"可重试"）→ AC-10 / `test_16207_maps_to_layer_not_enabled`（exit 8「本环境未启用应用工场」）→ AC-40 / `test_unknown_code_falls_back_to_exit_19_not_exit_1`（未登记 code 原样打 `code` + `message`，**不落进 exit 1「CLI 内部异常」那一格**）→ AC-04 / `test_161_segment_codes_are_registered_not_unknown`（**2026-08-17 审查新增**：CON-8 明写 `deploy`/`logs` 也消费 **F054 的 161 段**，但表里一条都没有 —— 至少 `16121`「编排器不可用」（dockerd / runtime-manager 不可达，`contracts-runtime-manager.md` §3 把 manager 的 `503 backend_unavailable` 映射到它，是 `bisheng logs` 最常撞的一条）→ **exit 7 可重试**、`16101`「应用不存在」（`--app-id` 写错或应用已删）→ **exit 6**；断言两者都不落进 exit 19）→ AC-04 / `test_unknown_code_with_5xx_degrades_to_retryable_not_19`（**未登记 code 先看 HTTP 状态类再落 19**：F049 实测里 FGA / DB 故障在 `/api/v2` 返 **HTTP 503 + `19002`**（`test/open_api/test_open_api_auth_api.py:300-302`），只按 code 查表会打成"平台返回未登记的错误码"+ exit 19，而正确处置是"平台暂不可用、稍后重试"= exit 7；断言 503/502/504→7、401→4、403→5，三类都判不了才 19）→ AC-04, AC-10 / `test_26004_and_26031_are_reported_as_platform_or_cli_defect`（不得翻成"你的密钥有问题"）→ AC-04 / `test_delegate_rejection_shape_matches_server_side_rejection`（CLI 侧 `login` 拒绝与服务端 403 原样呈现的拒绝形状一致：同退出码 5、同"委托专用、本地开发另发一把"指向）→ AC-13 / `test_no_error_text_contains_key_material`（对所有分支断言输出不含 `FAKE_KEY` 子串）→ AC-04
  **覆盖 AC**: AC-04, AC-10, AC-11, AC-13, AC-30, AC-34, AC-35, AC-40
  **依赖**: T002

- [x] **T004**: `[MVP-核心]` `errors.py` 实现（`CliError` + `ERROR_HINTS` + 退出码映射）
  **文件**: `src/bisheng-cli/bisheng_cli/errors.py`（新）
  **逻辑**: `class CliError(Exception)` 带 `exit_code` / `code`（平台原始码，可为 `None`）/ `message` / `next_step` / `details` / `hints`；`EXIT_*` 常量按 design §4.2 ② 全表定义（0/1/2/3/4/5/6/7/8/9/10/11/12/13/14/**18**/19/20/21/22/23/24/25；18 = 缺陷类，2026-08-17 裁决新增）；`ERROR_HINTS: dict[int, tuple[str, str]]` = code → (人话, 下一步)，条目取自 design D9 与 §4.1 B 步 6-7 的清单（260 段：`26001`/`26002`/`26003`/`26004`/`26027`/`26030`/`26031`；162 段：`16201`/`16202`/`16203`/`16205`/`16207`/`16221`/`16222`/`16223`/`16224`/`16225`/`16226`/`16227`/`16228`/`16229`/`16230`/`16231`/`16241`/`16251`/`16252`/`16254`；**161 段（2026-08-17 审查补：CON-8 明写本 Feature 也消费 F054 的 161 段，原清单一条都没有）**：`16121`「编排器不可用」→ **exit 7**（`contracts-runtime-manager.md` §3：manager 的 `503 backend_unavailable` 映射到它；`logs` 在 dockerd 宕机时撞的就是这条，**不是 404**，"后端不可用 ≠ 实例不存在"）· `16101`「应用不存在」→ **exit 6**（`--app-id` 写错或应用已删，F054 design:518））。
  **未登记 code 的降级是两级不是一级**（审查修订）：① 先按 **HTTP 状态类**归位——`503`/`502`/`504` → exit 7「平台暂不可用，稍后重试」（F049 的 FGA / DB 故障走 `19002` + HTTP 503，`test/open_api/test_open_api_auth_api.py:300-302`，只查 code 表会把它打成"未登记错误码"而误导用户去查密钥）· `401` → exit 4 · `403` → exit 5；② 三类都不适用才落 **exit 19**「平台返回错误 {code}：{message}」（未知 ≠ 崩溃、≠ 成功，D9）。**两级都要原样打出 `code` 与 `message`**。`16229` 本轮无写入方但**必须登记**（结构演进后置，但 `--confirm-schema-change` 本轮就实现，不登记会在结构演进上线那天变成未知码）。**绝不吞 `details` / `hints`**——那是本地 agent 自动修复的全部输入（AC-47 的成立前提，D6）。**`26003` 的 `data.required` 按单字符串处理**（不是数组，见 T003 该用例）。
  **测试**: T003 全部通过。
  **覆盖 AC**: AC-04, AC-10, AC-11, AC-13, AC-30, AC-34, AC-35, AC-40
  **依赖**: T003

- [x] **T005**: `[MVP-核心]` 输出层测试（机读 NDJSON / 人读文本 / 掩码）
  **文件**: `src/bisheng-cli/tests/test_output.py`（新）
  **逻辑**: 断言 AC-04 的实质 = "非交互可用 + 机器可读 + 永不回显密钥"，形状照 design §4.2 ⑥。
  **测试**: `test_json_mode_machine_events_go_to_stdout_human_text_to_stderr`（`--json` 下 stdout 里**每一行都是可 `json.loads` 的对象**——混一行进度文本就会炸掉 agent 的 `jq` 管道，D2）→ AC-04 / `test_result_event_is_always_the_last_line_and_appears_exactly_once`（成功 / 失败 / 异常三条路径各一次）→ AC-04 / `test_event_shapes_are_exactly_three`（`stage` / `progress` / `result`）→ AC-04 / `test_non_tty_degrades_to_milestones`（无 TTY 时不打进度条、只在 25/50/75/100% 发 `progress`）→ AC-04 / `test_mask_never_emits_key_material`（把 `FAKE_KEY` 塞进 message / header / details 三处，断言输出只有掩码形式 `bs-sak-****`）→ AC-04 / `test_verbose_masks_authorization_header`（`--verbose` 打方法 / 路径 / 状态码 / 耗时，**Authorization 恒掩码**）→ AC-04 / `test_scan_hits_print_file_line_without_value`（`hits[]` 只打 `file:line` + 规则名，**断言不含任何值**；且 CLI **不去本地文件把那行读出来补打**——那等于把服务端刻意不给的东西自己补回来）→ AC-35 / `test_utf8_wrapper_survives_gbk_console`（模拟 `cp936` stdout，断言不抛 `UnicodeEncodeError`，坑 5）→ AC-04
  **覆盖 AC**: AC-04, AC-35
  **依赖**: T002

- [x] **T006**: `[MVP-核心]` `output.py` 实现（双形态输出 + 进度 + 掩码器）
  **文件**: `src/bisheng-cli/bisheng_cli/output.py`（新）
  **逻辑**: `Emitter` 类持 `json_mode` / `quiet` / `verbose` / `is_tty`：`stage(...)` / `progress(...)` / `result(ok, exit_code, data, failure)` 三个事件方法（`--json` 时写 stdout 一行 NDJSON，否则写 stderr 人读文本）；`result` 由 `main.py` 的收口保证**恒发且只发一次**。`mask(text)` 用正则把 `bs-sak-\w+` 与 `Authorization: Bearer \S+` 替换成掩码，**所有出口（人读 / 机读 / verbose 日志）统一过一遍**。`STAGE_LABELS` 是**纯展示用**中文短语表，**未知 stage 原样打印英文**（不认识 ≠ 报错，D6）。无彩色、无表格、不装 rich（D2）。
  **测试**: T005 全部通过。
  **覆盖 AC**: AC-04, AC-35
  **依赖**: T004, T005

- [x] **T007**: `[MVP-核心]` HTTP 客户端与前置探测测试（两套信封 / 探测三分支 / 代理坑）
  **文件**: `src/bisheng-cli/tests/test_http.py`（新）
  **逻辑**: 断言 design §4.1 A 的前置探测三分支与坑 12 的信封解析顺序。
  **测试**: `test_envelope_parsed_body_status_code_first_then_http_status`（**先读 body `status_code`，再看 HTTP 状态**；反过来会把 `/api/v1` 的所有业务错误当成功，坑 12）→ AC-04 / `test_v1_http200_business_error_is_treated_as_error` → AC-04 / `test_v2_real_http_401_403_503_parsed_with_envelope_body` → AC-10, AC-11 / `test_probe_versions_404_and_env_open_platform_false_exits_8`（"本环境未部署开放能力层"）→ AC-05, AC-10 / `test_probe_versions_404_and_env_without_open_platform_flag_exits_9`（"平台版本过老，不支持 CLI"）→ AC-02, AC-10 / `test_probe_env_unreachable_exits_7`（"平台不可达"）→ AC-10 / `test_probe_stops_before_whoami_when_layer_absent`（⚠️ **判定后直接结束、不再打 whoami**——AC-05 的"login 在该环境不可用"由这里兑现，D10 偏离登记）→ AC-05 / `test_min_compatible_greater_than_local_warns_but_does_not_block`（本轮只提示不阻断，D11 第 3 条）→ AC-02 / `test_no_scopes_cached_between_calls`（客户端**不缓存 `scopes`**，每次命令的权限判定都以服务端为准）→ AC-52 / `test_proxy_env_detected_and_named_in_connect_error`（设 `ALL_PROXY` 后连接失败 → 错误里明说"检测到 `ALL_PROXY=…`，内网地址请加入 `NO_PROXY`"，坑 2）→ AC-10 / `test_upload_read_timeout_is_240s_below_nginx_300s`（断言常量，D5）→ AC-31 / `test_bearer_header_masked_in_verbose_log` → AC-04
  **覆盖 AC**: AC-02, AC-04, AC-05, AC-10, AC-11, AC-31, AC-52
  **依赖**: T002, T002a, T004

- [x] **T008**: `[MVP-核心]` `http.py` 实现（客户端封装 + 两套信封 + 前置探测）
  **文件**: `src/bisheng-cli/bisheng_cli/http.py`（新）
  **逻辑**: `PlatformClient(base_url, api_key=None, timeout=…, trust_env=True)`：统一加 `Authorization: Bearer …`；超时分档 —— 连接 10 s、普通读 60 s、**上传读 240 s**（刻意 < nginx `proxy_read_timeout 300s`，`docker/nginx/conf.d/default.conf:53`，让 CLI 自己先超时而不是拿一个被掐断的 504，D5）。`parse_envelope(resp)` 按坑 12 的固定顺序解析并抛 `CliError`。`probe(base_url)` 实现 design §4.1 A 的三分支（`versions` → 404 时再探 `GET /api/v1/env`，三支各有确定退出码 8 / 9 / 7，**判定后直接结束**）。连接失败时检测代理环境变量并把变量名与值写进错误（坑 2）；`--no-proxy` → `trust_env=False`。**不判权限位、不缓存 `scopes`**（AC-52，D3）。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-02, AC-04, AC-05, AC-10, AC-11, AC-31, AC-52
  **依赖**: T007

- [x] **T009**: `[MVP-核心]` CLI 入口与命令面测试（`--help` 命令集 / 全局参数 / 异常收口）
  **文件**: `src/bisheng-cli/tests/test_cli.py`（新）
  **逻辑**: 断言 AC-03 的本轮形态与 AC-04 的"交互确认一律有参数等价物"。
  **测试**: `test_help_lists_exactly_login_deploy_logs`（**本轮只注册三条**；`skills sync` / `dev` 不进解析器、不做"占位报错"，D11 第 1 条）→ AC-03 / `test_help_footer_declares_deferred_commands`（尾部注明"`dev` / `skills sync` 随后续版本提供"——顺延要**明说**而不是藏起来）→ AC-03 / `test_no_as_flag_anywhere`（遍历所有子命令的 action，断言不存在 `--as` 或任何指定他人身份的参数）→ AC-03 / `test_no_init_subcommand` → AC-03 / `test_version_flag_prints_package_version`（读 `bisheng_cli.__version__`）→ AC-02 / `test_every_interactive_confirm_has_a_flag_equivalent`（`--confirm-schema-change` / `--yes` / `--api-key-stdin` 三者存在）→ AC-04, AC-36 / `test_non_interactive_missing_flag_is_refusal_not_default_yes`（无 TTY 且缺确认参数 → 明确拒绝，**绝不"默认同意"**）→ AC-04, AC-36 / `test_unexpected_exception_exits_1_with_traceback_only_in_verbose` → AC-04 / `test_result_event_emitted_even_on_exception`（异常路径也恒有 `result` 尾行）→ AC-04
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-36
  **依赖**: T002, T006

- [x] **T010**: `[MVP-核心]` `main.py` + `cli.py` 实现（入口 / argparse / 退出码收口）
  **文件**: `src/bisheng-cli/bisheng_cli/main.py`（新）, `src/bisheng-cli/bisheng_cli/cli.py`（新）
  **逻辑**: `main()`：**启动第一件事**把 `sys.stdout/stderr` 用 `errors="replace"` 的 UTF-8 wrapper 包一层（Windows 控制台默认 GBK，打中文 hints 会 `UnicodeEncodeError` 直接崩、掩盖真正的错误，坑 5）；构造 `Emitter`；调 `cli.build_parser()` 解析；分发到命令 handler；`except CliError` → 打人话 + 下一步 + 发 `result` → `sys.exit(e.exit_code)`；`except Exception` → exit 1（traceback 仅 `--verbose`）。`cli.py`：`argparse` 子命令注册（本轮 `login` / `deploy` / `logs` 三条，参数面照 design §4.2 ①）+ 全局参数 `--version` / `--verbose` / `--quiet` / `--json` / `--timeout` / `--no-proxy`；`--help` 文案手写（无 typer / click，D2）；尾部注明顺延命令。**handler 以函数引用注入**，命令模块（T020 / T022 / T026）只填实现、不改本文件的注册结构。**不注册 `--platform`**（本轮恒用 `credentials.json` 的 `current`，D11 第 5 条）。
  **测试**: T009 全部通过。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-36
  **依赖**: T006, T009

- [x] **T011**: `[MVP-核心]` 凭据存储测试（权限位 / 多 profile / 不存 scopes）
  **文件**: `src/bisheng-cli/tests/test_credentials.py`（新）
  **逻辑**: 断言 CON-3 与 D3 的落地：**密钥必然明文存，文件权限位是唯一保护**。
  **测试**: `test_file_created_0600_and_dir_0700_in_one_step`（断言用的是 `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)` 语义——**"先 write 再 chmod"中间有一个 world-readable 窗口**，坑 1；POSIX 下直接断言 `stat().st_mode`）→ AC-07 / `test_never_written_into_project_dir`（在 tmp 项目里跑 login，断言项目树内无凭据文件）→ AC-07 / `test_scopes_never_persisted`（写入载荷里没有 `scopes` 键——一旦缓存权限位就会出现"管理员补勾了但 CLI 还说没权限"）→ AC-52 / `test_multi_profile_isolated_by_base_url`（两个平台各写一条、互不覆盖，`current` 指向最近一次）→ AC-12 / `test_relogin_same_platform_overwrites_profile` → AC-12 / `test_base_url_normalised_before_use_as_key`（**2026-08-17 审查新增**：`http://114:7860/` · `http://114:7860` · `HTTP://114:7860` 归一化后是**同一个 profile 键**；不归一化的后果不是"多一条记录"而是两个真实故障——① 明明 `login` 过却报 exit 3「请先 login」；② `.bisheng/app.json` 也按 base_url 分键（T014），键对不上就查不到 `app_id` → **迭代 deploy 被当成首发、平台上再建一个同名草稿应用**。规则：去尾部 `/`、scheme 与 host 小写、去默认端口不做（`:80`/`:443` 显式写与省略视为不同，避免猜错），**归一化函数只有一处、`credentials.py` 与 `project.py` 共用**，`app.json` 侧的对偶用例在 T013）→ AC-12 / `test_load_without_credentials_raises_exit_3_not_network_error`（未登录 → "请先 bisheng login" + 非零退出码，**不是网络错误**）→ AC-51 / `test_stored_snapshot_fields`（`service_account` / `resource_owner`(可为 `null`) / `key_mask` / `tenant_id` / `expires_at` / `logged_in_at`，形状照 design §4.2 ③）→ AC-06 / `test_windows_acl_failure_warns_loudly_instead_of_pretending`（模拟 `icacls` 等价 ACL 设置失败 → **明确警告而不是假装成功**，坑 1）→ AC-07
  **覆盖 AC**: AC-06, AC-07, AC-12, AC-51, AC-52
  **依赖**: T002

- [x] **T012**: `[MVP-核心]` `credentials.py` 实现
  **文件**: `src/bisheng-cli/bisheng_cli/credentials.py`（新）
  **逻辑**: 路径 `~/.bisheng/credentials.json`（目录 `0700` / 文件 `0600`；Windows 用 `%USERPROFILE%\.bisheng\` + `icacls` 等价"仅当前用户"ACL，做不到就明确警告）。**顶层多 profile 结构本轮就落**（`{"version":1,"current":<base_url>,"profiles":{…}}`，D3）——结构一旦按单平台写死，加多平台就是一次带迁移的破坏性变更；**顺延的只是 `--platform` 交互层**（D11 第 5 条）。`load_current()` 无凭据时抛 `CliError(exit=3)`。**不做加密**（明文 + 权限位是既定取舍，D3）；**恒不存 `scopes`**（AC-52）。
  **`normalise_base_url(raw)` 落在本模块、全仓唯一一份**（审查新增）：去尾 `/`、scheme 与 host 小写、保留显式端口；**profile 键、`current` 值、`.bisheng/app.json` 的分键（T014）三处都用它**——分两处实现就会出现"login 过却说未登录 / 迭代 deploy 被当首发再建一个应用"。
  **测试**: T011 全部通过。
  **覆盖 AC**: AC-06, AC-07, AC-12, AC-51, AC-52
  **依赖**: T004, T011

- [x] **T013**: `[MVP-核心]` 项目层测试（manifest 三必填快速失败 + `.bisheng/app.json`）
  **文件**: `src/bisheng-cli/tests/test_project.py`（新）
  **逻辑**: 断言 CON-1 的推论——**CLI 只做"存在 + 可解析 + 三必填"级快速失败，权威校验在 F055 托管预检**。
  **测试**: `test_missing_manifest_refused_locally_without_upload`（不发任何请求，`no_network` 哨兵保证）→ AC-30 / `test_unparsable_yaml_refused_with_line_info` → AC-30 / `test_each_of_name_runtime_port_missing_is_named_in_the_error`（三个必填项各缺一次，错误逐字点名缺哪个）→ AC-30 / `test_safe_load_only_rejects_python_object_tag`（`!!python/object` 不得被反序列化——`full_load` / `unsafe_load` 是 RCE，F055 design D3 红线）→ AC-30 / `test_optional_fields_not_validated_locally`（`tier` / `capabilities` / `database` / `egress` 本地一律不判、**不自造字段与缺省值**，否则会出现"本地过、上传被拒"）→ AC-30 / `test_app_json_written_and_read_per_base_url`（形状照 design §4.2 ④）→ AC-33 / `test_app_json_key_uses_the_same_base_url_normaliser_as_credentials`（**2026-08-17 审查新增**：`http://114:7860/` 写入、`http://114:7860` 读取必须命中同一条；两侧各自实现归一化 = 迟早分叉 → **复用 T012 落的同一个函数**，本用例直接断言 `project.normalise_base_url is credentials.normalise_base_url` 级的同源性或跑同一组样例）→ AC-33 / `test_explicit_app_id_overrides_saved_one` → AC-33 / `test_missing_app_id_asks_for_explicit_flag`（项目被复制到另一目录 / 标识丢失时要求显式指定，不猜）→ AC-33
  **覆盖 AC**: AC-30, AC-33
  **依赖**: T002

- [x] **T014**: `[MVP-核心]` `project.py` 实现（项目根定位 / manifest 快速失败 / `app.json` 读写）
  **文件**: `src/bisheng-cli/bisheng_cli/project.py`（新）
  **逻辑**: `find_project_root(path)`；`load_manifest(root)` = `yaml.safe_load` + 三必填（`name` / `runtime` / `port`）存在性检查 → 失败抛 `CliError(exit=6)` 并列出缺失项；**不做完整 schema 校验、不写 manifest**（AppManifest 归 F055，`extra='forbid'`，CON-1 / 决议-5）。`AppRef` 读写 `<项目根>/.bisheng/app.json`（按平台 base URL 分键——**键一律经 `credentials.normalise_base_url()`，不在本模块另写一份**，审查新增；`--app-id` 可显式覆盖，D13）。**建议开发者把 `.bisheng/` 提交进 git**（团队共享同一个 `app_id`），但它**结构性排除出上传包**（T018）——"进 git"与"进包"是两件事。
  **测试**: T013 全部通过。
  **覆盖 AC**: AC-30, AC-33
  **依赖**: T004, T013

- [x] **T015**: `[MVP-核心]` 忽略规则测试（三层规则 + git/子集解析器一致性）
  **文件**: `src/bisheng-cli/tests/test_ignore.py`（新）
  **逻辑**: 覆盖 D4 的三层规则与坑 9。**核心用例是"同一份样本目录，git 路径与自研子集解析器结果必须一致"**——两条路径分叉就是静默的包内容差异。
  **测试**: `test_git_path_and_subset_parser_agree_on_sample_tree`（`sample_project_git` 上跑 `git ls-files -c -o --exclude-standard -z` 与子集解析器，断言两个集合相等；无 git 则 skip）→ AC-32 / `test_double_star_matches_across_directories`（`**` 单独处理——**`fnmatch` 的 `*` 跨 `/` 匹配、且根本没有 `**`**，`linsight/domain/services/workspace_backend.py:616-619` 的注释逐字记录了这两个坑，本仓已真实咬过一次）→ AC-32 / `test_single_star_does_not_cross_slash`（每段单独匹配）→ AC-32 / `test_leading_bang_negation_takes_back` → AC-32 / `test_trailing_slash_matches_directory_only` → AC-32 / `test_bishengignore_loaded_last_and_wins` → AC-32 / `test_hard_excluded_dirs_cannot_be_taken_back_by_bang`（`.git/` `node_modules/` `.venv/` `__pycache__/` `.bisheng/` 等硬排除，`!` 取不回）→ AC-32 / `test_dist_and_build_are_soft_excluded_and_can_be_taken_back`（⚠️ **`dist/` / `build/` 刻意不进硬排除**：存量应用把前端构建产物放 `dist/` 交后端静态托管是常见形态，硬排会静默剥掉、故障要到构建 / 探活阶段才暴露）→ AC-32 / `test_non_git_project_output_says_subset_parsing_used`（非 git 仓库时**在输出里明说**"忽略规则按子集解析，复杂规则请写进 `.bishengignore`"）→ AC-32
  **覆盖 AC**: AC-32
  **依赖**: T002

- [x] **T016**: `[MVP-核心]` `ignore.py` 实现（git 优先 / 子集解析 / `.bishengignore` 收口）
  **文件**: `src/bisheng-cli/bisheng_cli/ignore.py`（新）
  **逻辑**: 三层从内到外（D4）：① 结构性排除（硬排除不可取回 / 软排除可被 `.bishengignore` 的 `!` 取回）；② `.gitignore` 语义——是 git 仓库且 `git` 可执行 → 直接 `git ls-files -c -o --exclude-standard -z` 让 git 自己算（零依赖、100% 语义一致），否则回落自研子集解析器（`#` 注释 / 空行 / 前导 `!` / 目录后缀 `/` / `**` / 段内 `*` `?`）；③ `.bishengignore`（同语法、最后加载、优先级最高）。**手写段匹配，`**` 单独处理，绝不用 `fnmatch` 顶 gitignore 全语义**（坑 9）。**不引 `pathspec`**——一条内网安装链换一个只在"非 git 项目"才用得上的完备性，不划算（D4 备选 B）。
  **测试**: T015 全部通过。
  **覆盖 AC**: AC-32
  **依赖**: T015

- [x] **T017**: `[MVP-核心]` 打包测试（tar.gz 四条硬规矩 + 凭据不进包 + 体量自查）
  **文件**: `src/bisheng-cli/tests/test_packaging.py`（新）
  **逻辑**: 断言 D4 的"打包四条硬规矩"，每条都是一个坑的对偶。
  **测试**: `test_credentials_file_never_in_package`（**assert 型测试**，AC-07 的直接落点）→ AC-07, AC-32 / `test_venv_node_modules_git_pycache_excluded` → AC-32 / `test_local_sqlite_and_attachment_dir_excluded` → AC-32 / `test_member_paths_are_posix_relative_no_backslash_no_abs_no_dotdot`（Windows 上 `Path` 给 `\` 分隔 → 服务端解包出 `src\main.py` 这样的**单个文件名**，目录结构全平；或触发 16202，坑 4）→ AC-31, AC-32 / `test_symlink_hardlink_device_fifo_skipped_and_listed`（服务端 tar 解包闸会拒它们，本地不跳等于必然吃一个 16202 且浪费一次上传，坑 14；**跳过要列出、不静默**）→ AC-31 / `test_owner_exec_bit_preserved_0755_others_normalized_0644`（丢可执行位 → entrypoint 上线后不可执行，故障要到构建 / 探活才暴露、排查方向指向"平台构建有问题"，坑 20）→ AC-31 / `test_reproducible_same_sha256_twice`（成员按路径排序、`mtime` 归一、`uid=gid=0`、`uname=gname=""`）→ AC-31 / `test_never_silently_truncates_on_limit`（超限**整包拒绝**并列清单，判据照 `linsight/domain/services/workbench_impl.py:1255-1257`："包被悄悄截断 = 线上跑的不是本地那份"）→ AC-32 / `test_oversize_report_lists_excluded_count_then_top10`（超限报告**先列排除了多少**再列 Top 10 最大文件 / 目录——"忽略建议"不能是空话，且开发者的第一反应"平台上限太小"多半是没排除 `.venv/`，坑 3）→ AC-32 / `test_limits_endpoint_unreachable_falls_back_to_defaults_and_proceeds`（取不到 `deploy-limits` → 用内置默认值只提示、继续上传，由服务端 16201 兜底；**绝不让一个软校验挡死发布**，坑 17 / CON-4）→ AC-32
  **覆盖 AC**: AC-07, AC-31, AC-32
  **依赖**: T002, T002a, T016
  **⚠️ 上限口径**: `{max_package_mb, max_unpacked_mb, max_package_entries}` 的权威值经 `GET /api/v2/apps/deploy-limits` 取（F055 T005 落的配置键、T039 的端点），内置默认 50 MB / 200 MB 解包 / 20000 条目**只作回落**（F055 T050 回写项 3 已登记同一口径，不另立一套）。

- [x] **T018**: `[MVP-核心]` `packaging.py` 实现（tar.gz + 统计 + Top10 报告）
  **文件**: `src/bisheng-cli/bisheng_cli/packaging.py`（新）
  **逻辑**: `build_package(root, ignore_result, out_path) -> PackageStat`：`tarfile` + `gzip` 产 **tar.gz**（**不产 zip**——F055 端点参数逐字写的是 `package`、对象键是 `apps/{app_id}/versions/{version_id}/code.tar.gz`，产 zip 等于和字面契约、对象键名、未来分片方案三处同时错位，D4）；`arcname = PurePosixPath(*rel.parts)` 且落包前逐条 assert 无 `\`、无绝对路径、无 `..`（坑 4）；模式归一 `0644`、**保留 owner 执行位为 `0755`**（坑 20）；链接 / 设备 / FIFO 跳过并收集进 `PackageStat.skipped`；成员排序 + `mtime` 归一 + `uid/gid/uname/gname` 归零（可复现）。`PackageStat` 含条目数 / 原始体量 / 压缩体量 / 排除统计 / Top 10 最大文件与目录。**不静默截断、不上传**（上传在 T022）。
  **测试**: T017 全部通过。
  **覆盖 AC**: AC-07, AC-31, AC-32
  **依赖**: T016, T017

---

### Wave 2 · `[MVP-核心]` 三条命令、平台分发端点与 114 验证

- [ ] **T019**: `[MVP-核心]` `login` 测试（探测 → whoami → 拒 `delegate` → 写凭据）
  **文件**: `src/bisheng-cli/tests/test_command_login.py`（新）
  **逻辑**: 按 design §4.1 A 的数据流逐分支断言。⚠️ **`delegate` 相关用例只能用 mock `whoami` 响应**——该位在 F049 期根本签不出来（`open_api/domain/scopes.py:186-188` NOTE，坑 15），**去 114 上试不出来不等于功能没生效**。
  **测试**: `test_success_writes_profile_and_prints_platform_account_owner_mask_expiry`（输出目标平台 / 服务账号名 / 资源归属人 / `key_mask` / 到期时间）→ AC-06 / `test_success_without_resource_owner_field_degrades_with_explicit_hint`（`whoami` 暂无 `resource_owner` → 明打一句"资源归属人请在服务账号详情页确认"，**不静默省略**；`[受阻于 F049 回写]`，D14 / T034 回写项 1）→ AC-06 / `test_no_scope_check_at_all`（**不校验任何权限位**——未勾任何位的有效密钥可正常 `login`）→ AC-06, AC-10 / `test_delegate_scope_refused_before_writing_credentials`（不写凭据、错误指向"这把 key 配置为委托专用，本地开发请另发一把"、exit 5；**断言凭据文件不存在**）→ AC-09 / `test_delegate_refusal_is_not_a_silent_fallback_to_mode_s`（断言退出码非 0 且不出现"登录成功"字样，INV-31）→ AC-09, AC-13 / `test_delegate_refusal_is_not_a_bare_param_error`（错误文案必须指向委托专用，不得只回一个参数类错误码）→ AC-09 / `test_missing_invalid_and_inactive_account_are_distinguishable`（**2026-08-17 审查订正**：原用例名写"四种成因（无效 / 撤销 / 过期 / 停用）互不相同"，与 F049 **已落码**的形状冲突——`OpenApiCredentialInvalidError` 一个码 `26002` + 一条 Msg 同时覆盖「不存在 / 已撤销 / 已过期」（`common/errcode/open_api.py:50-55` docstring 逐字 "Credential unknown, revoked or expired"），服务端**不给**区分这三者的任何信号，CLI 造不出来。可断言且必须断言的是**三条码**：`26001`（没带 / 带歪 Authorization → 让用户检查 `--api-key` 传法）· `26002`（密钥不被接受 → 重签或换一把）· `26027`（服务账号被停用 / 删除 → 找管理员启用账号，**不是**换密钥）文案互不相同；AC-10「彼此可区分」按此读为「密钥类失败 vs 平台不可达 vs 未部署开放能力层」三组可区分，**不承诺撤销与过期可分**）→ AC-10, AC-11 / `test_platform_unreachable_and_layer_absent_are_distinguishable`（exit 7 vs exit 8，探测在 whoami 之前结束）→ AC-05, AC-10 / `test_key_from_flag_env_stdin_tty_priority`（`--api-key` > `BISHENG_API_KEY` > `--api-key-stdin` > TTY 隐藏输入；四者皆无 → exit 2）→ AC-07 / `test_key_never_echoed_in_any_output`（含 `--verbose`）→ AC-04, AC-07 / `test_relogin_overwrites_same_platform_profile` → AC-12 / `test_no_auto_skills_sync_this_round`（本轮不触发 `skills sync`——AC-08 随顺延项 T035–T038，此处显式断言"没有静默尝试"）→ AC-08
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13
  **依赖**: T002, T002a, T008, T012

- [ ] **T020**: `[MVP-核心]` `commands/login.py` 实现
  **文件**: `src/bisheng-cli/bisheng_cli/commands/login.py`（新）
  **逻辑**: 编排 = `http.probe(base_url)` → `GET /api/v2/auth/whoami`（**F049 已实现，commit `43e73bfc5`**；`/api/v2` 下唯一 `@open_api_scope(None)` 的端点，`open_api/api/endpoints/auth.py:23`，正是 AC-06「不校验任何权限位」的落点）→ `scopes` 含 `"delegate"` 则拒绝并退 5 → 写 profile（T012）→ 输出。密钥来源优先级见 design §4.2 ①；`getpass` 隐藏输入。**不直接用 httpx**（走 `http.py`）。**本轮不自动执行 `skills sync`**（AC-08 随 T038）。
  **测试**: T019 全部通过。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13
  **依赖**: T010, T012, T019

- [ ] **T021**: `[MVP-核心]` `deploy` 同步段测试（本地校验 → 打包 → 上传 → 同步错误分支）
  **文件**: `src/bisheng-cli/tests/test_command_deploy_sync.py`（新）
  **逻辑**: ⚠️ **本任务是红线 1 的直接承载**：`POST /api/v2/apps/deploy` 的**同步响应**里就已跑完归属判定 · 大小闸 · 解包闸 · manifest 校验 · 本地引用校验 · 在途单 / 待上线闸（F055 design §4.1 ① `:411-427`），**这些失败一条都不进轮询**。
  **测试**: `test_not_logged_in_exits_3_without_any_request` → AC-51 / `test_local_manifest_failure_refuses_before_packaging`（不打包、不上传）→ AC-30 / `test_dry_run_stops_after_packaging_and_prints_stats`（条目数 / 体量 / 忽略统计，不上传）→ AC-31, AC-32 / `test_oversize_refused_locally_with_top10` → AC-32 / `test_upload_is_streamed_multipart_not_read_bytes`（传 file object，50 MB 不进内存，D5）→ AC-31 / `test_app_id_persisted_immediately_on_http_200_even_if_pipeline_later_fails`（⚠️ **接收成功即写盘**：首发预检失败时平台**已经建好草稿应用并分配了 `app_id`**，只在成功时才保存 → 开发者修完 manifest 重跑会**再建一个应用**，构建页堆一串同名草稿；且 F055 明确依赖"CLI 保存 `app_id` 以复用"，坑 13 / D13）→ AC-33 / `test_iterative_deploy_prints_target_app_name_and_id_before_upload`（误投护栏：指定了**同一归属人的另一个应用**会真的更新那个应用——无声的错误；非交互模式下这行输出是唯一护栏）→ AC-33 / `test_interactive_confirm_skipped_by_yes_flag` → AC-04 / `test_first_deploy_prints_app_id_and_entry_url_when_present_else_points_to_detail_page`（`entry_url` 只在 `POST` 返回里、首发时大概率为 `null` → **明确指路"应用详情页 · 发布"而不是打印空串或 `None`**；`[受阻于 F055 回写]`，T034 回写项 3）→ AC-33 / `test_26003_missing_app_manage_refused_and_names_the_required_scope`（exit 5，输出里出现整串 `app:manage`——`data.required` 是**单个字符串**不是数组，见 T003；判定与归属人有无"创建应用"角色权限、角色是否被调整、账号是否被停用**无关**）→ AC-34 / `test_16205_other_owner_refused_and_names_the_owner` → AC-38 / `test_16251_in_flight_approval_refused_with_withdraw_path`（撤回路径在应用详情页 · 发布，CLI 不提供撤回命令）→ AC-37 / `test_16252_pending_online_refused` → AC-37 / `test_16229_schema_change_requires_confirm_flag`（未确认即终止、不生成审批单；非交互环境未带参数视为未确认）→ AC-36 / `test_confirm_schema_change_flag_forwarded_as_form_field`（F055 本轮"只接收不消费"，参数存在与否是 CLI 的对外契约）→ AC-36 / `test_16207_workshop_runtime_layer_absent_exits_8`（"本环境未启用应用工场"，**不返回未定义错误**）→ AC-40 / `test_16201_16202_16203_map_to_exit_6` → AC-32 / `test_sync_error_never_enters_polling_loop`（**红线 1 的断言**：mock 只准备一次 `POST` 响应，若进了轮询循环 `no_network` 哨兵会当场失败）→ AC-31a
  **覆盖 AC**: AC-04, AC-30, AC-31, AC-31a, AC-32, AC-33, AC-34, AC-36, AC-37, AC-38, AC-40, AC-51
  **依赖**: T002, T002a, T008, T012, T014, T018

- [ ] **T022**: `[MVP-核心]` `commands/deploy.py` 同步段实现（校验 → 打包 → limits → 上传 → 写 `app.json`）
  **文件**: `src/bisheng-cli/bisheng_cli/commands/deploy.py`（新）
  **逻辑**: 严格按 design §4.1 B 步 1–6：载入凭据 → 定位项目根 + `load_manifest` → 解析忽略规则 + 打包（`--dry-run` 到此为止）→ `GET /api/v2/apps/deploy-limits` 自查（取不到只提示、继续）→ 迭代场景打印目标应用名称 + 标识（`--yes` 跳过交互确认）→ `POST /api/v2/apps/deploy`（multipart：`package` + `app_id?` + `confirm_schema_change`）→ **200 立刻写 `.bisheng/app.json`**（坑 13）并记下 `entry_url`（轮询载荷里没有这个字段，D7）→ 同步错误按 code 映射退出码**直接终止、不进轮询**。
  **测试**: T021 全部通过。
  **覆盖 AC**: AC-04, AC-30, AC-31, AC-31a, AC-32, AC-33, AC-34, AC-36, AC-37, AC-38, AC-40, AC-51
  **依赖**: T014, T018, T021（鉴权客户端构造在 `http.py`/T008、凭据载入在 `credentials.py`/T012，二者经 T021 的依赖链已就位；**刻意不依赖 T020**——`deploy` 与 `login` 之间没有代码依赖，写上就把"三路并行"变成串行链）
  **跨 Feature**: 服务端 = **F055 T039**（`POST /apps/deploy` / `GET /apps/deploy-limits`）。

- [ ] **T023**: `[MVP-核心]` `deploy` 轮询与 `--wait` 终态测试（分阶段输出 / 六终态 / 退出码）
  **文件**: `src/bisheng-cli/tests/test_command_deploy_wait.py`（新）
  **逻辑**: 用 `platform_mock.deployment_seq([...])` 编排轮询序列，断言 D6 / D7。
  **测试**: `test_stage_events_in_server_order_received_first`（⚠️ **第一条轮询响应的 `stage` 就是 `received`**，漏登记会让每次 deploy 的第一行输出掉进"未知 stage"兜底分支）→ AC-31a / `test_all_eleven_server_stages_translate_or_pass_through`（权威枚举照 F055 `055-.../design.md:86`：`received · secret_scan · precheck_manifest · precheck_build · precheck_probe · version_recorded · approval_created · approved · publishing · online · pending_online`；**`approval_created` 是机读值、不得写成中文「审批单生成」**——那是展示串，混淆会让 `--json` 的 `stage` 与服务端对不上）→ AC-31a / `test_stage_translation_is_a_mapping_not_an_ordered_sequence`（**2026-08-17 审查新增**：上面那串**是取值集合、不是顺序断言**——F055 design:86 的花括号写法把 `secret_scan` 列在 `precheck_*` 之前，而 **2026-08-17 该 ★ 已拍板：`secret_scan` 提前到 `precheck_*` 之前**（F053 spec 决议-13；扫描输入是源码包不依赖构建产物、失败更快、DEV-04 四步是逻辑分组非顺序契约），AC-31a 已同步为「安全扫描 → 托管预检 → 审批单」。**但这不改变本条的结论**——顺序既然改过一次就可能再改，CLI 把它写死就是把服务端的编排决策复制到客户端。→ CLI **只按服务端到达顺序输出**，`STAGE_LABELS` 是无序 dict；断言"任意顺序的 stage 序列都不报错"，**不要写死顺序断言**——写死顺序的用例会在服务端下次调整阶段编排时连同 README 一起变红）→ AC-31a / `test_unknown_stage_printed_verbatim_not_an_error`（不认识 ≠ 报错）→ AC-31a / `test_any_failed_stage_stops_polling_and_exits_nonzero` → AC-31a / `test_failure_tuple_passed_through_untouched_in_json`（`{stage,code,message,details,hints[]}` **原样**进 `result.failure`——**绝不吞 `details` / `hints`**，那是 agent 自动修复的全部输入）→ AC-31a, AC-35 / `test_precheck_failure_prints_missing_items_and_hints_lines` → AC-35 / `test_16241_scan_hit_prints_file_line_only_never_the_value` → AC-35 / `test_default_returns_0_at_waiting_approval_with_three_tracking_paths`（应用详情页 · 发布 / MCP 应用状态工具 / `deploy --wait`）→ AC-31b / `test_wait_online_exits_0_with_entry_url_or_pointer`（`entry_url` 缺位时指路详情页；`[受阻于 F055 回写]`）→ AC-31c, AC-33 / `test_wait_rejected_exits_20_with_full_reason`（驳回理由**全文不截断**）→ AC-31c / `test_wait_withdrawn_exits_21` → AC-31c / `test_wait_pending_online_exits_22_with_manual_publish_path`（`pending_reason ∈ {capacity, deploy_failed}`）→ AC-31c / `test_wait_cancelled_exits_24_immediately_not_timeout`（⚠️ 应用被删除 → 这单**永远不会有结论**，只认四终态会一路轮到超时再打印"这不是失败，请继续等"，D7）→ AC-31c / `test_wait_exception_exits_25_immediately_not_timeout`（审批人解析为空，同上）→ AC-31c / `test_wait_timeout_exits_23_and_says_not_a_failure`（超时与驳回的后续动作完全相反——等 vs 改）→ AC-31c / `test_backoff_2s_x1_5_capped_10s` → AC-31c
  **覆盖 AC**: AC-31a, AC-31b, AC-31c, AC-33, AC-35
  **依赖**: T002, T002a, T021

- [ ] **T024**: `[MVP-核心]` `deploy` 轮询与终态机实现（`commands/deploy.py` 增量）
  **文件**: `src/bisheng-cli/bisheng_cli/commands/deploy.py`（**增量新增 `_poll()` / `_terminal()` 两个函数与 `STAGE` 常量，不重写 T022 已落的同步段**）
  **逻辑**: 短轮询 `GET /api/v2/apps/deployments/{deployment_id}`，间隔 2 s 起、每 5 次 ×1.5、封顶 10 s；`--wait-timeout` 默认 1800 s。**长连接 / SSE 物理上不可行**——nginx `proxy_read_timeout 300s`（`docker/nginx/conf.d/default.conf:53`）而审批是人工动作可跨天（坑 6）。两段语义分开：无 `--wait` 轮到 `status=waiting_approval` 即返回 0；有 `--wait` 续轮至终态，映射照 design D7 终态表（0 / 20 / 21 / 22 / 23 / 24 / 25）。`approval.status` **必须认全六种**：`pending` / `rejected` / `withdrawn` / `cancelled` / `exception` / `executed|approved`。
  **测试**: T023 全部通过。
  **覆盖 AC**: AC-31a, AC-31b, AC-31c, AC-33, AC-35
  **依赖**: T022, T023
  **跨 Feature**: 服务端 = **F055 T039**（`GET /apps/deployments/{id}`）；终态语义来自 F055 T034/T035（驳回 / 撤回 / 删除致取消）与 T029（审批人为空 → `decision=EXCEPTION`）。

- [ ] **T025**: `[MVP-核心]` `logs` 测试（服务端判权限 / 空结果提示 / `--follow` 去重）
  **文件**: `src/bisheng-cli/tests/test_command_logs.py`（新）
  **逻辑**: 断言 D8 —— **CLI 对归属零逻辑**，owner-only 全由服务端判（读 `OpenApiPrincipal.resource_owner_user_id`，**不是** `subject_user_id`，F055 T039）。
  **测试**: `test_not_logged_in_exits_3_without_request` → AC-51 / `test_tail_since_keyword_forwarded_as_query_params`（可查看最近一段 / 按时间范围 / 关键词）→ AC-41 / `test_16254_owner_only_refused_with_readable_reason`（"该应用不属于当前密钥的资源归属人"）→ AC-42 / `test_16205_other_owner_refused` → AC-42 / `test_cli_never_checks_ownership_itself`（断言请求先发出、CLI 不预查归属——第二处归属判定会与服务端分叉，且 CLI 拿不到权威数据）→ AC-42 / `test_26003_missing_app_manage_exits_5` → AC-41 / `test_16207_layer_absent_exits_8` → AC-40 / `test_empty_lines_prints_app_state_hint_not_blank`（"未取到日志：应用可能没有运行实例（草稿 / 待上线 / 已停运），请在应用详情页确认应用态"——**明确提示而不是空白**；`[受阻于 F055 回写]`，满足 AC-43 精神但不满足其字面，T034 回写项 2）→ AC-43 / `test_follow_polls_with_since_every_3s` → AC-41 / `test_since_accepts_epoch_seconds_and_relative_window`（**2026-08-17 审查新增，照 runtime-manager 已落码的实测口径**：`since` 收 **epoch 秒** 或 `30m` / `2h` / `7d` 相对窗口，不可解析由服务端回 400；CLI 不自造第三种写法、也不在本地把相对窗口换算成绝对时间——换算等于给同一语义造第二个实现）→ AC-41 / `test_keyword_may_return_fewer_lines_than_tail_is_not_a_bug`（`keyword` 在 manager 内过滤，**返回行数可 < `tail`**，`contracts-runtime-manager.md` §2 逐字"这是设计不是 bug"；CLI 不得据此重试或报警）→ AC-41 / `test_16121_orchestrator_unavailable_says_retry_not_app_missing`（dockerd / runtime-manager 宕机时链路回 **503 → `16121`**、**不是 404**；"后端不可用 ≠ 实例不存在"，打成"应用已删除"会让 owner 白排查一轮）→ AC-41 / `test_follow_dedupes_same_second_repeats`（⚠️ **docker 时间戳是秒级**，同一秒的多行在下一轮 `since` 里会重复返回；同类坑本仓咬过：memory `project_chat_history_sameSecond_order`）→ AC-41 / `test_app_id_resolution_same_as_deploy`（项目内记录或显式指定）→ AC-43 / `test_since_empty_says_no_logs_in_range_or_rotated_not_never_happened`（日志保留期不做承诺——runtime-manager 侧是 docker 日志轮转窗口）→ AC-41
  **覆盖 AC**: AC-40, AC-41, AC-42, AC-43, AC-51
  **依赖**: T002, T002a, T008, T012, T014

- [ ] **T026**: `[MVP-核心]` `commands/logs.py` 实现
  **文件**: `src/bisheng-cli/bisheng_cli/commands/logs.py`（新）
  **逻辑**: `GET /api/v2/apps/{app_id}/logs?tail=&since=&keyword=` → `{lines[]}`（`tail` 服务端范围 1–5000、默认 500；`since` = epoch 秒或 `30m`/`2h`/`7d`；日志保留期 = docker 轮转窗口，产品口径「最近的运行日志」，**CLI 不做任何保留期承诺**）；错误码翻人话（`errors.py`，含 `16121` → exit 7）；`--follow` 携 `since` 每 3 s 短轮询（**无流式接口**：服务端链路是 `GET /api/v2/.../logs` → F054 `GET /api/v1/apps/{id}/logs` → runtime-manager `GET /v1/apps/{id}/logs`（**已实现**）→ `docker logs`，全是一次性响应，坑 18 的"未实现"口径已于 2026-08-17 审查回正），保留上一轮最后 N 行的内容哈希集合做去重。**CLI 不做任何归属判定**。
  **测试**: T025 全部通过。
  **覆盖 AC**: AC-40, AC-41, AC-42, AC-43, AC-51
  **依赖**: T014, T025（同 T022：**刻意不依赖 T020**，`logs` 与 `login` 之间没有代码依赖）
  **跨 Feature**: 服务端 = **F055 T039**（`GET /apps/{app_id}/logs` + owner-only 判定）；中段 = **F054 T057**（backend `GET /api/v1/apps/{app_id}/logs`，**未实现**）；终点 = **F054 T030/T031**（runtime-manager 只读接口，✅ **已实现**，commit `d693feeb3` —— 2026-08-17 审查回正，原文写的"当前未实现"已过时）→ 114 联调排在 **F054 T057 → F055 T039** 之后，本任务的验收本轮只到单测。

- [ ] **T027**: `[MVP-核心]` 平台分发端点集成测试（匿名可达 / 开关关闭即 404 / 租户豁免）
  **文件**: `src/backend/test/dev_toolkit/test_distribution_api.py`（新）, `src/backend/test/dev_toolkit/conftest.py`（新）
  **逻辑**: **本 Feature 唯一落 `src/backend/test/` 的测试**（不放 `test/` 根，`asyncio_mode=auto`）。
  **测试**: `test_versions_reachable_without_any_credential`（**匿名**，不带 Bearer 也不带 JWT）→ AC-01 / `test_versions_payload_shape`（`cli.{version,min_compatible,filename,sha256,download_path}` + **`sdk.{version,min_compatible,download_path}` 字段位存在且本轮为 `null`**（F057 AC-01/AC-03 消费同一端点，不留就会在 F057 期出现第二个端点或破坏性改形）+ `platform.{version,open_platform_enabled,app_runtime_enabled}`）→ AC-01, AC-02 / `test_platform_version_not_taken_from_env_endpoint`（⚠️ `/api/v1/env` 的 `version` 是硬编码 `'2.6.0-fix'`（`src/backend/bisheng/__init__.py:7`，3.0-vibe 实测）→ 断言 `platform.version` 取自 `artifacts/manifest.json` 而非那里，坑 21）→ AC-02 / `test_download_returns_file_response_with_content_disposition_and_length` → AC-01 / `test_download_requires_no_login_and_no_key` → AC-01 / `test_routes_absent_when_open_platform_disabled`（⚠️ **断言是路由不存在（404）、不是某个错误码**——AC-05「呈不存在」的字面落点，且不给未认证方留"这里有个功能但没开"的探测面）→ AC-05 / `test_multi_tenant_enabled_no_jwt_does_not_raise_no_tenant_context`（多租户开启 + 无 JWT 时不抛 `NoTenantContextError`——豁免名单生效的回归护栏，见 T029）→ AC-01 / `test_missing_artifacts_degrade_readably_not_500`（**2026-08-17 审查新增**：`artifacts/` 里的 wheel 与 `manifest.json` 是**提交进 git 的构建产物**，任何"检出后没跑 `scripts/pack_cli_wheel.sh`"的开发环境里它们就是不存在的 —— 断言 `versions` 仍 **200** 且 `cli` 段为 `null` 并带一句可读说明（不抛、不 500），`download` 返 **404 + 可读 message**（"CLI 安装件未随本次部署发布，请联系平台管理员"）而**不是** `FileResponse` 对不存在路径抛出的 500 + traceback；本用例同时是"产物漏提交"这一类发版事故的唯一自动告警）→ AC-01
  **覆盖 AC**: AC-01, AC-02, AC-05
  **依赖**: 无（平台侧完全独立于 CLI 工程，可与 Wave 1 全程并行；编号排在此处只为与 T028 相邻）

- [ ] **T028**: `[MVP-核心]` 平台分发端点实现（**本 Feature 唯一改 backend 业务代码的任务**）
  **文件**: `src/backend/bisheng/dev_toolkit/api/endpoints/distribution.py`（新）, `src/backend/bisheng/dev_toolkit/api/router.py`（新）, `src/backend/bisheng/api/router.py`（**共享文件，纯追加**）
  **逻辑**: 两个匿名端点（D10）：`GET /api/v1/dev-toolkit/versions`（载荷照 design §4.2 ⑤，**一次留够 `sdk.*` 字段位**）与 `GET /api/v1/dev-toolkit/cli/download`（`FileResponse(wheel_path, filename=…)`）。模板 = `GET /api/v1/env`（`api/v1/endpoints.py:62-63`：普通 `@router.get`，**函数签名里没有任何 auth `Depends` 即匿名**）；`FileResponse` 写法照 `open_endpoints/api/endpoints/filelib.py:496-506`（自动 `Content-Length`、支持 Range、零内存放大）。产物用 `Path(__file__).resolve().parents[N] / "artifacts"` 定位（写法同 `linsight/builtin_skill_seeder.py`）。
  **⚠️ 产物缺失是常态分支、不是异常**（审查新增）：未跑 `pack_cli_wheel.sh` 的检出里 `artifacts/` 是空的 → `versions` **恒 200**、`cli` 段给 `null` + 一句可读说明（形状不变、字段位保留，agent 的解析不会因此崩）；`download` 给 **404 + 可读 message**。**绝不让 `FileResponse` 对着不存在的路径抛**（500 + traceback 会把"产物没提交"这个发版问题伪装成"平台坏了"）。
  **⚠️ 落点没有选择余地**：`/api/v2/**` 下**结构性否决**（F049 计划把 `verify_open_api_access` 提升到整个 `router_rpc`，`bisheng/api/router.py:123-126` 的注释，届时那里放匿名端点是永久例外）；裸路径 `/cli/download` **不可达**（商业版网关只转发 `/api/v1/**` 与 `/api/v2/**`，`docs/architecture/11-gateway.md:36-37`；OSS nginx `docker/nginx/conf.d/default.conf:50` 同形）。
  **⚠️ AC-05 的落地 = 条件注册，不是抛 404**：`if settings.open_platform.enabled:` 为假时**根本不 `include_router`**（`core/config/open_platform.py:16-20` 是**进程级 YAML 配置、非 DB 热配置**）→ FastAPI 天然 404。收益三条：字面满足"呈不存在"、**零新错误码**（CON-8）、不留探测面。代价 = 改配置要重启后端，这正是进程级配置的既有语义。
  **⚠️ 不用 MinIO 预签 URL**：安装件是随镜像发布的静态物；且 `clear_minio_share_host`（`minio_storage.py:686`，docstring `:687-691` 逐字说明"让前端通过 nginx 代理访问资源"）会返回依赖前端 nginx 的相对路径，CLI 直连时拿不到可用 URL。
  **⚠️ 不 import `database/models`、不查 DB**（RULE-3；本轮只读磁盘产物）。
  **跨 Feature 冲突面**: `bisheng/api/router.py` 的 `:66-112` 一片同时被 **F054 T035/T057** 与 **F055 T039/T041** 追加 `include_router`；三方都是纯追加，**解冲突时三行都要保留**；本任务的 include 是**条件的**，不要"顺手统一"成无条件。
  **测试**: T027 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-05
  **依赖**: T027

- [ ] **T029**: `[MVP-核心]` `/api/v1/dev-toolkit` 进 `TENANT_CHECK_EXEMPT_PATHS`
  **文件**: `src/backend/bisheng/utils/http_middleware.py`（`TENANT_CHECK_EXEMPT_PATHS`，`:16-44`，**共享文件、增一条**）
  **逻辑**: 追加前缀 `"/api/v1/dev-toolkit"` 并写一行注释说明理由。**这不是可选优化**：多租户开启时无 JWT 的请求**不会**调 `set_current_tenant_id`（`http_middleware.py:107-112` 只在 `not multi_tenant.enabled` 时兜底），任何 DAO SELECT 都会 `NoTenantContextError`；豁免名单会把整棵调用树置于 `_bypass_tenant_filter`（`:321-323`）。本端点若严格只读磁盘可以不加，但**版本端点要回 `open_platform_enabled` / `app_runtime_enabled` 且将来极可能读表**，现在就加更省事（D10）。
  **回滚**: 删该行即回滚，无数据变更。
  **测试**: T027 的 `test_multi_tenant_enabled_no_jwt_does_not_raise_no_tenant_context` 通过。
  **覆盖 AC**: AC-01, AC-05
  **依赖**: T028

- [ ] **T030**: `[MVP-核心]` `scripts/pack_cli_wheel.sh` + `artifacts/` 布局（构建契约）
  **文件**: `scripts/pack_cli_wheel.sh`（新，骨架照 `scripts/pack_linsight_skill.sh:1-40`）, `src/backend/bisheng/dev_toolkit/artifacts/manifest.json`（新，初始占位 + 说明）
  **逻辑**: `uv build` 产 wheel → 校验（文件非空、`bisheng_cli/` 在包内、版本与 `bisheng_cli.__version__` 一致）→ **装 wheel 冒烟**（见下）→ 拷进 `src/backend/bisheng/dev_toolkit/artifacts/` → 写 `manifest.json`（`{cli:{version,min_compatible,filename,sha256}, platform:{version}}`，T028 的端点读它）。脚本失败一律非零退出、把失败原因写清（照 `pack_linsight_skill.sh` 的 `[FAIL] …` 风格）。
  **⚠️ 冒烟必须装进一个干净 venv 并 import 生产入口**（2026-08-17 审查新增，本轮真事故的直接对策）：`uv venv /tmp/bisheng-cli-smoke && <该 venv>/bin/pip install <刚产的 wheel>` → ① `python -c "import bisheng_cli.main"`（**模块级 import**，把"依赖解析出来的新版本在 import 期就崩"这一类挡在发版之前）· ② `bisheng --version` 退出码 0 且输出 == `bisheng_cli.__version__`（顺带验 console script 真的注册上了）· ③ `bisheng deploy --help` 退出码 0（验 argparse 树可构建）。**三条任一失败 = 脚本非零退出、不拷产物**。判据：app-proxy 的 `fastapi>=0.115` 在开发机测全绿、生产解析到 0.141 后 `uvicorn` 模块级 import 当场崩——**源码树里跑 pytest 永远看不见这一类**，因为它测的是 dev 环境已解析好的那组版本；而 CLI 的分发路径就是"在别人机器上 pip install"，冒烟不做等于把这一步外包给客户。
  **⚠️ 为什么产物必须随后端包同行并提交进 git**（坑 11，最容易在生产翻车的一条）：backend 镜像的 build context **只有 `./src/backend/`**（`.github/workflows/ci.yml:54` 的 `docker buildx build … ./src/backend/` + `src/backend/Dockerfile:13` `COPY ./ ./`）→ **`src/bisheng-cli/` 不在镜像内**。判据照 `linsight/builtin_skill_seeder.py:45-47` 逐字："inside the package so every deployment shape (docker COPY, rsync, pip install) carries it automatically"。**目录名不能叫 `build` / `lib` / `wheels` / `sdist`**——`.gitignore:137,148,150,152` 是无前导斜杠的全局规则，任何层级同名目录都被忽略、产物 `git add` 静默失败。落码后**必须跑一次 `git check-ignore -v src/backend/bisheng/dev_toolkit/artifacts/<wheel>` 确认无命中**。
  **发版契约**（写进脚本头注释与 T032 的 README）：**改了 CLI 就必须重跑本脚本并把产物一起提交**，否则平台分发的是旧 wheel；114 是真 git 检出 + `bash /opt/bisheng-ops/deploy.sh`、不走镜像，**两条路径都要验**。
  **覆盖 AC**: AC-01
  **依赖**: T001, T010

- [ ] **T031**: `[MVP-核心]` CI 接入（ruff + `pytest -m "not network"` + 版本漂移守卫）
  **文件**: `.github/workflows/cli-quality.yml`（**新建独立 workflow 文件**——审查订正：原文只写到目录级、"新增一个 job"若落进既有 `ci.yml` 就变成共享文件的合并冲突面；独立文件把冲突面降到零，形制照 `frontend-quality.yml` 的同级地位。**不改任何既有 workflow 的 steps**）
  **逻辑**: 新 workflow **三条 leg**（审查修订，原文只有第一条）：
  1. **锁定解析**：`cd src/bisheng-cli && uv sync --frozen && uv run ruff check . && uv run pytest -m "not network"`（**`--frozen`**：`uv.lock` 是提交进 git 的，CI 必须用它、不许就地重解析——口径同 `src/backend/Dockerfile:7` 的 `uv sync --frozen --no-dev`）。
  2. **装 wheel 冒烟**：跑 `bash scripts/pack_cli_wheel.sh` 并断言其内置冒烟通过（T030 的三条：`import bisheng_cli.main` · `bisheng --version` · `bisheng deploy --help`）。**这是唯一一条真的按"用户拿到的形态"验证的 leg**。
  3. **上界哨兵（allow-failure，只告警不阻断）**：`uv sync --upgrade`（或 `--resolution highest`）装到当前可解析的最新依赖后**只跑冒烟**（不跑全量），提前暴露"上界该抬了 / 新版本有 breaking"的那一天；红了就去看是抬上界还是钉版本，**不许直接删上界**。
  再加一步**版本漂移守卫**——断言 `bisheng_cli.__version__` == `src/backend/bisheng/dev_toolkit/artifacts/manifest.json` 的 `cli.version`，不一致即失败（防"改了 CLI 忘了重跑 T030 的脚本"）；顺带断言 `git check-ignore -v <artifacts 里的 wheel>` **无命中**（坑 11 的产物被全局 `.gitignore` 规则吞掉那条，落码时验过一次不代表以后不会被人改回来）。
  **⚠️ 为什么必须接 CI**（design §7）：仓内 CI 目前**不跑** runtime-manager / app-proxy 的任何测试（`.github/workflows/{ci,test,release,base_ci}.yml` 零命中）——CLI 不接进去就会和它们一样长期无人验证。
  **覆盖 AC**: —（工程保障任务，不直接承载 AC；它保的是 T003–T026 的测试不腐坏）
  **依赖**: T002, T030

- [ ] **T032**: `[MVP-核心]` README 与排障口径（对外契约的人读面）
  **文件**: `src/bisheng-cli/README.md`（新）
  **逻辑**: 内容 = ① 安装（从平台下载端点 `pip install <url>`，纯内网零公网依赖）；② 三条命令与全部参数（照 design §4.2 ①），**尾部明说 `dev` / `skills sync` 随后续版本提供**；③ **退出码全表**（§4.2 ②，agent 的自动化判定依据，是对外契约的一部分）；④ `--json` NDJSON 事件契约（三种事件、`result` 恒为最后一行）；⑤ 排障口径三条——**先看 body 的 `status_code` 是 `20001` 还是 `260xx`**（多租户下默认租户被禁用会给一个与密钥无关的 `20001`/403，把它当"密钥不对"会让用户反复重签密钥，坑 7）· 代理环境变量与 `NO_PROXY`（坑 2）· `deployment_id` 是与平台侧对账的唯一凭据（服务端观测在 F055 的 `app_deployment` 表与 `app.release.*` 审计事件，"CLI 说失败了"要以它去那两处对账）；⑥ 发版契约（改 CLI 必重跑 `scripts/pack_cli_wheel.sh` 并提交产物，T030）。**不写"未来会有什么"的承诺清单**（顺延项的落点在 design §1 / §8，README 只写今天能用的）。
  **覆盖 AC**: AC-03, AC-04（退出码表与 NDJSON 事件契约是对外契约的人读面）
  **依赖**: T024, T026, T030

- [ ] **T033**: `[MVP-核心]` 114 部署与手动验证清单（演示剧本步 2–3）
  **文件**: `features/v3.0.0/053-dev-cli-skills/tasks.md`（本文，回填执行结果）
  **逻辑**: 按 design §7「114 手动验证」逐条执行（⚠️ 部署用 `bash /opt/bisheng-ops/deploy.sh`，**不要 rsync**，memory `reference_remote_dev`）：
  0. 平台侧确认开关：`curl -s http://<114>/api/v1/env` 读 `open_platform_enabled` / `app_runtime_enabled`；**开关关时 `curl /api/v1/dev-toolkit/versions` 必须 404**（这就是 AC-05 的现场验证）。
  1. 装 CLI **两条路径都要验**：① `curl -sO http://<114>/api/v1/dev-toolkit/cli/download && pip install ./bisheng_cli-3.0.0-py3-none-any.whl`；② 直接 `pip install http://<114>/api/v1/dev-toolkit/cli/download`。`bisheng --version` 与端点 `versions` 一致。
  2. `BISHENG_API_KEY=bs-sak-… bisheng login http://<114>`（key 来自演示剧本步 1 签发、勾了 `app:manage`）→ `ls -l ~/.bisheng/credentials.json` **必须是 `-rw-------`**。
  3. `bisheng deploy --dry-run` 看打包体量与忽略统计 → `bisheng deploy --wait --json | tee deploy.ndjson; echo "exit=$?"` → `tail -1 deploy.ndjson` 是 `result` 行且 `exit_code` 与进程退出码一致。
  4. `bisheng logs --tail 200`（⚠️ **2026-08-17 审查回正**：runtime-manager 侧的 `GET /v1/apps/{id}/logs` **已实现**（F054 T030/T031，commit `d693feeb3`）；本步能否验到内容取决于**链路中段**的 F054 **T057** 与 F055 **T039** 是否已上 114 —— 未就绪则只验错误呈现（`16207` / `26003` / `16254`），就绪则连带验 `--since 30m` 与 `--keyword`（**带 keyword 时行数少于 `--tail` 是正常的**）。dockerd 停掉一次验 `16121` 走的是"稍后重试"而不是"应用不存在"）。
  5. **失败面演练**：`runtime` 改错验 16222；塞一个含 `bs-sak-` 字面量的文件验 16241（**断言输出里没有那个值**）；把 `.venv/` 造大验超限报告与 Top 10。
  6. **AC-42 必须用第二把「资源归属人不同」的密钥验证**——同一把永远通过，测了等于没测。
  7. **AC-52**：管理员去掉 `app:manage` 位 → **等 5 秒**（服务端 3 秒正向缓存、硬顶 5，`core/config/open_platform.py:31-35`，坑 16）→ 不重新 `login` 直接跑 `bisheng deploy`，应即刻按新权限位被拒。
  **⚠️ `health 200` 会骗人**（admin 短路 ReBAC，memory `reference_remote_dev`）：CLI 的所有权限相关判定都走服务账号（非 admin），**平台侧任何用浏览器 admin 账号做的旁证都不算数**。
  **⚠️ 本轮无法在 114 验证的项**：`delegate` 拒绝（F049 期签不出该位，坑 15）· `logs` **内容**（取决于 F054 T057 与 F055 T039 是否已上 114；**不是**"runtime-manager 没实现"——那截已落码）——单测已覆盖，不要因为 114 上试不出来就改代码。
  **旅程引用**（不由本 Feature 验收，只在剧本里连带跑过）：AC-48「上线 ≠ 可用，owner 设可见范围后同事才能从广场打开」**经 F054 / F056 验证**；AC-50「经 CLI 发布的应用在广场 / 权限 / 审计中与平台内造应用一致、每次发布必审、扫描同规则集、元信息取自 `bisheng-app.yaml`」**经 F055 验证**。
  **覆盖 AC**: AC-01, AC-04, AC-05, AC-06, AC-07, AC-31, AC-31a, AC-31b, AC-31c, AC-32, AC-33, AC-35, AC-41, AC-42, AC-52
  **依赖**: T020, T024, T026, T028, T029, T030, T032

- [ ] **T034**: `[MVP-核心]` 上游回写四项 + 顺延项落点核对
  **文件**: `features/v3.0.0/053-dev-cli-skills/spec.md`（AC-05 措辞）, `features/v3.0.0/049-openapi-auth-baseline/tasks.md`（追加回写条目）, `features/v3.0.0/055-app-publish-pipeline/tasks.md`（追加回写条目）
  **逻辑**: design §8 已登记的四项，逐条落到上游文档（**只追加条目、不改他人代码**）：
  1. **F049 给 `WhoamiResponse` 加 `resource_owner: {user_id, user_name}`**——`WhoamiResponse`（`open_api/domain/schemas/credential.py:108-116`）只有 `subject_kind` / `service_account` / `tenant_id` / `scopes` / `key_mask` / `expires_at`，而 `OpenApiPrincipal.resource_owner_user_id` 在服务端**已经存在**（`open_api/domain/context.py:37-39`）。改动量 = 一个可选字段 + 一次 user 名查。**为什么值得改**：资源归属人就是此后 `deploy` 出的应用 owner，管理员选错归属人是 F049 自己在签发表单上加风险提示的那个错误；`login` 那一刻看不到它，这个错要等到 deploy 之后甚至换人接手时才暴露。补上之前 T020 走降级（AC-06 标 `[受阻于 F049 回写]`）。
  2. **F055 给 `GET /api/v2/apps/{id}/logs` 的返回补 `app_state` / `pending_reason`**——目前只有 `{lines[]}`，AC-43「明确提示应用态」只能降级（T026）。
  3. **F055 给 `GET /api/v2/apps/deployments/{id}` 的轮询载荷补 `entry_url`**（`app_state=已上线` 时非空）——它目前**只在 `POST /deploy` 的返回里**（`055-.../design.md:492`），而首发时应用还是草稿、大概率为 `null` → AC-31c「通过并上线（输出入口地址）」/ AC-33 / 决议-12 只能降级为"指路应用详情页"（T024）。
  4. **改本 spec 的 AC-05 措辞**——「login 校验入口在开放能力层未部署时不可达」与 F049「服务账号模块恒在 + `whoami` 恒在注册」的既成实现冲突（`api/router.py:123-126`；`core/config/open_platform.py:17-18` 注释逐字："the service-account module is always on"）。建议改成「CLI 的 `login` 在该环境不可用并给出可读原因」，由 T008 的前置探测 + exit 8 兑现。**改 spec 而不是改 F049**——把 whoami 也置于开关下，等于让 F049 的显式设计破例并波及已落码的鉴权面。
  **另有一项由 F055 侧发起、本 Feature 只需接受**：F055 T050 回写项 3 已登记「AC-32 的上限经 `deploy-limits` 取、取不到由 16201 兜底」——T017 / T022 已按该口径写，**不要另立一套**。
  **顺延项落点核对**：确认 design §1 非目标表的落点方向与本文 Wave 3–5 的任务标题一一对应，无遗漏、无新增。
  **覆盖 AC**: AC-05, AC-06, AC-31c, AC-33, AC-43（本任务不新增行为，只解除这五条的降级前提；降级实现本身已由 T008 / T020 / T024 / T026 覆盖）
  **依赖**: T020, T024, T026

---

### Wave 3 · 顺延：`skills sync` 与 DEV-03 两包技能包（release 必做，本轮不做）

> design §8 把这一波列为顺延波次的**最高优先级**——它是 AC-47「agent 全程不离开本地对话」的前提。分发端点与匿名口径已由 T028 留位（`GET /api/v1/dev-toolkit/skills/{pack}`，同 router）。

- [ ] **T035**: `skills sync` 命令（拉取 / 幂等覆盖 / 输出每包名称与版本与更新结果 / 列出被覆盖文件）
  **文件**: `src/bisheng-cli/bisheng_cli/commands/skills.py`, `src/bisheng-cli/bisheng_cli/cli.py`（注册第四条命令）
  **测试载体**: `src/bisheng-cli/tests/test_command_skills.py`
  **覆盖 AC**: AC-03, AC-14, AC-19, AC-20, AC-21, AC-51

- [ ] **T036**: 技能包分发端点 + 包随后端发布件同行
  **文件**: `src/backend/bisheng/dev_toolkit/api/endpoints/distribution.py`（增量加 `skills/{pack}`）, `src/backend/bisheng/dev_toolkit/skills/`
  **测试载体**: `src/backend/test/dev_toolkit/test_distribution_api.py`（增量）
  **覆盖 AC**: AC-05, AC-14, AC-15

- [ ] **T037**: 「部署纳管」包内容（`bisheng-app.yaml` 写法引用 F055 / 能力声明 / 安全红线 / 托管运行契约 / deploy 工作流与预检排障指引 + 样例 + 连通自检脚本）
  **文件**: `src/backend/bisheng/dev_toolkit/skills/deploy-hosting/`
  **测试载体**: `src/backend/test/dev_toolkit/test_skill_packs.py`（结构完整性 + 样例无真实密钥 + 自检脚本缺配置时输出可读原因而非堆栈）
  **覆盖 AC**: AC-16, AC-18, AC-19

- [ ] **T038**: 「平台能力接线」包结构 + 两条不走 SDK 的标准库接法（模型 / 应用数据库）；**SDK 三件套章节与其自检脚本随 F057 补齐、其验收随 F057**
  **文件**: `src/backend/bisheng/dev_toolkit/skills/platform-wiring/`
  **测试载体**: `src/backend/test/dev_toolkit/test_skill_packs.py`（增量）
  **覆盖 AC**: AC-17, AC-18

- [ ] **T039**: `login` 成功后自动执行一次 `skills sync`（失败不影响登录成功、输出原因并提示可手动重跑）
  **文件**: `src/bisheng-cli/bisheng_cli/commands/login.py`（增量）
  **测试载体**: `src/bisheng-cli/tests/test_command_login.py`（增量，替换 T019 的 `test_no_auto_skills_sync_this_round`）
  **覆盖 AC**: AC-08

- [ ] **T040**: 技能包触发评测样本集与跑分（≥ 10 条不含产品名的中性部署表述，「部署纳管」包触发率 100%；auth 静默失败点对照样本随 F057）
  **文件**: `src/backend/test/dev_toolkit/fixtures/skill_trigger_samples.md`, `src/backend/test/dev_toolkit/test_skill_trigger.py`
  **覆盖 AC**: AC-22

- [ ] **T041**: 跨 Feature 旅程验收（接入信息文本 + key → `login` → 调通一次 MCP 工具；agent 凭技能包 + CLI + MCP 完成声明补全 → deploy → 预检修复 → 审批状态跟踪）
  **文件**: `features/v3.0.0/053-dev-cli-skills/tasks.md`（回填执行结果）
  **前置**: F052（MCP 面）就绪
  **覆盖 AC**: AC-46, AC-47

---

### Wave 4 · 顺延：`bisheng dev` 本地运行与身份注入（release 必做，本轮不做）

> 依赖 F054 app-proxy 的注入头形态与 F057 SDK，两者本轮都不在纵切上。**注入的环境变量清单不得自造**，唯一来源 = [`contracts-runtime-manager.md` §5](../054-app-domain-runtime/contracts-runtime-manager.md)（design §6.2 表末行已原样登记：`BISHENG_APP_DB_URL` · `BISHENG_APP_DB_PATH` · `BISHENG_APP_ID` · `BISHENG_APP_SLUG` · `BISHENG_APP_VERSION` · `BISHENG_APP_VERSION_ID` · `BISHENG_PLATFORM_API_BASE` · `PORT` 与 `BISHENG_APP_PORT`（恒等）· `BISHENG_APP_BASE_PATH`（dev 期为空串）· `BISHENG_APP_HEALTH_PATH`；平台保留 env 名**覆盖**调用方同名值）。

- [ ] **T042**: `dev` 迷你代理：注入与 F054 app-proxy **结构一致**的身份头 + 每请求短时访问凭据句柄；**剥离客户端伪造的平台身份注入头**（剥离规则与 F054 一致：按下划线 / 连字符 / 大小写归一化等价类匹配）；无 `--as`
  **文件**: `src/bisheng-cli/bisheng_cli/commands/dev.py`, `src/bisheng-cli/bisheng_cli/devproxy.py`
  **测试载体**: `src/bisheng-cli/tests/test_dev_proxy.py`
  **覆盖 AC**: AC-03, AC-23, AC-25

- [ ] **T043**: `dev` 本地 SQLite + 与托管运行期**同名**的连接环境变量注入；数据跨重启保留、位于项目本地且不进上传包；同名平台接线环境变量注入（清单来源见上）
  **文件**: `src/bisheng-cli/bisheng_cli/devdb.py`, `src/bisheng-cli/bisheng_cli/commands/dev.py`（增量）
  **测试载体**: `src/bisheng-cli/tests/test_dev_env.py`
  **覆盖 AC**: AC-26, AC-27

- [ ] **T044**: `dev` 启动前置校验与输出（未 `login` / 凭据无效 / 平台不可达 → 拒绝并提示；缺 manifest 或必填项 → 拒绝并列缺失项；输出注入身份来源与账号、本地访问地址；`dev` 本身不验权限位）
  **文件**: `src/bisheng-cli/bisheng_cli/commands/dev.py`（增量）, `src/bisheng-cli/bisheng_cli/cli.py`（注册第五条命令）
  **测试载体**: `src/bisheng-cli/tests/test_command_dev.py`
  **覆盖 AC**: AC-03, AC-24, AC-29, AC-53

- [ ] **T045**: `dev` 期平台能力调用按服务账号**被显式授予**的范围放行（经 F051 / F052 面执行，过滤强度与 fail-closed 与线上一致；迷你代理只注入身份与环境、不代理这些调用）+ 「本地与线上同构」端到端（同一份代码 `dev` 跑通后 `deploy` 上线，托管环境取到的是**当前访问用户**身份）
  **文件**: `features/v3.0.0/053-dev-cli-skills/tasks.md`（回填执行结果）
  **前置**: F051 / F052 / F054 app-proxy 就绪
  **覆盖 AC**: AC-28, AC-49

---

### Wave 5 · 顺延：平台侧接入信息区与 CLI 其余顺延项（release 必做，本轮不做）

- [ ] **T046**: 接入信息区（platform 服务账号详情页「API 密钥」tab 顶部：MCP 地址 / OpenAI 兼容 base URL / CLI 下载链接 / `bisheng login` 指引）+ 「一键复制接入信息」（**不含 key 值，也不含任何可换取 key 值的凭据**；实时生成不做快照；无分享链接 / 二维码 / 站内信推送）；未部署开放能力层时该区不出现
  **文件**: `src/frontend/platform/src/pages/ServiceAccount/`（F049 已建的详情页增量）, `src/frontend/platform/src/controllers/API/`（读 `dev-toolkit/versions`）, `src/frontend/packages/locales/`（三语）
  **测试载体**: 手动验证（Playwright 未落地）+ `src/backend/test/dev_toolkit/test_distribution_api.py` 已覆盖端点侧
  **覆盖 AC**: AC-44, AC-45

- [ ] **T047**: 多平台凭据的**交互层**（`--platform` 参数注册 · profile 列出与切换默认平台）——数据结构已由 T012 落好，本任务零迁移
  **文件**: `src/bisheng-cli/bisheng_cli/cli.py`, `src/bisheng-cli/bisheng_cli/credentials.py`（增量）
  **测试载体**: `src/bisheng-cli/tests/test_credentials.py`（增量）
  **覆盖 AC**: AC-12

- [ ] **T048**: 版本兼容**阻断**（不兼容即拒绝执行并给出从当前平台重新下载的链接；兼容但落后仅提示）——开启方式 = 把 T008 前置探测里的 warning 升为 `CliError(exit=2)`
  **文件**: `src/bisheng-cli/bisheng_cli/http.py`（增量）
  **测试载体**: `src/bisheng-cli/tests/test_http.py`（增量）
  **覆盖 AC**: AC-02

- [ ] **T049**: 非 Claude Code 引擎经 AGENTS.md 引用同一技能目录的指引（sync 完成后输出引用方式）
  **文件**: `src/bisheng-cli/bisheng_cli/commands/skills.py`（增量）, `src/backend/bisheng/dev_toolkit/skills/README.md`
  **测试载体**: `src/bisheng-cli/tests/test_command_skills.py`（增量）
  **覆盖 AC**: AC-20

> **不做、且被提议过不止一次的四项**（design §8 / spec §范围边界与决议-2 / 决议-12，**不要再提回**）：CLI 侧复制一份密钥扫描规则集做本地预扫（同一规则集分两处必漂移，扫描只在 F055 服务端做一次）· `init` / 工程骨架生成 · `logout` / `whoami` 子命令（登出 = 删凭据文件或重新 `login` 覆盖）· CLI 生成二维码（去应用详情页 · 发布取）。单文件二进制是 v3.1 备选（决议-1），下载端点届时按 `?platform=&arch=` 分发、`versions` 载荷加 `assets[]`（形状已留位）。

---

## AC 追溯表

> 逐条列举、无范围写法。`[MVP-核心]` 列标 ✅ 的 AC 在本轮闭环；标 ⏭ 的随顺延波次；标 ↗ 的由其它 Feature 验收。

| AC | 覆盖任务 | 本轮 |
|---|---|---|
| AC-01 | T027, T028, T029, T030, T033 | ✅ |
| AC-02 | T007, T008, T009, T010, T027, T028；阻断随 T048 | ✅（只提示不阻断） |
| AC-03 | T009, T010（本轮三条 + 无 `--as` / `init` 断言）, T032（README 明说顺延命令）；五条齐备随 T035, T042, T044 | ✅（显式偏离登记，见开发模式） |
| AC-04 | T003, T004, T005, T006, T007, T008, T009, T010, T019, T020, T021, T032, T033 | ✅ |
| AC-05 | T007, T008, T027, T028, T029；措辞回写 T034 ④ | ✅（login 校验入口一半以前置探测等价兑现） |
| AC-06 | T011, T012, T019, T020；资源归属人字段回写 T034 ① | ✅（降级：`[受阻于 F049 回写]`） |
| AC-07 | T011, T012, T017, T018, T019, T020, T033 | ✅ |
| AC-08 | T019（断言本轮不触发）, T039 | ⏭ |
| AC-09 | T019, T020 | ✅（只能单测，坑 15） |
| AC-10 | T003, T004, T007, T008, T019, T020 | ✅ |
| AC-11 | T003, T004, T007, T008, T019, T020 | ✅ |
| AC-12 | T011, T012, T019, T020（数据结构与覆盖语义）；交互层 T047 | ✅（数据结构） |
| AC-13 | T003, T004, T019, T020 | ✅ |
| AC-14 | T035, T036 | ⏭ |
| AC-15 | T036 | ⏭ |
| AC-16 | T037 | ⏭ |
| AC-17 | T038 | ⏭ |
| AC-18 | T037, T038 | ⏭ |
| AC-19 | T035, T037 | ⏭ |
| AC-20 | T035, T049 | ⏭ |
| AC-21 | T035 | ⏭ |
| AC-22 | T040 | ⏭ |
| AC-23 | T042 | ⏭ |
| AC-24 | T044 | ⏭ |
| AC-25 | T042 | ⏭ |
| AC-26 | T043 | ⏭ |
| AC-27 | T043 | ⏭ |
| AC-28 | T045 | ⏭ |
| AC-29 | T044 | ⏭ |
| AC-30 | T003, T004, T013, T014, T021, T022 | ✅ |
| AC-31 | T007, T008, T017, T018, T021, T022, T033 | ✅ |
| AC-31a | T021, T023, T024, T033 | ✅ |
| AC-31b | T023, T024, T033 | ✅ |
| AC-31c | T023, T024, T033；`entry_url` 回写 T034 ③ | ✅（上线分支降级为"指路详情页"） |
| AC-32 | T015, T016, T017, T018, T021, T022, T033 | ✅ |
| AC-33 | T013, T014, T021, T022, T023, T024, T033 | ✅（入口地址同上降级） |
| AC-34 | T003, T004, T021, T022 | ✅ |
| AC-35 | T003, T004, T005, T006, T023, T024, T033 | ✅ |
| AC-36 | T009, T010, T021, T022 | ✅ |
| AC-37 | T021, T022 | ✅ |
| AC-38 | T021, T022 | ✅ |
| AC-39 | **墓碑**（spec 2026-08-17 审查裁定 2 已删除，编号保留不复用；原内容并入 AC-50） | — |
| AC-40 | T003, T004, T021, T022, T025, T026 | ✅ |
| AC-41 | T025, T026, T033 | ✅（单测闭环；114 联调受阻于 **F054 T057 + F055 T039**——manager 侧 T030/T031 已落码，见 T032 说明） |
| AC-42 | T025, T026, T033（必须用第二把归属人不同的密钥） | ✅ |
| AC-43 | T025, T026；`app_state` 回写 T034 ② | ✅（降级：明确提示而非空白） |
| AC-44 | T046 | ⏭ |
| AC-45 | T046 | ⏭ |
| AC-46 | T041 | ⏭ |
| AC-47 | T041 | ⏭ |
| AC-48 | **旅程引用，经 F054 / F056 验证**；T033 剧本连带跑过，本 Feature 不单独验收 | ↗ |
| AC-49 | T045 | ⏭ |
| AC-50 | **经 F055 验证**（每次发布必审 / 扫描同规则集 / 元信息与档位取自 `bisheng-app.yaml`）；T033 剧本连带跑过 | ↗ |
| AC-51 | T011, T012, T021, T022, T025, T026 | ✅ |
| AC-52 | T007, T008, T011, T012, T033（等 5 秒余量） | ✅ |
| AC-53 | T044 | ⏭ |

**统计**：spec 的 55 条有效 AC（AC-01–AC-53 连号 + AC-31a/b/c 三条，AC-39 为墓碑不计入覆盖）→ **未覆盖 0 条**。其中本轮 `[MVP-核心]` 闭环 **30** 条（✅）、随顺延波次 **23** 条（⏭）、跨 Feature 旅程引用 **2** 条（↗ AC-48 / AC-50）。

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

### Wave 1（2026-08-17 实施）

1. **`26004` / `26031` 的退出码 design 漏定，2026-08-17 裁决为新开 exit 18「缺陷类」**（既不是 exit 1、也不是 exit 19；实施方初版取 1 / 19，已改）。退出码表的唯一用途是让本地 coding agent 不读散文就能决定下一步，所以分格判据是**动作是否不同**：exit 1（CLI 崩了）值得重试一次；exit 19（未登记码）读 `message` 后可改参数重试；而这两个码**重试与改参数都保证无用**，唯一动作是停下报障——第三种动作即第三个码。把已登记的 `26031` 映到 19（其语义是「未登记的码」）还会给出假标签。已同批改 `errors.py`（新增 `EXIT_DEFECT = 18`）与 design §4.2 ② 退出码表（新增 18 行 + 裁决说明），并补两个单测：`test_defect_class_gets_its_own_exit_code_not_1_or_19`、`test_registered_code_wins_over_5xx_degradation`（后者防止 `26031` 携带的 HTTP 500 把「报障」降级成「稍后重试」，而重试永远不会成功）。
2. **新增 `tests/test_import_smoke.py`（tasks 未列）**——依赖上界的另一半保险：模块级 import 全部 CLI 模块 + 生产入口 `bisheng_cli.main:main`。理由＝ app-proxy 的 `fastapi>=0.115` 事故里 69 个用例全绿而生产 import 即崩，只有模块级 import 能在 collection 阶段抓到。同批已落：两条依赖都带上界（`httpx>=0.27,<1.0` / `PyYAML>=6.0,<7.0`）、`uv.lock` 提交进 git、wheel 装进干净 venv 后跑 `bisheng --version` / `--help`（default 与 `--resolution highest` 两条腿都验过）。
3. **`ignore.py` 的子集解析器有一条与 git 的已知语义差**——git 不允许用 `!` 把「已被忽略目录下的文件」取回，本解析器允许。刻意保留：`.bishengignore` 本就是「子集兜不住的复杂规则的显式出口」（D4 第 3 层），且该差异只能从 `.bishengignore` 触发、`.gitignore` 路径恒走 git 本身。已写进 `ignore.py` 模块 docstring。
4. **硬链接改为按普通文件打包，不跳过**（2026-08-17 裁决，`packaging.py::_special_kind` 已移除 `S_ISREG and st_nlink > 1` 分支）。原实现按 D4「符号链接 / 硬链接 / 设备文件 / FIFO 本地就跳过并列出」逐字做，代价是硬链接文件的**内容不进包**。**裁决理由：那条要求的前提是假的**——服务端拒的是 tar 里的 hardlink 成员，而该成员只在 tarfile 自行挑类型时产生（`TarFile.add` / `gettarinfo` 查 `self.inodes`）；`packaging.py` 逐条手工构造 `TarInfo`（默认 `REGTYPE`）再 `addfile` 流式写内容，这条路径**产不出** hardlink 成员。为一个不会发生的成员类型丢掉普通文件的内容，且 `st_nlink > 1` 既不是作者选的、他也看不见——是纯损失。design D4 与坑 14 已同批订正；新增 `test_hardlinked_regular_file_is_packed_with_its_contents` 断言成员为 `isreg()` 且内容完整。
5. **`mask()` 归 `output.py`、`errors.py` 反向 import 它**——design §4.3 把掩码器划给 `output.py`，而 `errors.render_human()` 必须掩码（T003 `test_no_error_text_contains_key_material`）。`output.py` 不 import `errors.py`，无环。
6. **命令 handler 采用「注册结构在 `main.py`、实现懒加载」**——`main._HANDLER_PATHS` 存 `"模块:函数"` 字符串，`resolve_handler()` 才 import。Wave 1 里 `commands/{login,deploy,logs}.py` 尚不存在，`--help`、参数解析、异常收口与退出码全部可测可用；Wave 2 只需新增模块文件，不改 `main.py` / `cli.py` 的注册结构（T010 逐字要求）。
7. **`arch-guard.sh` RULE-7 在本工程零输出**——但踩到一次自指的坑：conftest 的 docstring 里**引用**该规则的正则示例本身命中了规则。已改写成散文描述。后人写「本规则长什么样」的注释时同理。

