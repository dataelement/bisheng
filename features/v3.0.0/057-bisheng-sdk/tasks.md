# Tasks: bisheng-sdk（Python 首发三件套 auth / retrieve / storage + 开发者指南）

**关联规格**: [spec.md](./spec.md)（36 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D16 / 坑 1–36 / §4.2 契约 ①–⑦ / §6.2 阻塞项与回写）
**版本**: v3.0.0
**纵切**: 不在 [mvp-114-path.md](../mvp-114-path.md) §2 纵切上；无 `[MVP-核心]` 标记，全部为 release 必做。
**代码事实口径**: 沿用 design.md（`3.0-vibe` `fe10f75ea`，2026-09-16）；**两个前置依赖分支按其源码为准**——`wt/storage-handle` `23886547f`（F054 T084 / T085 附件句柄）与 `wt/cli-dev` `b61b209e4`（F053 `bisheng dev` + `platform-wiring` 技能包），两者均**未合入 `3.0-vibe`**（坑 30 / 坑 31 / 坑 35）。SDK 路径以 `src/bisheng-sdk/` 为根、后端以 `src/backend/bisheng/` 为根、CLI 以 `src/bisheng-cli/` 为根、其余以仓库根为根。**行号会漂移、符号名不会——落地前一律以符号名重定位。**

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 初稿 + 同日独立审查 15 条修订，36 条 AC（决议 1–11） |
| design.md | ✅ 已评审（全自动模式定案） | 2026-09-16 初版 + 两次续写（末次按 `wt/cli-dev` 改写 D12 / D13 / D4 / D5 / D8，坑扩到 36）；`/sdd-review design` 已跑，发现就地修订；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-09-16） | 本文；**44 任务 / 7 Wave + 1 前置**；36 条 AC 全覆盖（追溯表见末尾）；`/sdd-review tasks` 已跑 |
| 实现 | 🚧 进行中 | **38 / 45**（两条切片已合流：`wt/f057-sdk-core` 交付包本体 Wave 0–3，`wt/f057-sdk-dist` 交付分发与文档 Wave 0 / 4 / 5 / 6。仍缺的是需要 114 或真实构建容器的端到端项，逐条见下。）|

---

## 开发模式

**按 Wave 组织**：
- **Wave 0**（T000）= 前置依赖分支合并核对（`wt/storage-handle` + `wt/cli-dev`）。
- **Wave 1**（T001–T009）= SDK 包工程 + 测试基建 + errors / 上下文 / auth。
- **Wave 2**（T010–T015）= HTTP 层 + 版本兼容 + retrieve。
- **Wave 3**（T016–T021）= storage（路径规则、本地后端、远端后端、门面与异步孪生）。
- **Wave 4**（T022–T029）= 平台分发（打包脚本、manifest 合并、artifact_service、四个端点、CI、提交 wheel）。
- **Wave 5**（T030–T032）= 托管构建期取包（runtime-manager extra index）。
- **Wave 6**（T033–T040）= 「平台能力接线」技能包**增量**（SDK 章 / retrieve / storage 两章 / SDK 样例 / 自检追加）+ 指南入口 + 评测样本 + CLI 包清单核对。
- **Wave 7**（T041–T043）= 端到端旅程、114 手验、跨 Feature 回写登记。

**执行序**：Wave 1 → 2 → 3 串行（共用 `_http.py` / `errors.py`）；Wave 4 与 Wave 1–3 只共享 `__version__`，可并行；Wave 5 依赖 Wave 4 的简单索引；Wave 6 依赖 Wave 1–4（样例与自检要 import 真 SDK）；Wave 7 最后。**T029（提交 SDK wheel）与 T038（重打 CLI wheel）都写 `bisheng/dev_toolkit/artifacts/`，必须串行且排在各自 Wave 末尾**（二进制冲突不可合并）。

**Test-First（SDK 版）**：测试任务先于配对实现任务；`覆盖 AC` **逐条列举**（禁范围写法）。
- **SDK 单测零网络**：`tests/conftest.py` 的 `no_network` autouse fixture 把 `httpx.Client` / `httpx.AsyncClient` 默认 transport 换成抛 `AssertionError("unmocked network call")` 的哨兵；平台交互一律经 `tests/helpers/platform_mock.py` 的 `httpx.MockTransport` 工厂。同步 / 异步两条路径**参数化跑同一组用例**（D10）。
- **需要真平台的用例**挂 `@pytest.mark.network`，默认跳过、CI 不跑、114 手验跑（照 `src/bisheng-cli/pyproject.toml` 的 marker 形态）。
- 测试目录 `src/bisheng-sdk/tests/`（`cd src/bisheng-sdk && uv sync --frozen --extra dev && uv run pytest`）。**不放进 `src/backend/test/`**——SDK 不 import `bisheng`（CON-1）。
- 平台侧改动的测试落 `src/backend/test/dev_toolkit/`（既有包，`asyncio_mode=auto`，conftest 已剥六个代理变量）；runtime-manager 侧落 `src/runtime-manager/tests/test_build.py`（增量）。
- **文本任务的 Test-First 例外（唯一两处，理由在此）**：T033（SKILL.md 增量）与 T034（`example-sdk/`）是散文与样例，先写断言再写正文只会把断言写成正文的复读机；它们的可判定断言集中在**同波次、同一 PR 的 T035**，且 T035 里有两条**回归型**断言（auth 章仍是目录第一条 + 章首警示块、模型章仍标「暂未提供」）守住 F053 已交付的契约。其余所有实现任务一律测试在前。

**自包含任务**：每个任务内联文件、逻辑、依赖、AC 覆盖；设计论证指向 design §X / D-x / 坑-x，不复制。

**不涉及的任务类别**（写明以免评审误判遗漏）：**无前端任务**（Platform / Client 都不改，本 Feature 的「界面」是 wheel、技能包与四个匿名端点，design C7）· **无 Worker / Celery 任务**（无异步作业，因此不涉及 `tenant_id` 经 Celery headers → ContextVar 的传递）· **无 ORM / 迁移任务**（无新表、无 Alembic revision，design C2；因此不需要回滚方案）· **无错误码模块**（D14，用户预留的 26400–26409 不使用）。

**⚠️ 三条实现红线（落码前逐条对照）**：
1. **SDK 代码里不得出现 `BISHENG_APP_TOKEN` / `BISHENG_API_KEY`**（CON-3 / 决议-2）——T014 有 grep 型断言；retrieve 的凭据只来自请求上下文的 `X-BiSheng-Access-Token`。
2. **`current_user()` 无注入即抛错，中间件不拒绝无头请求**（D3 / AC-07）——抛错点在读取处，不在中间件；不提供任何"宽松模式"参数。
3. **两个打包脚本必须合并写 manifest、只删自己前缀的 wheel**（D16 / 坑 9 / 坑 10）——否则重打 CLI 会静默让 `/versions` 的 `sdk` 段回到 null。

**⚠️ 四处"本轮无法端到端验证、只能 mock"的地方，实现者不要去 114 上试然后判定功能不生效**（design §6.2）：
- **托管期 retrieve**：后端 `validate_bearer` 只认 `bs-sak-` / `bs-pat-`（`credential_validator.py:43`），OBO Bearer 今天答 `26001`；且 `obo_secret` 未配时 app-proxy 根本不注入令牌（坑 4 / 5 / 阻塞项 ②）。
- **本地期 retrieve**：`bisheng dev` 已落地（`wt/cli-dev`），但它注入的 `X-BiSheng-Access-Token` 是**本地 HMAC 自签**的 `bsdev.` 句柄，平台无从验签，同样答 `26001`（坑 32 / 阻塞项 ③）。
- **本地期 storage**：`bisheng dev` **不注入任何 `BISHENG_APP_STORAGE_*`**（`devdb.py:INJECTED_ENV`，坑 34 / 契约 ⑦）；单测一律 `monkeypatch.setenv("BISHENG_APP_STORAGE_DIR", tmp_path)` 自造句柄。
- **托管期 storage**：附件 API 与三个注入变量**已在 `wt/storage-handle` 实现但未合入**（坑 30）；`3.0-vibe` 上跑对账测试会找不到 `runtime_manager/storage.py` → 用例 `skip` 并打印原因，不是失败。

**跨 Feature 依赖（签名 / 契约变更须回头改本文）**：
| 依赖方 | 具体 | 本文哪些任务会当场坏 |
|---|---|---|
| F054 app-proxy `INJECTED_HEADER_NAMES`（`app-proxy/headers.py:29-40`）、`_encode` / 缺失省略语义 | HTTP 头契约 | T005 / T006（对账测试先红） |
| F054 `lifecycle.build_env` + `storage.storage_env` 注入的 `BISHENG_APP_STORAGE_ENDPOINT` / `_TOKEN` / `_MAX_FILE_MB`（`wt/storage-handle`；backend 副本 `app_runtime/domain/constants.py:APP_STORAGE_ENV_NAMES:188-192`） | 环境变量契约 | T018 / T019 / T020 / T021 |
| F054 T084 附件 API `PUT|GET|DELETE /v1/apps/{app_id}/storage/objects/{key}`、`GET …/meta/{key}`、`GET …/objects`（design §4.2 ④，**对方已实现**，manager 信封 `{"detail":{code,message}}`） | HTTP 契约 | T018 / T019；T042 联调 |
| F053 T042–T044 `bisheng dev`（同构十头 + 每请求 `bsdev.` 凭据；**未注入 `BISHENG_APP_STORAGE_DIR`**） | CLI | T005 / T006（对账）· T016 / T020（句柄自造）· T042 本地期联调 |
| F053 T038 `skills/platform-wiring/`（SKILL.md 五章 + `example/` + `selfcheck.py`）与 `test_skill_packs.py` 的 `PACKS` 参数化 / `WIRING` 专项断言 | 技能包文本 + 测试 | T033 / T034 / T035 / T036（全为增量，改章序即红） |
| F053 `versions` 载荷 `sdk` 字段位（三键留位，`distribution.py:80`）+ `test_distribution_api.py:80-81`、`:228` 的 null 断言（`wt/cli-dev` 上漂到 `:82-83`、`:230`） | HTTP / 测试 | T026 / T027 |
| F053 `pack_cli_wheel.sh` + `cli-quality.yml` manifest 漂移守卫 | 构建脚本 | T023 |
| F053 `commands/skills.py:DEFAULT_PACKS`（`3.0-vibe` 单元素；`wt/cli-dev` 已两元素 + 已重打 CLI wheel） | CLI 常量 + 二进制 | T038（合并后先核对再决定改不改）· T029（`artifacts/` 二进制串行，坑 35） |
| F052 门面：OBO 受理、**平台签发的本地短时凭据受理**、`knowledge_base_ids` 可省略、「不可及」码 + `data.unreachable_ids`；F055 T057–T059 白名单 / `16273` / 审计 | 服务端 | T014 / T015（占位码）· T042 |
| runtime-manager `builder.py:366-369` buildargs、`config.py:159-160, 231-232`、`Dockerfile.j2:21-42` | 构建契约 | T030 / T031 |

**跨 Feature 副作用登记**（改到别人文件的任务）：
- **T023**（`scripts/pack_cli_wheel.sh`）——改 `rm -f *.whl` 为 `rm -f bisheng_cli-*.whl`、manifest heredoc 改 python 合并；`cli-quality.yml` 的 drift guard 逻辑不变。
- **T026 / T027**（`dev_toolkit/api/endpoints/distribution.py`、`dev_toolkit/domain/services/artifact_service.py`、`test/dev_toolkit/conftest.py`、`test/dev_toolkit/test_distribution_api.py`）——F053 拥有的文件做增量；**改 F053 的 `sdk` null 断言**为 T027 的同批改动。
- **T029 / T038**（`dev_toolkit/artifacts/manifest.json` + 两个 wheel）——二进制，**串行**；`wt/cli-dev` 已提交过一版 CLI wheel + manifest，合并后**先合并再重打**，不要手工编辑 manifest（坑 35）。
- **T030 / T031**（runtime-manager `config.py` / `builder.py` / `templates/python3.11/Dockerfile.j2` / `tests/test_build.py`）——F054 拥有；纯追加两个 ARG / 两个 buildarg / 两个 config 字段；`wt/storage-handle` 也改 `config.py`（追加 `storage_*` 字段），两处不相邻但同文件，合并顺序见 T000。
- **T033 另改 F053 的测试**（`test/dev_toolkit/test_skill_packs.py` 里 `test_auth_chapter_teaches_exactly_app_proxys_header_names` 的 `assert "不要依赖" in token_row` 一句）——`X-BiSheng-Access-Token` 从「本轮无消费方」变成「retrieve 在用」，守卫断言随契约同批更新，同一 PR。
- **T033 / T034 / T036**（`skills/platform-wiring/` 的 `SKILL.md` / 新目录 `example-sdk/` / `selfcheck.py`）——**包本体归 F053 T038 且已交付**，本 Feature 只做增量：换 auth 章的「SDK 用法」桩、插 retrieve / storage 两章、加 SDK 样例与自检步骤；**章序、目录第一条、`> ⚠️` 警示块、模型章「暂未提供」一律不动**（F053 的 `test_skill_packs.py` 断言，坑 31）。**T037** 改 `skills/deploy-hosting/SKILL.md:138` 指针一句与 `skills/README.md` 目录树。
- **T038**（`src/bisheng-cli/bisheng_cli/commands/skills.py` + `tests/test_command_skills.py`）——`wt/cli-dev` 已把 `DEFAULT_PACKS` 改成两元素并补过测试；合并后若已两元素则**只重打 CLI wheel 一次**（因 T023 改了打包脚本），常量与测试零改动。
- **T043**——只追加文档条目到 F052 / F053 / F055 tasks，不改他人代码；**F054 无回写**（附件契约以 `wt/storage-handle` 为准，design §6.2 回写登记第 1 条）。

---

## Tasks

### Wave 0 · 前置依赖核对

- [x] **T000**: 前置依赖分支合并核对（先于任何编码）〔0.5h〕
  **完成**: ✅ 2026-09-16 在 `3.0-vibe` `375a8594f` 上逐条核对，六项全部就位（两个前置分支都已合入，`wt/storage-handle` / `wt/cli-dev` 不再存在于 worktree 列表）：① `src/runtime-manager/runtime_manager/storage.py` 有 `STORAGE_ENV_NAMES`；② `app_runtime/domain/constants.py:APP_STORAGE_ENV_NAMES` 三名齐；③ `src/bisheng-cli/bisheng_cli/devproxy.py` 命中 `X-BiSheng-` 20 处（十头 + 归一化表）；④ `dev_toolkit/skills/platform-wiring/` 存在；⑤ `DEFAULT_PACKS = ("deploy-hosting", "platform-wiring")` 已两元素；⑥ `artifacts/manifest.json` 键为 `['cli', 'platform', '_note']`——**尚无 `sdk` 段**（归姊妹切片 T022 / T029）。另核对到本文未登记的一条：F055 的托管期检索服务端已合入（`filelib.py` 的 `HOSTED_APP_ACTOR_KIND` 分支 + `CapabilityBusService.retrieve`），其凭据形状与 design 初稿不同，见「实际偏差记录」第一条。
  **文件**: 本文（回填核对结果，不改代码）
  **逻辑**: 本 Feature 的实现分支必须从**已含两个前置分支**的基线切出，顺序 `wt/cli-dev` → `wt/storage-handle` → 本 Feature（坑 35：两分支都写 `src/backend/bisheng/dev_toolkit/artifacts/`，二进制不可 textual merge）。逐条核对并把结果写进本任务下方：① `test -f src/runtime-manager/runtime_manager/storage.py` 且 `grep -q "STORAGE_ENV_NAMES" ` 命中（F054 T084）② `grep -n "BISHENG_APP_STORAGE_ENDPOINT" src/backend/bisheng/app_runtime/domain/constants.py`（backend 契约副本）③ `test -f src/bisheng-cli/bisheng_cli/devproxy.py` 且 `grep -c "X-BiSheng-" ` ≥ 10（F053 T042）④ `test -d src/backend/bisheng/dev_toolkit/skills/platform-wiring`（F053 T038）⑤ `grep -n "DEFAULT_PACKS" src/bisheng-cli/bisheng_cli/commands/skills.py` 是否已两元素 ⑥ `python3 -c "import json;print(json.load(open('src/backend/bisheng/dev_toolkit/artifacts/manifest.json')).keys())"`。**任一项缺失就停下**——缺的那项对应的任务（T018/T019 对账、T033–T036 增量、T038）会按「文件不存在」写成新建，把对方的实现覆盖掉。
  **依赖**: 无
  **核对结果（基线 375a8594f）**: ① `runtime_manager/storage.py` 存在且含 `STORAGE_ENV_NAMES` ✅ ② `app_runtime/domain/constants.py:198` 有 `BISHENG_APP_STORAGE_ENDPOINT` ✅ ③ `bisheng_cli/devproxy.py` 存在、`X-BiSheng-` 出现 20 次 ✅ ④ `skills/platform-wiring/` 已在 ✅ ⑤ `DEFAULT_PACKS` 已是两元素 ✅ ⑥ manifest 键 = cli / platform / _note ✅。两个前置分支均已合入 `3.0-vibe`，无一项缺失。

### Wave 1 · SDK 包工程、测试基建、errors、上下文与 auth

- [x] **T001**: SDK 包工程骨架（本仓第二个可发布包工程）〔2h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`src/bisheng-sdk/{pyproject.toml,uv.lock,README.md,bisheng_sdk/__init__.py}`；`uv build --wheel` 产物含 15 个 `bisheng_sdk/*.py`（非空 wheel）。**偏差**：`__init__.py` 一次性 import 三模块（不留空模块占位），因为三个 Wave 在同一批落地。
  **文件**: `src/bisheng-sdk/pyproject.toml`（新）, `src/bisheng-sdk/bisheng_sdk/__init__.py`（新）, `src/bisheng-sdk/uv.lock`（新，`uv lock` 后**提交**）, `src/bisheng-sdk/README.md`（新，占位：安装 + 指南端点链接，正文随 T037）
  **逻辑**: 照抄 `src/bisheng-cli/pyproject.toml`（D1）：name=`bisheng-sdk`、version=`0.1.0`、`requires-python=">=3.11"`、`dependencies=["httpx>=0.27,<1.0"]`（**唯一依赖、带上界**）、`[project.optional-dependencies] dev=["pytest>=8.0","pytest-asyncio>=0.23","ruff>=0.9.0"]`、hatchling + **`[tool.hatch.build.targets.wheel] packages=["bisheng_sdk"]`**（坑 12）、`[tool.ruff]` 含 `RUF001/002/003` ignore、pytest marker `network`、`asyncio_mode="auto"`。`__init__.py`：`__version__ = "0.1.0"`（单一版本真相）、`__all__ = ("auth", "retrieve", "storage")`、`from . import auth, retrieve, storage`（延迟到 T006 / T015 / T021 落文件后再加 import，先用空模块占位）。**无 console script**。
  **依赖**: 无

- [x] **T002**: pytest 基建：零网络哨兵 + 环境隔离 + 上下文清理 + mock 平台响应工厂〔3h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/conftest.py` + `tests/helpers/platform_mock.py`。**偏差**：MockTransport 不经生产代码的参数注入，而是 `monkeypatch` `_http.client` / `_http.aclient` 两个工厂——生产代码里因此没有任何测试专用钩子，真实的 `request` / `parse_envelope` 路径仍被完整走到。
  **文件**: `src/bisheng-sdk/tests/conftest.py`（新）, `src/bisheng-sdk/tests/helpers/platform_mock.py`（新）, `src/bisheng-sdk/tests/helpers/__init__.py`（新）
  **逻辑**: fixtures——`no_network`（autouse；替换 `httpx.Client` / `AsyncClient` 默认 transport 为抛 `AssertionError` 的哨兵；清 `HTTP_PROXY` 等六个代理变量）· `clean_env`（autouse；`monkeypatch.delenv` 全部 `BISHENG_*`，防开发机残留）· `reset_context`（autouse；每用例前后把 `_context` 的 ContextVar 复位）· `platform_env`（设 `BISHENG_PLATFORM_API_BASE=http://platform.test`）· `hosted_headers(user_id="42", name="张三", dept=True, token=FAKE_OBO)` 造十头（**中文名按 `quote(safe="/")` 编码**，照 `entry_authz_service._encode`；`dept=False` 时**省略**三头而非空串）· `dev_headers()`（`Subject-Kind=service_account`、无部门）。假令牌常量**拼接**：`FAKE_OBO = "eyJ" + "a" * 40`、`FAKE_KEY = "bs-sak-" + "x" * 43`（坑 22）。
  `platform_mock.py`：基于 `httpx.MockTransport` 的响应工厂，**形状照 design §4.2 ③④⑤ 逐字构造、不许"顺手规整"**：`versions_ok(sdk_version, min_compatible)` / `versions_sdk_null()` / `versions_404()` · `retrieve_ok(chunks)` / `v2_error(http_status, code, message, data=None)`（`26001`→401、`26003`→403 且 `data.required` 为**单个字符串**、`26030`→503、`16273`→带 `data.capability` / `data.reason`、`16274`）· `storage_put_ok(meta)` / `storage_get_ok(bytes, content_type)` / `storage_stat_ok` / `storage_list(pages)`（多页 cursor）/ `storage_err(http_status, code)` · `v1_envelope(data)`（HTTP 200 + 信封）。工厂记录每次请求（方法 / 路径 / 头 / body）供断言。
  **依赖**: T001

- [x] **T003**: errors 与脱敏测试〔1.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_errors.py`（8 用例，含四种凭据形态的掩码参数化）。
  **文件**: `src/bisheng-sdk/tests/test_errors.py`（新）
  **测试**: `test_every_error_has_message_and_next_step`（design D6 表每个类实例化后 `str()` 含"下一步"）→ AC-19, AC-25 / `test_hierarchy_single_base`（全部继承 `BishengSdkError`；`PlatformIdentityMissingError` **不是** `VisitorCredentialMissingError` 子类，反之亦然——auth 与 retrieve 的缺失可区分）→ AC-07, AC-15, AC-19 / `test_redact_masks_sak_pat_bearer_and_jwt`（把 `FAKE_KEY` / `"bs-pat-"+"y"*43` / `"Bearer "+FAKE_OBO` / 裸 `FAKE_OBO` 塞进 message、next_step、details，`str()` 与 `repr()` 都只剩掩码）→ AC-04 / `test_platform_refused_keeps_code_message_details_verbatim`（未登记码不丢任何字段）→ AC-19 / `test_storage_errors_distinguishable`（Missing / Rejected / Unavailable / NotFound / TooLarge / InvalidPath 六类互不为子类且文案互异）→ AC-25
  **覆盖 AC**: AC-04, AC-07, AC-15, AC-19, AC-25
  **依赖**: T002

- [x] **T004**: `errors.py` 实现〔1.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/errors.py`。**偏差**：19 个子类而非 18——按 D5 改写新增 `AppCredentialMissingError`（应用运行期凭据未注入，与访问者凭据缺失可区分）。
  **文件**: `src/bisheng-sdk/bisheng_sdk/errors.py`（新）
  **逻辑**: `class BishengSdkError(Exception)`：`message` / `next_step` / `code: int | None` / `details: dict | None`，`__str__` = `redact(...)`；D6 表的 18 个子类，带各自结构化属性（`ScopeMissingError.required: str`、`TargetUnreachableError.ids: list`、`CapabilityRevokedError.capability / reason`、`SdkIncompatibleError.sdk_version / min_compatible / platform_version`、`AttachmentTooLargeError.limit_bytes`、`StorageHandleRejectedError.reason`）。`redact(text)`：正则替换 `bs-sak-\S+` / `bs-pat-\S+` → `bs-***`、`Bearer \S+` → `Bearer ***`、`eyJ[A-Za-z0-9_-]{10,}(\.[A-Za-z0-9_-]+){0,2}` → `***`。所有文案中文（RUF001-003 已 ignore）。
  **测试**: T003 全部通过。
  **覆盖 AC**: AC-04, AC-07, AC-15, AC-19, AC-25
  **依赖**: T003

- [x] **T005**: 头名常量、上下文与 auth 测试（含三处对账、并发隔离、三种接法）〔3h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_auth.py`（22 用例）+ `tests/test_context_isolation.py`（4 用例）+ `tests/test_contract_alignment.py`（9 用例，源文件缺失即 skip）。
  **文件**: `src/bisheng-sdk/tests/test_auth.py`（新）, `src/bisheng-sdk/tests/test_context_isolation.py`（新）, `src/bisheng-sdk/tests/test_contract_alignment.py`（新）
  **测试**（`test_auth.py`）: `test_current_user_from_hosted_headers`（十头 → `Identity`，`user_name == "张三"` 已解码、`dept_path` 保留 `/`、`subject_kind == "human"`）→ AC-06 / `test_missing_dept_headers_become_none_not_empty`（坑 2）→ AC-10 / `test_dev_headers_service_account_without_dept`（`subject_kind == "service_account"`、三部门 `None`、结构与线上同一 dataclass）→ AC-06, AC-10 / `test_dev_headers_personal_token_is_human_with_dept`（PAT `login` 时 `dev` 注入 `subject_kind == "human"` 且可能带部门——SDK 原样透传、不推导，design D4「与 spec 的口径差」/ 坑 33）→ AC-06 / `test_no_context_raises_identity_missing_never_none`（裸调用、空上下文、有其它头但无 `User-Id` 三种 → `PlatformIdentityMissingError`；断言**不返回** `None`）→ AC-07 / `test_identity_has_no_token_field_and_repr_has_no_token`（`Identity` 无 `access_token` 属性；`repr` 不含 `FAKE_OBO`）→ AC-04, AC-08 / `test_no_as_user_or_login_or_verify_api`（`dir(bisheng_sdk.auth)` 无 `as_user` / `login` / `verify` / `impersonate` / `sign`）→ AC-08 / `test_header_name_normalisation`（`X_BISHENG_USER_ID` / `x-bisheng-user-id` / WSGI `HTTP_X_BISHENG_USER_ID` 都能读到）→ AC-31 / `test_ids_are_strings_not_ints`（坑 20）→ AC-06 / `test_from_headers_is_pure_and_does_not_touch_context` → AC-09 / `test_asgi_middleware_sets_and_resets_per_request`（纯 ASGI 可调用；两次请求不同用户各得其身份；请求结束后上下文为空）→ AC-09 / `test_asgi_middleware_passes_headerless_request_through`（探活请求进应用、不 4xx；只有调 `current_user()` 才抛）→ AC-07 / `test_asgi_middleware_handles_websocket_scope`（握手 scope 的头进上下文）→ AC-09 / `test_wsgi_middleware_reads_http_x_bisheng_environ` → AC-31 / `test_bind_context_manager_for_streamlit_style`（`with auth.bind(headers):` 内可读，退出后抛）→ AC-09 / `test_middleware_is_not_starlette_basehttpmiddleware`（`issubclass` 为假，坑 14）→ AC-09
  **测试**（`test_context_isolation.py`）: `test_asyncio_gather_two_requests_isolated`（`asyncio.gather` 两个协程各 `bind` 不同用户、互不串扰）→ AC-09 / `test_thread_pool_has_no_identity`（`ThreadPoolExecutor` 里 `current_user()` 抛错——后台任务无访问者是刻意的）→ AC-07 / `test_created_task_inherits_copy_documented`（`asyncio.create_task` 能读到父身份——记录 asyncio 语义，坑 21）→ AC-09
  **测试**（`test_contract_alignment.py`，仓外 `skip`）: `test_header_names_match_app_proxy_verbatim`（读 `src/app-proxy/app_proxy/headers.py` 文本，提取 `INJECTED_HEADER_NAMES` 十个字面量，与 `bisheng_sdk._headers.INJECTED_HEADER_NAMES` 顺序与拼写逐字相等）→ AC-31 / `test_env_names_match_f054_contract_section_5`（读 `features/v3.0.0/054-app-domain-runtime/contracts-runtime-manager.md` §5 行，断言 `BISHENG_PLATFORM_API_BASE` 等名在 `_env.py` 中）→ AC-31
  **覆盖 AC**: AC-04, AC-06, AC-07, AC-08, AC-09, AC-10, AC-31
  **依赖**: T002, T004

- [x] **T006**: `_headers.py` / `_env.py` / `_context.py` / `auth.py` 实现〔4h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/{_headers,_env,_context,auth}.py`。
  **文件**: `src/bisheng-sdk/bisheng_sdk/_headers.py`（新）, `src/bisheng-sdk/bisheng_sdk/_env.py`（新）, `src/bisheng-sdk/bisheng_sdk/_context.py`（新）, `src/bisheng-sdk/bisheng_sdk/auth.py`（新）
  **逻辑**: `_headers.py`：`INJECTED_HEADER_NAMES`（十个，逐字照 `app-proxy/headers.py:29-40`）、`HEADER_*` 常量、`normalize_name()`（`strip().lower().replace("_","-")`，WSGI 形态先去 `HTTP_` 前缀）、`snapshot(headers: Iterable[tuple[str,str]]) -> dict[str,str]`（只收 `x-bisheng-` 前缀）、`parse_identity(snapshot) -> Identity`（design §4.2 ①：`User-Id` 缺 → `PlatformIdentityMissingError`；`unquote` 三个文本头与 `Dept-Path`；缺部门 → `None`；`Subject-Kind` 缺省 `"human"`）。`_env.py`：变量名常量 + `platform_api_base()`（空 → `PlatformUnreachableError` 点名 `BISHENG_PLATFORM_API_BASE` / `app_runtime.entry_base_url`，坑 19）。`_context.py`：`_current: ContextVar[dict[str,str] | None]`、`bind(snapshot)` 返回 token、`reset(token)`、`access_token() -> str | None`。`auth.py`：`@dataclass(frozen=True) Identity`、`current_user()`、`from_headers(mapping)`、`bind(headers)`（contextmanager）、`ASGIMiddleware`（**纯 ASGI 类**：`__init__(app)`、`async __call__(scope, receive, send)`；`scope["type"] in ("http","websocket")` 时 `bind(snapshot(scope["headers"] 解码 latin-1))`，`try: await app finally: reset`）、`WSGIMiddleware`（同形，从 `environ` 取 `HTTP_X_BISHENG_*`）。**无 `as_user`、无验签、无环境变量读取**（D3 / D4 / 决议-8）。
  **测试**: T005 全部通过。
  **覆盖 AC**: AC-04, AC-06, AC-07, AC-08, AC-09, AC-10, AC-31
  **依赖**: T004, T005

- [x] **T007**: 公开面守卫测试（AC-33 的自动化）〔1h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_public_surface.py` + `tests/test_import_smoke.py`。**偏差**：`BISHENG_APP_TOKEN` 的 grep 型断言按 D5 改写后的契约调整为「只允许出现在 `_env.py` 的代码里」，并改用 `ast` 区分代码与 docstring——否则解释性文档会把断言逼红。
  **文件**: `src/bisheng-sdk/tests/test_public_surface.py`（新）, `src/bisheng-sdk/tests/test_import_smoke.py`（新，照 `src/bisheng-cli/tests/test_import_smoke.py`：模块级 import 全部公开与私有模块、断言 `httpx` 有 `MockTransport` / `AsyncClient`）
  **测试**: `test_public_modules_are_exactly_auth_retrieve_storage_errors`（`pkgutil.iter_modules` 非下划线集合相等）→ AC-33 / `test_dunder_all_is_three_capability_modules` → AC-01, AC-33 / `test_chat_appdb_llm_db_client_do_not_import`（五个名字 `ModuleNotFoundError`）→ AC-30, AC-33 / `test_no_convenience_factory_symbols`（全包无 `openai` / `OpenAI` / `create_engine` / `connect(` / `sqlalchemy` 字符串——grep 源码）→ AC-30 / `test_no_process_level_credential_env_read`（源码 grep 无 `BISHENG_APP_TOKEN` / `BISHENG_API_KEY`，红线 1）→ AC-12 / `test_version_declared_once`（`bisheng_sdk.__version__` 是唯一字面量，`_compat` 引用同一对象）→ AC-03
  **覆盖 AC**: AC-01, AC-03, AC-12, AC-30, AC-33
  **依赖**: T006（T015 / T021 落文件后集合才完整；本任务先按占位模块通过，两处落地后**不得改集合**）

- [x] **T008**: SDK 质量门 CI〔1h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`.github/workflows/sdk-quality.yml` 三 leg；wheel leg 在 `scripts/pack_sdk_wheel.sh`（分发切片 T022）落地前自带 `uv build` + 空 wheel 校验 + 装包冒烟的等价实现。
  **文件**: `.github/workflows/sdk-quality.yml`（新）
  **逻辑**: 照 `cli-quality.yml` 三 leg：`locked`（`uv sync --frozen --extra dev` → `ruff check` + `ruff format --check` → `pytest -m "not network"`）· `highest`（`uv sync --resolution highest` 再跑测试，抓上界内的新版本破坏）· `wheel`（`bash scripts/pack_sdk_wheel.sh` + drift guard：`bisheng_sdk.__version__` == `manifest.json["sdk"]["version"]`、wheel 不被 `.gitignore` 匹配、manifest `git diff --quiet`）。paths：`src/bisheng-sdk/**`、`scripts/pack_sdk_wheel.sh`、本文件。`wheel` leg 依赖 T022 脚本存在，先以 `if: hashFiles('scripts/pack_sdk_wheel.sh') != ''` 守住。
  **依赖**: T001
  **证据**: 与 T028 合并交付于 `.github/workflows/sdk-quality.yml`（10607e923）；包未落地时三个 leg 各自打 notice 跳过而不是红。

- [x] **T009**: Wave 1 收口：`__init__.py` 挂 auth、ruff 全绿、`uv lock --check`〔0.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`ruff check` / `ruff format --check` 全绿（31 文件）；`uv lock` 已生成并提交。
  **文件**: `src/bisheng-sdk/bisheng_sdk/__init__.py`（增量）
  **逻辑**: `from . import auth`；`uv run ruff check . && uv run ruff format --check . && uv lock --check && uv run pytest`。
  **依赖**: T006, T007

### Wave 2 · HTTP 层、版本兼容与 retrieve

- [x] **T010**: HTTP 层测试（客户端池 / 超时 / trust_env / 信封解析顺序 / 码映射两级降级）〔2h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_http.py`（19 用例）。
  **文件**: `src/bisheng-sdk/tests/test_http.py`（新）
  **测试**: `test_envelope_status_code_read_before_http_status`（HTTP 200 + `status_code=10500` 信封 → 错误；HTTP 401 + 信封 `26001` → `VisitorCredentialRejectedError`，坑 7）→ AC-19 / `test_code_table_maps_registered_codes`（`26001`/`26002`/`26027`→Rejected · `26003`→`ScopeMissingError(required="knowledge:read")` · `26030`→PermissionEvaluation · `16273`→CapabilityRevoked(capability, reason) · `16274`→CapabilityNotDeclared）→ AC-14, AC-16, AC-17, AC-19 / `test_unregistered_code_falls_back_by_http_class_then_refused`（401 无码→Rejected；5xx 无码→Unreachable；403 未知码→`PlatformRefusedError` 且 `code` / `message` / `details` 原样）→ AC-16, AC-19 / `test_connect_error_and_timeout_are_unreachable_with_no_retry`（MockTransport 抛 `httpx.ConnectError`；断言只请求一次）→ AC-16, AC-19 / `test_trust_env_false_by_default_and_env_override`（设 `ALL_PROXY` 不影响；`BISHENG_SDK_TRUST_ENV=1` 时 `Client(trust_env=True)`）→ AC-19 / `test_timeouts_by_kind`（retrieve 读 30 s、storage 120 s、connect 5 s 常量）→ AC-19 / `test_client_pooled_per_base_url`（同 base 同实例，不同 base 不同实例）→ AC-18 / `test_bearer_header_never_logged_or_in_exception`（异常 `details` 里不含令牌）→ AC-04
  **覆盖 AC**: AC-04, AC-14, AC-16, AC-17, AC-18, AC-19
  **依赖**: T002, T004

- [x] **T011**: `_http.py` + `_codes.py` 实现〔3h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/{_http,_codes}.py`。**偏差**：`TARGET_UNREACHABLE_CODES` 不再留空——F052 已分配 `26321`（`data.unreachable_ids`），同批登记 `26320` / `26322`；`26323`（范围过大）按「未登记码原样呈现」走 `PlatformRefusedError`。
  **文件**: `src/bisheng-sdk/bisheng_sdk/_http.py`（新）, `src/bisheng-sdk/bisheng_sdk/_codes.py`（新）
  **逻辑**: `_http.py`：`client(base_url) -> httpx.Client` / `aclient(base_url) -> httpx.AsyncClient`（`dict` 池、`threading.Lock`；`trust_env = os.environ.get("BISHENG_SDK_TRUST_ENV") == "1"`；`Timeout(connect=5, read=…, write=…, pool=5)`）、`request(kind, method, path, *, bearer, json=None, content=None, stream=False)`、`parse_envelope(resp) -> Any`（顺序：JSON body 有 `status_code` 且 ≠ 200 → `_codes.map_error(code, message, http_status, data)`；非 2xx 无信封 → 按 HTTP 类兜底；2xx → `data`）、**零重试**（D11）。`_codes.py`：`CODE_TO_ERROR: dict[int, type]`（`26001/26002/26027` · `26003` · `26030` · `16273` · `16274`）、`TARGET_UNREACHABLE_CODES: frozenset[int] = frozenset()`（**F052 分配后填**，坑 25 同型；命中时构造 `TargetUnreachableError(ids=data.get("unreachable_ids", []))`）、`map_error()` 两级降级（D6 映射顺序）。
  **测试**: T010 全部通过。
  **覆盖 AC**: AC-04, AC-14, AC-16, AC-17, AC-18, AC-19
  **依赖**: T010

- [x] **T012**: 版本兼容测试〔1h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_compat.py`（11 用例）。
  **文件**: `src/bisheng-sdk/tests/test_compat.py`（新）
  **测试**: `test_compatible_when_min_le_local`（`min_compatible="0.1.0"`、本地 `0.1.0` / `0.2.0` 通过）→ AC-03 / `test_incompatible_raises_with_both_versions_and_remedy`（`min_compatible="0.3.0"` → `SdkIncompatibleError`，`str()` 含 `0.3.0`、本地版本、平台版本与「从当前平台重新获取 SDK」）→ AC-03 / `test_sdk_block_null_or_404_is_platform_too_old`（两种 → `PlatformTooOldError`，文案含「开放能力层未部署」可能）→ AC-03, AC-05 / `test_probe_once_per_process_per_base_and_failure_not_cached`（成功后第二次不再请求；`ConnectError` 后再调会重试）→ AC-03 / `test_auth_never_probes`（`current_user()` 全程零请求——`no_network` 哨兵已保证，显式断言）→ AC-03 / `test_version_tuple_algorithm_matches_cli`（`"0.10.0" > "0.9.9"`，不做字符串比较）→ AC-03
  **覆盖 AC**: AC-03, AC-05
  **依赖**: T002, T011

- [x] **T013**: `_compat.py` 实现〔1h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/_compat.py`。
  **文件**: `src/bisheng-sdk/bisheng_sdk/_compat.py`（新）
  **逻辑**: `ensure_compatible(base_url)` / `aensure_compatible(base_url)`：进程内 `dict[base_url, True]` 缓存成功；`GET /api/v1/dev-toolkit/versions` → 404 或 `data.sdk` 为 null / 无 `version` → `PlatformTooOldError`；`_version_tuple(min_compatible) > _version_tuple(__version__)` → `SdkIncompatibleError(sdk_version=__version__, min_compatible, platform_version=data.platform.version)`；连接失败 → `PlatformUnreachableError`（不缓存）。`_version_tuple` 照 `bisheng_cli/http.py:_version_tuple`（三段 int，非数字段按 0）。`__version__` 从包根 import（T007 单一真相断言）。
  **测试**: T012 全部通过。
  **覆盖 AC**: AC-03, AC-05
  **依赖**: T012

- [x] **T014**: retrieve 测试（同步 / 异步参数化）〔2.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_retrieve.py`（24 用例）。**偏差**：按 briefs-wave4 的跨 Feature 裁定与 F055 已合入实现，断言的是**两把凭据**而不是「只送访问者凭据」；`test_app_token_alone_is_never_enough` / `test_visitor_credential_alone_is_refused_locally` 两条替代了原先的 grep 型「代码里不得出现 BISHENG_APP_TOKEN」断言。`16273` / `26321` / `26322` 不再标 `[受阻]`——服务端已有写入方，只是 114 联调仍待 T042。
  **文件**: `src/bisheng-sdk/tests/test_retrieve.py`（新）
  **测试**: `test_search_posts_to_filelib_retrieve_with_context_token_as_bearer`（上下文 `bind(hosted_headers())` → 记录的请求：`POST http://platform.test/api/v2/filelib/retrieve`、`Authorization: Bearer <FAKE_OBO>`、body 键 == `RetrieveReq` 字段）→ AC-11, AC-12 / `test_body_is_field_for_field_and_none_ids_omitted`（`knowledge_base_ids=None` → body 无该键；`filters` 形状照 `RetrieveFilters`；无自造字段）→ AC-11, AC-18 / `test_result_mirrors_retrieve_resp`（`RetrieveResult.chunks[i]` 六字段 == 响应；`total` 原样；顺序不变）→ AC-11, AC-18 / `test_no_context_or_no_token_raises_missing_and_sends_nothing`（无上下文 / 有十头但无 `Access-Token` → `VisitorCredentialMissingError`，零请求）→ AC-15 / `test_process_env_app_token_is_never_used`（设 `BISHENG_APP_TOKEN=FAKE_KEY`、无上下文 → 仍 Missing、零请求；红线 1）→ AC-12, AC-15 / `test_no_as_user_parameter`（`inspect.signature(search)` 无 `as_user` / `user_id` / `on_behalf_of`）→ AC-08, AC-12 / `test_401_maps_rejected_with_next_step_mentioning_facade`（坑 5 文案）→ AC-15, AC-19 / `test_26003_maps_scope_missing_with_required_verbatim` → AC-14, AC-19 / `test_16273_maps_capability_revoked_with_name_and_reason`（`[受阻于 F055 T058]`，仅 mock）→ AC-17, AC-19 / `test_26030_maps_permission_evaluation_and_returns_no_chunks`（异常而非空列表）→ AC-16 / `test_target_unreachable_placeholder`（`monkeypatch` `_codes.TARGET_UNREACHABLE_CODES={99999}` → `TargetUnreachableError.ids == data.unreachable_ids`；`[受阻于 F052]`）→ AC-17, AC-19 / `test_incompat_surfaces_on_first_search`（`versions_sdk_null()` → `PlatformTooOldError`，未发检索请求）→ AC-03 / `test_two_users_same_query_get_their_own_results_no_cache`（两次 bind 不同用户、mock 返回不同结果、各得其果、两次请求）→ AC-18 / `test_async_twin_same_behaviour`（以上核心用例对 `asearch` 参数化）→ AC-11 / `test_422_is_platform_refused_with_details`（坑 6；`[受阻于 F052]` 放宽后改为成功用例）→ AC-19
  **覆盖 AC**: AC-03, AC-08, AC-11, AC-12, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19
  **依赖**: T002, T006, T011, T013

- [x] **T015**: `retrieve.py` 实现〔2.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/retrieve.py`。**偏差**：见 design D5 改写（两把凭据）。`tag_match_mode` 缺省值按服务端 Literal 取大写 `"ANY"`（design §4.2 ③ 初稿写的小写会 422）。
  **文件**: `src/bisheng-sdk/bisheng_sdk/retrieve.py`（新）, `src/bisheng-sdk/bisheng_sdk/__init__.py`（增量：`from . import retrieve`）
  **逻辑**: `@dataclass(frozen=True) Chunk(content, knowledge_id: int, document_id: int, document_name: str, chunk_index: int, document_update_time: str)`、`RetrieveResult(chunks: list[Chunk], total: int)`、`KnowledgeBaseFilter(knowledge_base_id: int, tags: list[str], tag_match_mode: str)`。`search(query: str, *, knowledge_base_ids: Sequence[int] | None = None, top_k: int = 10, max_content: int = 15000, filters: Sequence[KnowledgeBaseFilter] | None = None) -> RetrieveResult` 与 `asearch(...)`：① `token = _context.access_token()`，None → `VisitorCredentialMissingError`（`next_step` 含「经平台入口访问；线上另确认 `app_runtime.obo_secret` 已配置」）；② `base = _env.platform_api_base()`；③ `_compat.ensure_compatible(base)`；④ body 字段一一对应（`None` 键省略）；⑤ `_http.request("retrieve", "POST", "/api/v2/filelib/retrieve", bearer=token, json=body)` → `parse_envelope` → 构造结果。**不排序、不去重、不缓存、不读任何环境变量密钥**。`RETRIEVE_PATH` 为模块常量（D5「何时重新考虑」）。
  **测试**: T014 全部通过；T007 集合仍为四个公开模块。
  **覆盖 AC**: AC-03, AC-08, AC-11, AC-12, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19
  **依赖**: T014

### Wave 3 · storage

- [x] **T016**: 路径规则与本地目录后端测试〔2h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_paths.py`（26 用例）+ `tests/test_storage_local.py`（16 用例）。
  **文件**: `src/bisheng-sdk/tests/test_paths.py`（新）, `src/bisheng-sdk/tests/test_storage_local.py`（新）
  **测试**（paths，规则 = manager `runtime_manager/storage.py:validate_key:277-306` 的逐条镜像）: `test_traversal_matrix_rejected`（`../a` · `a/../b` · `/abs` · `a//b` · `a/./b` · `a\\b` · `""` · `"."` · 尾随 `/` · 含 `\x00` · 含 `\n` · UTF-8 1025 字节 → `InvalidAttachmentPathError`，**不规范化后放行**）→ AC-21 / `test_apps_prefix_rejected_even_for_own_app`（`apps/anything` → 拒；manager 保留命名空间，坑 29）→ AC-21 / `test_valid_unicode_paths_accepted`（`报告/2026 年度.pdf`）→ AC-20 / `test_prefix_rule_allows_empty_and_trailing_slash`（`validate_prefix` 镜像：`""` / `报告/` 通过、`apps/` 拒）→ AC-20
  **测试**（local）: `test_backend_selected_by_dir_env`（`BISHENG_APP_STORAGE_DIR=tmp` → 本地后端；同时设 `BISHENG_APP_STORAGE_ENDPOINT` → `StorageHandleMissingError`「句柄不唯一」；都不设 → Missing——`bisheng dev` 今天两个都不注入，坑 34）→ AC-23, AC-25 / `test_put_get_stat_list_delete_roundtrip`（bytes / file object / PathLike 三种 `data`；`stat.size` / `content_type`（`mimetypes` 猜）/ `modified_at` 为 `datetime | None`；`list("报告/")` 只返前缀内、按 path 升序；`delete` 后 `get` → `AttachmentNotFoundError`）→ AC-20, AC-23 / `test_put_is_atomic_tmp_then_replace`（写入中途异常不留半文件；目录内无 `.tmp` 残留）→ AC-23 / `test_real_disk_location_not_in_meta_or_errors`（`AttachmentMeta.path` 是应用内路径；`AttachmentNotFoundError` 文案不含 tmp 绝对路径）→ AC-21, AC-23 / `test_max_file_mb_env_enforced_locally_else_unlimited`（设 `BISHENG_APP_STORAGE_MAX_FILE_MB=1` → 1 MB + 1 字节 `AttachmentTooLargeError(limit_bytes=1048576)`；**单位是 MB、与线上同名同单位**；不设 → 通过，坑 23）→ AC-22 / `test_no_clear_or_prefix_delete_api`（`dir(storage)` 无 `clear` / `delete_prefix` / `delete_many` / `url` / `presign` / `share`）→ AC-22, AC-24 / `test_dir_env_missing_dir_created_lazily_under_project`（首次 put 建目录）→ AC-23
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
  **依赖**: T002, T004

- [x] **T017**: `_paths.py` + `_storage_local.py` 实现〔2.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/{_paths,_storage_local}.py`（+ `_attachment.py`：两个后端共用的 `AttachmentMeta`，由 `storage` 再导出，避免 `storage` ↔ 后端的循环 import）。
  **文件**: `src/bisheng-sdk/bisheng_sdk/_paths.py`（新）, `src/bisheng-sdk/bisheng_sdk/_storage_local.py`（新）
  **逻辑**: `_paths.validate(path) -> str` / `_paths.validate_prefix(prefix) -> str`（D9 规则 = manager `validate_key` / `validate_prefix` 的逐条镜像；返回原串，不规范化）。`_LocalDirBackend(root: Path)`：`put`（`tempfile.NamedTemporaryFile(dir=root, delete=False)` 流式写 → `os.replace`；写前若已知长度且超 `BISHENG_APP_STORAGE_MAX_FILE_MB × 1024²` 直接拒；未知长度边写边计数超限即删 tmp 并抛）· `get` / `open` / `stat`（`os.stat` + `mimetypes.guess_type`）· `list(prefix, limit)`（`os.walk` 相对化、posix 分隔、排序）· `delete`。`root / path` 解析后 `resolve()` 必须仍在 `root` 内（防御性二次守卫）。所有异常文案只含应用内路径。
  **测试**: T016 全部通过。
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
  **依赖**: T016

- [x] **T018**: 远端 HTTP 后端测试 + 附件 API 对账（design §4.2 ④ 契约的可执行快照）〔2.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`tests/test_storage_remote.py`（20 用例）+ `tests/test_contract_alignment.py` 的路由 / 路径规则 / 环境变量名三条对账。
  **文件**: `src/bisheng-sdk/tests/test_storage_remote.py`（新）, `src/bisheng-sdk/tests/test_contract_alignment.py`（增量，T005 已建）
  **测试**: `test_backend_selected_by_endpoint_and_token_env`（`BISHENG_APP_STORAGE_ENDPOINT` + `_TOKEN` 齐 → 远端；只有 ENDPOINT 无 TOKEN → `StorageHandleMissingError`「句柄不完整」）→ AC-20, AC-25 / `test_put_streams_body_with_bearer_and_content_length`（`PUT {E}/objects/%E6%8A%A5%E5%91%8A/a.pdf`（**逐段 `quote(seg, safe="")`**）、`Authorization: Bearer <token>`、body = **原始字节流非 multipart**、`Content-Length` 存在、传 file object 时不整读进内存）→ AC-20, AC-21 / `test_get_stat_list_delete_wire_shapes`（`GET {E}/objects/{key}` 下载 · **`GET {E}/meta/{key}` 元信息（不是 `/stat/`）** · `GET {E}/objects?prefix=&cursor=&limit=` 列举、跟 `next_cursor` 翻两页合并 · `DELETE {E}/objects/{key}` → **`200 {}` 当成功、不是 204**，坑 29）→ AC-20 / `test_413_payload_too_large_maps_with_max_file_mb`（manager 信封 `{"detail":{"code":"payload_too_large","message":…,"max_file_mb":20}}` → `AttachmentTooLargeError(limit_bytes=20*1024**2)`）→ AC-22 / `test_401_unauthorized_maps_rejected_with_manager_message`（**只有 401、没有 403、没有「已下线」专用码**：令牌不属本应用 / 应用已 destroy / 无 Bearer 全是 `unauthorized`，`reason` = `detail.message`，坑 28）→ AC-25 / `test_404_not_found_maps_attachment_not_found`（含 `delete` 缺失路径也是 404、不是静默成功）→ AC-25 / `test_503_storage_unavailable_and_connect_error_map_unavailable_not_empty_list`（`list` 在 503 时抛而不是返 `[]`；`next_step` 点名 `runtime/status` preflight `attachment_storage`，坑 27）→ AC-25 / `test_400_invalid_object_key_maps_invalid_path`（服务端二次校验的呈现）→ AC-21 / `test_meta_never_carries_bucket_key_endpoint_or_token`（`AttachmentMeta` 字段集合恰 `path/size/content_type/modified_at`（+ `etag` 保留）；`key`→`path` 已剥应用前缀；异常 `details` 不含 token）→ AC-21 / `test_app_id_never_sent_by_client`（请求体 / 查询串 / 头里无 `app_id`——它只在注入的 ENDPOINT 里）→ AC-21 / `test_async_twins_same_wire_shape`（参数化）→ AC-20
  **测试**（对账，仓外或文件缺失时 `skip` 并打印原因，坑 30）: `test_storage_routes_match_manager_verbatim`（读 `src/runtime-manager/runtime_manager/api/storage.py` 文本，断言四条 `@router` 路径与 `prefix="/v1/apps/{app_id}/storage"` 与 `_storage_remote.py` 的常量一致）→ AC-20 / `test_path_rules_match_manager_validate_key`（读 `runtime_manager/storage.py` 的 `validate_key`，逐条规则与 `_paths.py` 对齐）→ AC-21 / `test_env_names_match_manager_storage_env_names`（`STORAGE_ENV_NAMES` == `_env.py` 三名）→ AC-31
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-25, AC-31
  **依赖**: T002, T005, T011, T017

- [x] **T019**: `_storage_remote.py` 实现〔2.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67；审查修复见下）`bisheng_sdk/_storage_remote.py`。**偏差**：`open()` 在远端后端是「整读后包成 BytesIO」，不是流式——httpx 的流式响应要求把请求上下文交给调用方管理，而 `storage.open()` 的契约是返回一个普通 file-like；大文件的真流式留到 F054 加 presign 时再议。
  **审查修复（2026-09-16）**: 附件端点的**传输层失败原先漏翻**——`_http.request` 抛的 `PlatformUnreachableError` 直接逃到应用，于是「连不上 runtime-manager」（坑 27：manager 只听 `127.0.0.1` / 未配 `RTM_APP_FACING_BASE_URL`，这是托管期 storage 最常见的故障）被呈现成「连不上平台」，`next_step` 把人支去查 `BISHENG_PLATFORM_API_BASE`，而真正要看的是 `runtime/status` 的 `attachment_storage` 自检项。design D6 的 `StorageUnavailableError` 行本就写明「连接失败（坑 27）」属于它，代码没跟上；AC-25 的「彼此可区分」也因此破了。修法：`RemoteBackend._send` / `AsyncRemoteBackend._asend` 统一捕获并翻成 `StorageUnavailableError`（原 message 保留）。原测试 `pytest.raises((StorageUnavailableError, PlatformUnreachableError))` 两边都收，正是它把这个缺陷放过去的——已收紧成只认 `StorageUnavailableError` 并断言 `next_step` 点名 `attachment_storage`（`test_connect_failure_is_a_storage_outage_not_a_platform_outage` + 异步孪生一条）。
  **文件**: `src/bisheng-sdk/bisheng_sdk/_storage_remote.py`（新）
  **逻辑**: `_RemoteBackend(endpoint, token)`（`endpoint` 已含 `/v1/apps/{app_id}/storage`，SDK 不拼 `app_id`）：`_http.request("storage", …, bearer=token)`；`put` 用 `content=` 传 file object 或 bytes（httpx 流式，原始字节非 multipart）、`Content-Type` 显式或 `mimetypes` 猜、缺长度时先 `seek/tell` 取长度；`get` 整读、`open` 返回 `resp.iter_bytes()` 包装的 file-like；`stat` 打 `/meta/{key}`；`list`（循环 `next_cursor`，`limit` 到达即停）；`delete` 把 `200 {}` 当成功。错误映射按 **manager 信封 `{"detail":{"code","message",…extra}}` 的机器码**（坑 26）：`invalid_object_key` → `InvalidAttachmentPathError`、`unauthorized`（恒 401）→ `StorageHandleRejectedError(reason=detail["message"])`、`not_found` → `AttachmentNotFoundError`、`payload_too_large` → `AttachmentTooLargeError(limit_bytes=detail["max_file_mb"]*1024**2)`、`storage_unavailable` / 连接失败 / 无码 5xx → `StorageUnavailableError`、其它 → `PlatformRefusedError(code=None, details=detail)`。**路径段 `quote(seg, safe="")` 后拼接**；**永不走 manager 的 HMAC 路径**（那是 backend / F052 用的）。
  **测试**: T018 全部通过。
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-25
  **依赖**: T018

- [x] **T020**: storage 门面测试（后端选择 + 两后端跑同一套行为用例 + 异步孪生）〔1.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67；审查修复见下）`tests/test_storage_facade.py`（local / remote 参数化跑同一段脚本）。
  **审查修复（2026-09-16）**: `test_six_functions_and_six_async_twins_exist` 的名字说六个异步孪生，断言里只列了五个——**`aopen` 从来没实现过**，而这条测试的写法恰好让缺失看不出来。已补 `storage.aopen` / `AsyncRemoteBackend.aopen`（远端 = `aget` 后包 `BytesIO`，与同步 `open` 同形；本地 = `asyncio.to_thread`），断言改成「六个同步函数逐个推导出 `a<name>` 并要求是协程函数」，缺任何一个都会点名。D10「六函数各有异步孪生」至此才真的成立——少了它，用 FastAPI 的应用读大附件只能在事件循环里阻塞。
  **文件**: `src/bisheng-sdk/tests/test_storage_facade.py`（新）
  **测试**: `test_same_api_over_both_backends`（参数化 `local` / `remote(mock)`：`put → stat → list → get → delete → get 抛 NotFound` 同一脚本两边结果形状相等）→ AC-20, AC-23 / `test_six_functions_and_six_async_twins_exist`（`put/get/open/stat/list/delete` 与 `aput/…`）→ AC-20 / `test_handle_resolution_is_per_call_not_cached`（改环境变量后下一次调用换后端——`dev` 重启场景）→ AC-25 / `test_path_validated_before_any_io`（非法路径零请求、零磁盘写）→ AC-21 / `test_no_url_returning_function`（`dir(storage)` 无以 `url` / `link` / `presign` 结尾的名字）→ AC-22
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-25
  **依赖**: T017, T019

- [x] **T021**: `storage.py` 实现 + `__init__.py` 挂载〔1.5h〕
  **完成**: ✅ 2026-09-16（ff32fac67）`bisheng_sdk/storage.py`；`tests/test_public_surface.py` 的公开面集合最终 == `{auth, retrieve, storage, errors}`。
  **文件**: `src/bisheng-sdk/bisheng_sdk/storage.py`（新）, `src/bisheng-sdk/bisheng_sdk/__init__.py`（增量：`from . import storage`）
  **逻辑**: `@dataclass(frozen=True) AttachmentMeta(path, size: int, content_type: str | None, modified_at: datetime | None, etag: str = "")`（`modified_at` 由 manager 的 `last_modified` ISO 串解析，MinIO 无值时 `""` → `None`）；`_backend()`（**每次调用重算、不缓存**，`dev` 重启即换）：有 `BISHENG_APP_STORAGE_ENDPOINT` → 远端（缺 `_TOKEN` → `StorageHandleMissingError`「句柄不完整」）· 无 ENDPOINT 有 `BISHENG_APP_STORAGE_DIR` → 本地 · **两者都有 → `StorageHandleMissingError`「句柄不唯一」** · 都没有 → `StorageHandleMissingError`（D8）；六函数 + 六 `a*` 孪生（本地后端的异步版用 `asyncio.to_thread`）。每个函数首行 `_paths.validate`。
  **测试**: T020 全部通过；T007 公开面集合最终 == `{auth, retrieve, storage, errors}`。
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
  **依赖**: T020

### Wave 4 · 平台分发（打包、manifest、端点、CI、提交 wheel）

- [x] **T022**: `scripts/pack_sdk_wheel.sh` + `sdk_compat.py`〔2h〕
  **文件**: `scripts/pack_sdk_wheel.sh`（新）, `src/backend/bisheng/dev_toolkit/sdk_compat.py`（新）
  **逻辑**: `sdk_compat.py`：`SDK_MIN_COMPATIBLE = "0.1.0"`（平台声明的最低兼容 SDK 版本，D16；docstring 说明升它 = 宣告老 SDK 应用下次调用报错）。脚本照 `pack_cli_wheel.sh` 五步：① `uv build --wheel`（`src/bisheng-sdk/`）② 校验 wheel 含 `bisheng_sdk/auth.py`（`WHEEL_LISTING="$(unzip -l …)"` + `case`，**不用 `| grep -q`**，坑 12）且文件名含版本 ③ 清 venv 装 wheel 冒烟：`python -c "import bisheng_sdk, bisheng_sdk.auth, bisheng_sdk.retrieve, bisheng_sdk.storage, bisheng_sdk.errors; assert bisheng_sdk.__version__=='${VERSION}'"` ④ `rm -f "${ARTIFACTS_DIR}"/bisheng_sdk-*.whl`（**只删自己前缀**）→ 拷贝 → sha256 → **python 合并写 manifest**：读旧 JSON（缺则 `{}`），设 `["sdk"] = {version, min_compatible: SDK_MIN_COMPATIBLE(sed 自 sdk_compat.py), filename, sha256}`，`["platform"]` 与 `["cli"]` / `_note` 保留 ⑤ `git check-ignore` 自检。末尾提示「提交 wheel + manifest，否则平台照旧答 sdk=null」。
  **依赖**: T001
  **证据**: `scripts/pack_sdk_wheel.sh` + `bisheng/dev_toolkit/sdk_compat.py`（1358ad8f3）。脚本已实跑验证（用姊妹切片 `wt/f057-sdk-core` 的包做 dry run）：构建 → `unzip -l` 校验三模块 → 空 venv 装包冒烟 → 合并写 manifest，`cli` / `platform` 两段字节不变。

- [x] **T023**: `pack_cli_wheel.sh` 改为合并写 manifest、只删自己前缀 wheel（跨 Feature 改动）〔1h〕
  **文件**: `scripts/pack_cli_wheel.sh`（增量）
  **逻辑**: `:88` `rm -f "${ARTIFACTS_DIR}"/*.whl` → `rm -f "${ARTIFACTS_DIR}"/bisheng_cli-*.whl`；`:96-110` heredoc → `python3 - <<'PY'` 读旧 manifest、只替换 `cli` 与 `platform` 段、保留 `sdk` 段、写回（`indent=2` + 尾换行，与现有格式字节一致以免 `cli-quality.yml` drift guard 误报）。头注释追加两行说明。**跑一次脚本确认 `git diff` 只有预期变化**。
  **依赖**: T022
  **证据**: `scripts/pack_cli_wheel.sh` 改合并写 + 只删 `bisheng_cli-*.whl`（1358ad8f3）；重跑脚本后差异只有 `_note` 一行（78f231bce），wheel sha256 未变。

- [x] **T024**: `artifact_service` 的 SDK 段测试〔1h〕
  **文件**: `src/backend/test/dev_toolkit/conftest.py`（增量：`staged_artifacts` 追加 `sdk` 段 + 假 wheel `bisheng_sdk-0.1.0-py3-none-any.whl`；新 fixture `staged_cli_only`——manifest 无 `sdk` 段）, `src/backend/test/dev_toolkit/test_artifact_service_sdk.py`（新）
  **测试**: `test_snapshot_reads_sdk_artifact`（`snapshot.sdk.version/min_compatible/filename/sha256/path`）→ AC-01 / `test_sdk_none_when_section_absent_cli_still_present`（老 manifest 不影响 CLI）→ AC-01 / `test_sdk_none_when_wheel_file_missing_logs_warning`（照 CLI 的部分 rsync 分支）→ AC-01 / `test_min_compatible_defaults_to_version` → AC-03 / `test_read_sdk_guide_returns_platform_wiring_skill_md_or_none` → AC-26
  **覆盖 AC**: AC-01, AC-03, AC-26
  **依赖**: 无（后端侧独立）
  **证据**: `test/dev_toolkit/test_artifact_service_sdk.py`（6 用例）+ conftest 的 `staged_artifacts` 扩 sdk 段与新 fixture `staged_cli_only`（1358ad8f3）。

- [x] **T025**: `artifact_service.py` 增量实现〔1h〕
  **文件**: `src/backend/bisheng/dev_toolkit/domain/services/artifact_service.py`（增量）
  **逻辑**: `@dataclass(frozen=True) SdkArtifact(version, min_compatible, filename, sha256, path)`；`DistributionSnapshot` 加 `sdk: SdkArtifact | None`；`read_snapshot` 用同一套「manifest 有段 + 文件在盘」判定，缺一则 `None`（不影响 `cli`）；`read_sdk_guide() -> str | None` = `SKILLS_DIR / "platform-wiring" / "SKILL.md"`（缺 → None，照 `read_install_guide`）。不读 DB（C3 无关）。
  **测试**: T024 全部通过；既有 `test_distribution_api.py` 除 `sdk` null 断言外不变。
  **覆盖 AC**: AC-01, AC-03, AC-26
  **依赖**: T024
  **证据**: `artifact_service.py` 加 `SdkArtifact` / `DistributionSnapshot.sdk` / `read_sdk_guide()`，两个 wheel 共用 `_staged_wheel()` 判定（1358ad8f3）。

- [x] **T026**: 分发端点集成测试（四端点 + `versions` 的 `sdk` 段 + 改 F053 的 null 断言）〔2h〕
  **文件**: `src/backend/test/dev_toolkit/test_distribution_api.py`（增量：`:80-81` 与 `:228` 改为「有 staged sdk 时六键齐全；无时整段 null + `notice`」）, `src/backend/test/dev_toolkit/test_sdk_distribution_api.py`（新）
  **测试**: `test_versions_sdk_section_when_staged`（`version/min_compatible/filename/sha256/download_path/index_path` 六键，值照 manifest）→ AC-01, AC-03 / `test_versions_sdk_null_and_notice_when_not_staged` → AC-01 / `test_sdk_download_streams_wheel_with_content_disposition_anonymously`（无 Cookie 无 Bearer）→ AC-01 / `test_sdk_download_with_filename_segment_only_accepts_manifest_filename`（正确名 200；其它 404）→ AC-02 / `test_sdk_download_missing_is_real_404_with_envelope`（不是 200 信封、不是 500）→ AC-01 / `test_simple_index_root_lists_bisheng_sdk`（`text/html`；含 `href="bisheng-sdk/"`）→ AC-02 / `test_simple_index_project_page_links_download_with_sha256_fragment`（`href="../../sdk/download/bisheng_sdk-0.1.0-py3-none-any.whl#sha256=<manifest sha>"`；PEP 503 规范化名）→ AC-02 / `test_simple_index_404_when_not_staged` → AC-02 / `test_sdk_guide_md_served_as_markdown_anonymously_and_404_when_missing` → AC-26 / `test_all_sdk_routes_absent_when_open_platform_disabled`（四个路径 404，同 `test_routes_absent_when_open_platform_disabled`）→ AC-05 / `test_multi_tenant_no_jwt_does_not_raise_on_sdk_routes`（`/api/v1/dev-toolkit` 前缀已在 `TENANT_CHECK_EXEMPT_PATHS`，`http_middleware.py:61`）→ AC-01
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-26
  **依赖**: T025
  **证据**: `test/dev_toolkit/test_sdk_distribution_api.py`（12 用例）；同批把 F053 的 `sdk` 三键 null 断言改成「有 staged 时六键齐全 / 无时整段 null」（1358ad8f3）。

- [x] **T027**: `distribution.py` 增量实现（四端点 + `versions` 填值）〔2h〕
  **文件**: `src/backend/bisheng/dev_toolkit/api/endpoints/distribution.py`（增量）
  **逻辑**: 常量 `SDK_DOWNLOAD_PATH = "/api/v1/dev-toolkit/sdk/download"`、`SDK_INDEX_PATH = "/api/v1/dev-toolkit/simple/"`、`SDK_MISSING_MESSAGE = "SDK 安装件未随本次部署发布，请联系平台管理员"`、`SDK_GUIDE_MISSING_MESSAGE`；`get_dev_toolkit_versions` 的 `sdk` 由 `snapshot.sdk` 填（六键）或整段 `None`；`notice` 逻辑：cli 或 sdk 任一缺失即给文案（拼接）。`@router.get("/sdk/download")` 与 `@router.get("/sdk/download/{filename}")` 共用 `_serve_sdk_wheel(filename: str | None)`（D15）；`@router.get("/simple/")` 与 `@router.get("/simple/bisheng-sdk/")` 返回 `HTMLResponse`（最小 PEP 503：`<!DOCTYPE html><html><body><a href=…>…</a></body></html>`）；`@router.get("/sdk-guide.md")` 照 `get_install_guide`。**无 `Depends`**（匿名，D10 同源）。
  **测试**: T026 全部通过；`test/dev_toolkit` 全量通过；`ruff` + `arch-guard.sh` 零输出。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-26
  **依赖**: T026
  **证据**: `distribution.py` 四端点 + `versions` 的 `sdk` 段 + `_versions_notice()`（1358ad8f3）。`test/dev_toolkit` 全量 114 passed；ruff 与 arch-guard 零输出。

- [x] **T028**: `sdk-quality.yml` wheel leg 接入真实脚本 + drift guard〔0.5h〕
  **文件**: `.github/workflows/sdk-quality.yml`（增量）
  **逻辑**: 去掉 T008 的 `hashFiles` 守卫；drift guard 读 `manifest.json["sdk"]["version"]`；「Artifacts are committed」步骤 `git diff --quiet -- manifest.json`。
  **依赖**: T008, T022
  **证据**: `.github/workflows/sdk-quality.yml`（10607e923）三 leg 一次写全（含 T008 的 locked / highest），wheel leg 直接调真脚本 + `sdk.version` drift guard + manifest 未提交守卫。**偏差**：T008 原归姊妹切片，但 CI 文件与打包脚本同属分发面，合在本切片一次写完。

- [ ] **T029**: 打包并提交 SDK wheel（Wave 4 末尾，串行）〔0.5h〕
  **文件**: `src/backend/bisheng/dev_toolkit/artifacts/bisheng_sdk-0.1.0-py3-none-any.whl`（新，二进制）, `src/backend/bisheng/dev_toolkit/artifacts/manifest.json`（增量 `sdk` 段）
  **逻辑**: `bash scripts/pack_sdk_wheel.sh` → 确认 `cli` 段字节不变 → 提交。⚠️ 与 T038（重打 CLI wheel）**不得并行**。
  **依赖**: T021, T022, T023, T027
  **未做（本轮）**: 需要 `src/bisheng-sdk/` 与本提交在同一棵树上才能构建并提交 wheel，而包本体在姊妹切片 `wt/f057-sdk-core`（`ff32fac67`）。合并两个切片后执行一次 `bash scripts/pack_sdk_wheel.sh` 并提交 wheel + manifest 即可（脚本已验证可跑通，见 T022）。在那之前 `/versions` 的 `sdk` 段是 null、`/sdk/download` 与 `/simple/bisheng-sdk/` 答 404 —— 这是已被测试固定的降级形态，不是缺陷。

### Wave 5 · 托管构建期取包

- [x] **T030**: runtime-manager extra index 测试〔1h〕
  **文件**: `src/runtime-manager/tests/test_build.py`（增量）
  **测试**: `test_build_args_inject_extra_index_url_and_trusted_host`（照 `test_build_args_inject_index_url:126-133`：`buildargs["PIP_EXTRA_INDEX_URL"] == config.build_extra_index_url`、`PIP_EXTRA_TRUSTED_HOST`）→ AC-02 / `test_dockerfile_renders_extra_index_args_and_pip_flags`（渲染文本含 `ARG PIP_EXTRA_INDEX_URL=""`、`${PIP_EXTRA_INDEX_URL:+--extra-index-url "$PIP_EXTRA_INDEX_URL"}`、`${PIP_EXTRA_TRUSTED_HOST:+--trusted-host "$PIP_EXTRA_TRUSTED_HOST"}`；`--index-url` 行保留）→ AC-02 / `test_config_reads_rtm_build_extra_env`（`RTM_BUILD_EXTRA_INDEX_URL` / `RTM_BUILD_EXTRA_TRUSTED_HOST`，缺省空串）→ AC-02 / `test_template_render_still_deterministic`（既有用例不变）→ AC-02
  **覆盖 AC**: AC-02
  **依赖**: 无
  **证据**: `src/runtime-manager/tests/test_build.py` 追加 3 用例（buildargs / Dockerfile 渲染 / `RTM_BUILD_EXTRA_*` 读取），`tests/test_build.py` 19 passed 1 skipped（1358ad8f3）。

- [x] **T031**: runtime-manager `config.py` / `builder.py` / `Dockerfile.j2` 增量〔1.5h〕
  **文件**: `src/runtime-manager/runtime_manager/config.py`（增量：`build_extra_index_url` / `build_extra_trusted_host` 字段 + `RTM_BUILD_EXTRA_*` 读取，紧邻 `:159-160` / `:231-232`）, `src/runtime-manager/runtime_manager/builder.py`（增量：`:366-369` buildargs 加两键）, `src/runtime-manager/runtime_manager/templates/python3.11/Dockerfile.j2`（增量：`:21-22` 后加两个 `ARG`；`:39-42` pip 行加两个 shell 参数展开；头注释第 8 行补「SDK 自平台简单索引」）, `docs/architecture/14-app-factory-deployment.md`（增量：runtime-manager 环境变量表在 `RTM_BUILD_INDEX_URL` 行（`:151`）之后追加 `RTM_BUILD_EXTRA_INDEX_URL` / `RTM_BUILD_EXTRA_TRUSTED_HOST` 两行，备注「值必须是**构建容器可达**的宿主机地址，不能写 `localhost`」，坑 15。`features/v3.0.0/054-app-domain-runtime/deploy/` 只有两个 systemd unit 文件、无 env 模板，不改）
  **逻辑**: 只做追加；`--extra-index-url` 与 `--index-url` 并存（第三方依赖走主索引，`bisheng-sdk` 由 pip 在两个索引里都找、按 hash 取平台那份）。README / 部署文档注明值必须是**构建容器可达**的宿主机地址，非 `localhost`（坑 15）。
  **测试**: T030 全部通过；`cd src/runtime-manager && uv run ruff check . && uv run pytest -q`。
  **覆盖 AC**: AC-02
  **依赖**: T030
  **证据**: `config.py` 两字段 + `builder.py` 两 buildarg + `Dockerfile.j2` 两 ARG 与两处 pip 参数展开 + `docs/architecture/14-app-factory-deployment.md` 环境变量表两行与一条排障行（1358ad8f3）。

- [ ] **T032**: 114 构建期真机验证〔1.5h，`needs_114`〕
  **文件**: 本文（回填结果）
  **逻辑**: `/etc/bisheng/runtime-manager.env` 加 `RTM_BUILD_EXTRA_INDEX_URL=http://192.168.106.114:7860/api/v1/dev-toolkit/simple/` 与 `RTM_BUILD_EXTRA_TRUSTED_HOST=192.168.106.114` → `systemctl restart bisheng-runtime-manager` → 用 T034 样例（`requirements.txt` 含 `bisheng-sdk`）`bisheng deploy` → `journalctl -u bisheng-runtime-manager` 看 pip 从 `/simple/bisheng-sdk/` 取到 wheel、hash 校验通过。⚠️ 需 T029 已部署（`deploy.sh` 重启 8 unit）。记录 `docker build` 的出站路径是否被 F054 出站白名单放行（F054 AC-16 尚未实现，本轮容器出站不受限——记录事实）。
  **覆盖 AC**: AC-02
  **依赖**: T029, T031
  **未做（需 114）**: 本切片无 114 访问，且它依赖 T029 已部署。

### Wave 6 · 技能包、指南、自检、评测样本、CLI 包清单

- [x] **T033**: 「平台能力接线」`SKILL.md` **增量**：填 SDK 桩 + 插 retrieve / storage 两章〔3h〕
  **文件**: `src/backend/bisheng/dev_toolkit/skills/platform-wiring/SKILL.md`（**增量**，F053 T038 已交付 226 行五章版本；先 `git log -1 -- <该文件>` 确认在手的是对方那版，T000 已核对）, `src/backend/test/dev_toolkit/test_skill_packs.py`（**增量，改 F053 的一条断言**——见下 ④）
  **逻辑**: **不动的部分**（F053 的 `test_skill_packs.py` 直接断言，坑 31）：frontmatter（`name: platform-wiring`、中性 description、`metadata.display-name`）、第 1 章「访问者身份」仍是**目录第一条与正文第一章**且章首 `> ⚠️` 警示块含「静默」「登录页」原样、模型章仍含「暂未提供」「不要猜」且**全章零 URL**、应用数据库章仍含 `BISHENG_APP_DB_PATH` / `BISHENG_APP_DB_URL` / `--confirm-schema-change` / `只**记录**`、`bisheng dev` 章与自检清单章内容不动（编号可顺延）。⚠️ 另有一条**全文级**约束：`test_auth_chapter_teaches_exactly_app_proxys_header_names` 断言「SKILL.md 里所有反引号包住的 `X-BiSheng-*` 名字**集合恰等于** app-proxy 的十个」——新写的 retrieve / storage 两章**不得出现第十一个 `X-BiSheng-*` 名**（坑 36）。**本任务改四处**：
  ① 第 1 章末尾的「### SDK 用法（随后续版本补齐）」桩 → 换成实体内容：`user = bisheng_sdk.auth.current_user()` 一行 vs 三种错误做法（自建登录页 / 自读头自己拼 / 自解析凭据）对照；三种接法（ASGI 纯中间件 / WSGI / `auth.bind()` 供 Streamlit）；无注入即抛 `PlatformIdentityMissingError`（健康端点不调 auth、后台任务不假设有访问者）；`user_id` 是 `str` 且**不是**平台 `user` 表的行；`subject_kind` 在 `dev` 期**取决于 login 用的密钥**（服务账号密钥 → `service_account`、个人访问令牌 → `human`，坑 33）、线上恒 `human`；「本地看不到 per-user 差异，验证路径 = 发布后用真实账号访问」。**保留**原有「读头也是合法写法」的表格（spec AC-32 明认直读注入头合法）。
  ② 新增「## 2. 知识库检索（retrieve）」：一行用法；per-user 语义（以当前访问者检索、结果 = 应用声明白名单 ∩ 访问用户可见范围、fail-closed）；本地 / 线上四处差异（本地无白名单、范围 = 服务账号被显式授予范围、只会「本地看得少」不会「本地能跑线上越权」、凭据来源不同但对应用不可见）；错误类速查表（design D6）；示例**必带** `knowledge_base_ids`（坑 6）；**如实写明**「本轮平台尚未受理应用侧访问凭据，retrieve 会答『凭据被拒』——这不是你的代码写错了」（坑 5 / 坑 32）。
  ③ 新增「## 3. 附件存储（storage）」：六函数；本地目录 vs 平台存储、不进上传包与 git、同一 API、按应用隔离、无直链、不暴露底层实现（bucket / 键 / 端点 / 凭据）、**不计租户存储配额**；本地上限只在注入 `BISHENG_APP_STORAGE_MAX_FILE_MB` 时生效（坑 23、坑 34）。
  ④ 第 1 章身份头表里 `X-BiSheng-Access-Token` 那一行的说明由「本轮没有消费方，**不要依赖**它做任何判断；SDK 用法随后续版本补齐」改成「每请求的短时访问凭据句柄，`retrieve` 用它；应用不要自己解析或转存」——**同批修改 F053 的断言** `test_skill_packs.py::test_auth_chapter_teaches_exactly_app_proxys_header_names` 末尾那句 `assert "不要依赖" in token_row`（改为断言新措辞含「不要自己解析」），理由与 T026 改 `sdk` null 断言同型：契约变了，守卫跟着变，同一 PR 里改完。
  两章插在第 1 章之后、应用数据库章之前，**同批更新目录编号与锚点**（原 2/3/4/5 章顺延为 4/5/6/7，锚点 `#2-应用数据库` 等一并改；改完 `grep -n "^#\|](#" SKILL.md` 双向对表）。另在末尾「## 参考」前加一节「SDK 装哪来 / 准入门槛」：`pip install --extra-index-url <平台>/api/v1/dev-toolkit/simple/ bisheng-sdk`、托管构建期只需 `requirements.txt` 写 `bisheng-sdk`、以及 chat / appdb 为什么不在 SDK 里（一段）。全文零真实密钥。
  **覆盖 AC**: AC-26, AC-27, AC-28, AC-30, AC-32, AC-35, AC-36
  **依赖**: T000, T021（API 定稿）
  **证据**: `skills/platform-wiring/SKILL.md`（10607e923）：填 SDK 桩、插第 2/3 章、原 2–5 章顺延为 4–7、目录与锚点同批更新、末尾加第 8 章；`X-BiSheng-Access-Token` 行改措辞并同批改 F053 的 `test_skill_packs.py` 守卫断言。全文反引号里的 `X-BiSheng-*` 仍恰为 app-proxy 的十个。
  **偏差（评审期修正）**: 本任务 ② 要求的「如实写明」照初稿写成了「**平台尚未受理**应用侧访问凭据」，这一句现在**是错的**——F055 的托管检索（`filelib.py` 的 `HOSTED_APP_ACTOR_KIND` 分支 → `CapabilityBusService.retrieve`）与访问者凭据核验（`composition.py` 注册 `AccessSubjectVerifier`）都已合入 `3.0-vibe`，线上这条路是通的（前提是部署配了 `app_runtime.obo_secret`）。照原文写会把开发者支去查一个没坏的平台。改为：线上通、**本地 `bisheng dev` 不通**，并点名本地的两处上游缺口（不注入 `BISHENG_APP_TOKEN`、本地自签句柄平台无从验签）。同批：错误表补 `AppCredentialMissingError` 行（本地实际先撞的就是它）、检索章补「两把凭据各答什么、不可互换、没有 owner 兜底」一段（settled 契约在正文里落地，不只在 design 里）。T035 的断言同批改：由 `assert "尚未上线" in chapter` 改为断言新措辞 + `assert "尚未上线" not in chapter`。

- [x] **T034**: SDK 版可运行样例（FastAPI，三件套齐用）——**新目录 `example-sdk/`，不动既有 `example/`**〔2h〕
  **文件**: `src/backend/bisheng/dev_toolkit/skills/platform-wiring/example-sdk/main.py`（新）, `.../example-sdk/bisheng-app.yaml`（新）, `.../example-sdk/requirements.txt`（新：`fastapi`、`uvicorn`、`bisheng-sdk`）
  **逻辑**: **为什么另起目录**：F053 已交付的 `example/` 是零依赖标准库样例，`test_skill_packs.py::test_example_is_stdlib_only` 对两个包都断言 `requirements.txt` 为空/无第三方；把 SDK 塞进它会当场红，且「不装 SDK 也能接线」是 spec AC-32 承认的合法路径，不该被删。`SKILL.md`（T033）在 SDK 各章指向 `example-sdk/`，「参考」节两个样例都列。
  内容：`app.add_middleware(bisheng_sdk.auth.ASGIMiddleware)`；`GET /`（页面：`你好，{user.user_name}` + 部门 + 「本地开发 · 服务账号」角标当 `subject_kind == "service_account"`）；`GET /healthz`（**不调 auth**）；`GET /__whoami`（回显本请求的十头，供 T036 自检解析）；`POST /ask`（`retrieve.search(q, knowledge_base_ids=[...])`，库 id 从 `bisheng-app.yaml` 的 `capabilities.knowledge_bases` 同源读一份常量）；`POST /upload` / `GET /files` / `GET /files/{path}`（storage 三操作，下载由应用自己吐流——AC-22）；每个端点把 D6 异常翻成 4xx JSON `{error, next_step}`（**不 500、不 traceback**）。四条托管契约（PORT / 0.0.0.0 / `/data` / `BISHENG_APP_BASE_PATH`）照 `deploy-hosting/example/main.py`。manifest 声明一个知识库能力（`capabilities` 非空）——⚠️ F053 的 `test_skill_packs.py::test_example_manifest_is_valid_against_the_platform_schema` 断言 `manifest.capabilities.is_empty()`，但它只读 `example/bisheng-app.yaml`，**不覆盖 `example-sdk/`**；`test_example_is_stdlib_only` 同理只读 `example/requirements.txt`。这正是另起目录的原因，两条断言一字不改。`example-sdk/` 的 schema 合法性由 T035 单列断言。
  **覆盖 AC**: AC-26, AC-30, AC-32, AC-34
  **依赖**: T033
  **证据**: `skills/platform-wiring/example-sdk/{main.py,bisheng-app.yaml,requirements.txt}`（10607e923）；既有 `example/` 一字未动。清单声明一个知识库能力，与 `main.py` 的 `KNOWLEDGE_BASE_IDS` 由 T035 的断言守着同源。
  **偏差（评审期修正）**: `/ask` 原来把 `AppCredentialMissingError` 兜进最后那条 `BishengSdkError → 502`，读起来是「平台挂了」，实际是本应用没拿到运行期凭据（本地必然如此）。单列一条 → 503，T035 加一条断言守它排在兜底分支之前。
  **评审期实跑**（不入库，仅记录）：把姊妹切片 `wt/f057-sdk-core` 的包放到 `PYTHONPATH` 后用 `TestClient` 跑本样例：`/healthz` 无身份 200；`/` 无身份 401「未取得平台注入的访问者身份」、有身份 200 且显示姓名；`/ask` 有身份无应用凭据 503、完全无身份 401「检索不会以任何其它身份发起」。四种开发者常犯的错各得一条可区分的明确拒绝，无一条静默给出错误答案。

- [x] **T035**: 技能包增量 + SDK 样例 + 自检脚本测试〔1.5h〕
  **文件**: `src/backend/test/dev_toolkit/test_platform_wiring_sdk.py`（新；**不改** F053 的 `test_skill_packs.py`——那里的共通断言与 `WIRING` 专项断言继续守 F053 的部分，本文件只加 SDK 增量的断言）
  **测试**: `test_auth_chapter_still_first_with_warning_block_after_edit`（回归守 F053 契约：第一个 `## ` 标题含「访问者身份」；其后首个非空行以 `> ⚠️` 开头）→ AC-27 / `test_auth_chapter_teaches_sdk_one_liner_and_three_wrong_ways`（含 `auth.current_user()` 与「自建登录页」「自己解析」「自己校验」三类错误做法；**桩句「随后续版本补齐」已消失**）→ AC-27 / `test_retrieve_chapter_states_per_user_and_local_diff`（含「白名单」「可见范围」「fail-closed」「本地看得少」「真实账号」）→ AC-35 / `test_storage_chapter_states_local_online_diff_and_quota`（含「不计」「配额」「不进」「上传包」「直链」）→ AC-36 / `test_model_chapter_still_marked_unavailable_and_invents_no_base_url`（回归：仍含「暂未提供」，不含拼 base URL 的示例）→ AC-30 / `test_toc_anchors_resolve`（目录每条 `](#…)` 都能在正文找到对应标题，防章节顺延漏改锚点）→ AC-26 / `test_no_sdk_wrapper_for_model_or_appdb`（全文不含 `bisheng_sdk.chat` / `bisheng_sdk.appdb`）→ AC-30 / `test_example_sdk_manifest_valid_against_schema`（`AppManifest(**yaml)` 不抛；`capabilities` 非空且只声明知识库）→ AC-26 / `test_example_sdk_requirements_pin_bisheng_sdk` → AC-02 / `test_example_sdk_healthz_does_not_call_auth`（`main.py` 源码里 `/healthz` 处理函数体内无 `current_user`）→ AC-27 / `test_selfcheck_readable_failure_without_env`（`subprocess` 空 HOME、无 `BISHENG_*` → 非零退出、输出含「未」或「下一步」、无 `Traceback`）→ AC-28 / `test_selfcheck_reports_incompatible_sdk_readably`（假 `versions` 响应经 `BISHENG_PLATFORM_API_BASE` 指向本地 `http.server`，`min_compatible="9.9.9"` → 输出含双方版本）→ AC-03, AC-28 / `test_sdk_guide_endpoint_serves_this_file`（`read_sdk_guide()` 内容 == `platform-wiring/SKILL.md`）→ AC-26
  **覆盖 AC**: AC-02, AC-03, AC-26, AC-27, AC-28, AC-30, AC-35, AC-36
  **依赖**: T033, T034
  **证据**: `test/dev_toolkit/test_platform_wiring_sdk.py`（17 用例，含两条回归：auth 章仍第一 + 章首警示块、模型章仍「暂未提供」且无 URL）（10607e923）。

- [ ] **T035a**（F051 落地后追加）: 模型章的两条回归断言要改口径〔0.3h〕
  **起因**: T034 / T035 里的 `test_model_chapter_still_marked_unavailable_and_invents_no_base_url` 假定模型面尚未交付。F051 已交付并定名三个环境变量，该断言从此守错了东西。
  **改成**: ① 模型章不再含「暂未提供」，而是教官方 `openai` 客户端 + **`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `BISHENG_MODEL_BASE_URL`** 三个注入名；② **仍然断言包里没有手拼的 base URL 字面量**（`/api/v2/model/v1` 只能来自 `whoami.model_base_url` 或注入的环境变量，F051 AC-30 的唯一出口口径不变）；③ `test_no_sdk_wrapper_for_model_or_appdb` 一字不改——SDK 依旧不封装 chat（DEV-07）。
  **另附**：指南需写明 `X-BiSheng-Access-Token` 由应用代码**显式转发**给模型面，否则调用记录的 subject 记为「应用自身」（F051 spec 决议-5 允许，但审计里就没有用户维度了）。
  **覆盖 AC**: AC-26, AC-30
  **依赖**: T035

- [x] **T036**: `selfcheck.py` **增量**：在 F053 已交付的脚本上追加 SDK 三步〔2h〕
  **文件**: `src/backend/bisheng/dev_toolkit/skills/platform-wiring/selfcheck.py`（**增量**，109 行版本已含：读 `~/.bisheng/credentials.json` → 打 `/api/v2/auth/whoami` → 校验应用库变量，`fail(reason, next_step)` 打两行并 `SystemExit(1)`）
  **逻辑**: 沿用既有 `fail()` 与输出风格、**不重写骨架**（F053 的 `test_selfcheck_reports_readable_reason_when_not_logged_in` 对两包参数化，改掉未登录分支的文案会红）。追加（D13）：① `import bisheng_sdk`（失败 → 打印 `pip install --extra-index-url <base>/api/v1/dev-toolkit/simple/ bisheng-sdk`，`<base>` 取 `BISHENG_PLATFORM_API_BASE` 或凭据文件的 `current`；**SDK 未装不算致命**——脚本继续跑既有三步后以「SDK 未安装」退出 1） ② `urllib` 打 `/api/v1/dev-toolkit/versions` 比对 `sdk.min_compatible`（脚本自己算三段元组，不 import SDK 内部函数；`sdk` 为 null → 提示「平台未发布 SDK 安装件 / 开放能力层未部署」） ③ auth：`BISHENG_APP_ID` 存在则对 `http://127.0.0.1:${BISHENG_APP_PORT}/__whoami` 发一次请求（经 `bisheng dev` 迷你代理进来的回显）再 `auth.from_headers` 解析；否则 `fail("未经 bisheng dev 启动", "在项目根执行 bisheng dev，用它打印的本地入口地址访问")` ④ retrieve：`bind` 上 ③ 的头后 `search("selfcheck", top_k=1)`，逐类异常翻一句；**`VisitorCredentialRejectedError` 时明确写「平台尚未受理应用侧访问凭据（本地为 `bsdev.` 句柄、线上为 OBO），不是你的密钥问题」**（坑 5 / 坑 32） ⑤ storage：`put/stat/delete` `_selfcheck/probe.txt`；无句柄时提示「`bisheng dev` 尚未注入 `BISHENG_APP_STORAGE_DIR`」（坑 34）。全程不打 traceback、不打密钥。
  **测试**: T035 全部通过；`cd src/backend && uv run pytest test/dev_toolkit -q` 全绿（含 F053 既有用例）。
  **覆盖 AC**: AC-03, AC-28
  **依赖**: T035
  **证据**: `selfcheck.py` 追加五步（装没装 / 版本兼容 / 身份 / 检索 / 附件），沿用既有 `fail()` 与输出风格（10607e923）；T035 用真 `http.server` + 桩 `bisheng_sdk` 跑通「版本不兼容」与「SDK 未装」两条可读失败路径，输出无 Traceback。
  **偏差（评审期修正）**: 本任务 ③ 写的探测地址 `http://127.0.0.1:${BISHENG_APP_PORT}/__whoami` **不成立**——`bisheng dev` 起两个监听，迷你代理（本地入口，注入身份头）听 `--port` / 清单 `port`，而 `PORT` / `BISHENG_APP_PORT` 注入给应用的是**应用自己**那个（`commands/dev.py` 的 `proxy_port` / `app_port`，后者是 `pick_free_port`）。照原文实现这一步**永远过不了**，且把原因报成「你直连了应用端口」。改为：入口地址按 `argv[1]` → `BISHENG_DEV_ENTRY_URL` → 最近 `bisheng-app.yaml` 的 `port` 解析（`dev_entry_url()`）；解析不到或连不上 → **跳过**身份 / 检索 / 附件三步（与 `check_app_db` 在普通 shell 里的处理一致），不再判失败；④ 增 `AppCredentialMissingError` 分支（`bisheng dev` 不注入 `BISHENG_APP_TOKEN`，本地实际先撞的是它，不是「凭据被拒」），`VisitorCredentialRejectedError` 文案改为「本地自签平台无从验签 / 线上过期或签给别的应用」。SKILL.md §7 同批改运行方式。

- [x] **T037**: README、指针与目录树〔1h〕
  **文件**: `src/bisheng-sdk/README.md`（增量：安装两种方式、三行用法、异常速查、「完整指南见 `GET /api/v1/dev-toolkit/sdk-guide.md` / `skills sync` 后的 `platform-wiring/SKILL.md`」——**不复制章节**，决议-7）, `src/backend/bisheng/dev_toolkit/skills/deploy-hosting/SKILL.md`（增量：`:138` 「由另一份技能覆盖，本轮不展开」改为指向 `platform-wiring`）, `src/backend/bisheng/dev_toolkit/skills/README.md`（增量：**`wt/cli-dev` 已把 `platform-wiring/` 加进目录树**——本任务只在其条目下补一行 `example-sdk/` 与「含 SDK 三件套章」），`src/backend/bisheng/dev_toolkit/guides/install-guide.md`（增量：一句「装 SDK 见 sdk-guide.md」，若该文件有安装段）
  **覆盖 AC**: AC-26, AC-32
  **依赖**: T033
  **证据**: `skills/deploy-hosting/SKILL.md` 的 capabilities 条改为指向 `platform-wiring`、`skills/README.md` 目录树补 `example-sdk/` 与自检说明、`guides/install-guide.md` 第 4 步后加 SDK 安装命令与 `sdk-guide.md` 指针（10607e923）。**偏差**：`src/bisheng-sdk/README.md` 由姊妹切片的 T001 创建，本切片不碰它以免同文件冲突——合并后需按本任务原意补一句「完整指南见 `GET /api/v1/dev-toolkit/sdk-guide.md`」。

- [x] **T038**: 核对 CLI `DEFAULT_PACKS` + 用合并版脚本重打 CLI wheel（跨 Feature，串行）〔1h〕
  **文件**: `src/bisheng-cli/bisheng_cli/commands/skills.py`（**仅当仍是单元素时**改 `:57`）, `src/bisheng-cli/tests/test_command_skills.py`（同前提；`wt/cli-dev` 已补「其一 404 时另一仍成功」用例）, `src/backend/bisheng/dev_toolkit/artifacts/bisheng_cli-3.0.0-py3-none-any.whl` + `manifest.json`（重打）
  **逻辑**: ① `grep -n "DEFAULT_PACKS" src/bisheng-cli/bisheng_cli/commands/skills.py`——`wt/cli-dev` 合并后应已是 `("deploy-hosting", "platform-wiring")`，**是则常量与测试零改动**；仍是单元素（合并丢了）才补，并同批补测试。② 无论改没改都要重打一次 wheel：T023 把打包脚本改成了合并写 manifest，旧 wheel 对应的 manifest 段需要用新脚本重生成——`cd src/bisheng-cli && uv run pytest -m "not network"` 全绿 → `bash scripts/pack_cli_wheel.sh` → 确认 `manifest.json["sdk"]` 段**原样保留**、`cli` 段只有 sha256 可能变 → 提交。⚠️ 与 T029 串行（同一 `artifacts/` 目录，坑 35）。
  **覆盖 AC**: AC-28, AC-32
  **依赖**: T000, T023, T029, T033
  **证据**: `DEFAULT_PACKS` 已是 `("deploy-hosting", "platform-wiring")`，常量与测试零改动；用合并版脚本重打 CLI wheel 一次，manifest 仅 `_note` 变、wheel sha256 不变（78f231bce）。

- [x] **T039**: auth 静默失败点评测样本 + 结构断言〔1.5h〕
  **文件**: `src/backend/test/dev_toolkit/fixtures/auth_silent_failure_samples.md`（新）, `src/backend/test/dev_toolkit/test_auth_silent_failure_samples.py`（新）
  **逻辑**: 样本 ≥ 5 条、不含产品名、朴素答案会是"做个登录页"的应用需求（如「做一个内部请假申请页，要知道是谁提交的」「做个部门看板，只让本部门的人看」「做个文件上传工具，按人隔离」「做个问答机器人，答案只能来自用户有权限的知识库」「给同事做个小工具，需要显示当前登录人的名字和部门」），每条附「未读包的典型产出」与「读包后应有产出」判据（不自建登录 / 不自读头 / 用 `auth.current_user()`）。测试：`test_at_least_five_samples`、`test_samples_are_product_name_neutral`、`test_each_sample_carries_identity_intent`（含「谁」「登录」「当前用户」「身份」「部门」「权限」之一）、`test_skill_auth_chapter_lists_forbidden_patterns`（照 `test_skill_trigger.py` 风格）。
  **覆盖 AC**: AC-29
  **依赖**: T033
  **证据**: `test/dev_toolkit/fixtures/auth_silent_failure_samples.md`（6 条样本，各带「未读包的典型产出 / 读包后应有产出」两半判据）+ `test_auth_silent_failure_samples.py`（5 条结构断言）（10607e923）。

- [ ] **T040**: 评测跑分（模型判定）并回填〔1.5h〕
  **文件**: 本文（回填）
  **逻辑**: 用 `skill-creator` 评测：对 T039 每条样本各跑「未读包 vs 读包（含 `platform-wiring/SKILL.md`）」两次生成，人工 / 模型判定读包后 5/5 不自建登录、改读 `auth.current_user()`；把样本 id、判定与日期回填到本文「实际偏差记录」上方的评测记录小节。未达 100% → 改 SKILL.md auth 章后重跑，不改判据。
  **覆盖 AC**: AC-29
  **依赖**: T039
  **未做（需跑模型评测）**: 样本与判据已就位（T039），评测跑分需要「未读包 vs 读包」两轮生成，不在本切片的离线能力内。

### Wave 7 · 端到端旅程、114 手验、回写

- [ ] **T041**: 端到端旅程测试文件（默认跳过，阻塞项落地后启用）〔3h〕
  **文件**: `src/backend/test/e2e/test_e2e_f057_sdk_journey.py`（新，照 `test_e2e_f053_openapi_auth_identity.py` 的 `F057_E2E=1` 门 + `E2E_API_BASE`）
  **逻辑**: 前置：平台已部署 T029 / T031、F053 `dev`（`wt/cli-dev` 已合）、F052/F055 OBO 受理（阻塞项 ②）、F054 附件 API（`wt/storage-handle` 已合并部署）。步骤：① `pip install --extra-index-url … bisheng-sdk` 于临时 venv；② `bisheng deploy` T034 的 `example-sdk/`（含知识库能力声明）→ 审批通过（`approve_online_114.py` 同型辅助）；③ 用两个**非 admin** 用户会话经 `/apps/{slug}/` 访问：`GET /` 各得自己的姓名 / 部门；`GET /healthz` 无头 200；④ `POST /ask` 的结果集合 == 同用户直接 `POST /api/v2/filelib/retrieve`（PAT / 会话派生）限定声明库的结果（**集合相等**）；用户无权的库不出现；未声明的库经应用 → `TargetUnreachableError` 或 `CapabilityNotDeclaredError` 的 4xx；⑤ 应用 A 上传 → 应用 B（第二个样例实例）`GET /files` 列不到；⑥ 下线应用后 `POST /ask` / `POST /upload` 得可区分错误。清理只动 `e2e-f057-*` 前缀资源。
  **覆盖 AC**: AC-13, AC-14, AC-15, AC-17, AC-21, AC-24, AC-34
  **依赖**: T029, T031, T034；**阻塞**：design §6.2 阻塞项 ②（托管期 retrieve）与 ③（本地期 retrieve）、契约 ③④⑦
  **未做（Wave 7，不在本切片范围）**

- [ ] **T042**: 114 手动验证（`/e2e-test features/v3.0.0/057-bisheng-sdk`）〔3h，`needs_114`〕
  **文件**: 本文（回填「114 验证记录」）
  **逻辑**: 顺序：`versions` 的 `sdk` 段 → `curl -OJ …/sdk/download` + `pip install` → `simple/` 两页 → `sdk-guide.md` → `skills sync` 拉到两个包并接入 `~/.claude/skills/` → `bisheng dev` 跑 `example-sdk/`（auth 必过；retrieve 预期答「凭据被拒」= 阻塞项 ③、storage 预期「无句柄」= 契约 ⑦，**如实记录为上游未就绪，不判 SDK 缺陷**）+ `selfcheck.py` → `deploy` → 两个非 admin 用户访问（**不用 admin**，super_admin 短路 ReBAC）→ 回填每步结果与阻塞项状态。storage 托管期先看 `GET /v1/runtime/status` 的 preflight `attachment_storage.ok`，systemd 形态需 `RTM_APP_FACING_BASE_URL` 指到 `bisheng-apps` 网桥网关（坑 27）。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-10, AC-13, AC-14, AC-20, AC-23, AC-28, AC-34
  **依赖**: T029, T032, T038；部分受阻于 design §6.2 阻塞项 ②③ 与契约 ③④⑦
  **未做（需 114，Wave 7）**

- [ ] **T043**: 跨 Feature 回写登记（只追加文档条目，不改他人代码）〔1h〕
  **文件**: `features/v3.0.0/053-dev-cli-skills/tasks.md`（**T043 增补**：注入 `BISHENG_APP_STORAGE_DIR=<项目根>/.bisheng/attachments/` 绝对路径 + 写 `.bisheng/.gitignore` + 建议同名注入 `BISHENG_APP_STORAGE_MAX_FILE_MB`（取平台 `RTM_STORAGE_MAX_FILE_MB`）、**不注入 `_ENDPOINT`**；**T042 增补**：`devproxy.HandleMinter` 的本地自签 `bsdev.` 句柄改为平台签发的短时凭据，否则本地 retrieve 恒 `26001`）, `features/v3.0.0/055-app-publish-pipeline/tasks.md`（T057 追加 OBO Bearer 受理 + `entry_authz` 签发改 fail-closed；T058 追加 `16273` 载荷 `data.capability` / `data.reason="revoked"`）, `features/v3.0.0/052-mcp-server-face/spec.md` 或其未来 tasks（`knowledge_base_ids` 可省略；「不可及」码 + `data.unreachable_ids`；受理平台签发的本地短时凭据）
  **不写回 F054**：附件句柄契约以 `wt/storage-handle` 为准，本文只做消费者（design §6.2 回写登记第 1 条）；仅在本任务结果里记一句事实——F057 `_storage_remote.py` 是该 router Bearer 路径的首个消费者，`validate_key` / 路由 / 信封任何改动会让 `test_contract_alignment.py` 先红。
  **依赖**: T021, T027（契约定稿后）
  **未做（Wave 7，不在本切片范围）**；另注：`features/v3.0.0/052-mcp-server-face/tasks.md` 同期有别的切片在改，回写应在其收口后单独做，避免同文件冲突。

---

## AC 追溯表

| AC | 任务 | AC | 任务 | AC | 任务 |
|---|---|---|---|---|---|
| AC-01 | T007, T024, T025, T026, T027, T042 | AC-13 | T041, T042（旅程引用，经 F052 / F055） | AC-25 | T003, T004, T016, T017, T018, T019, T020, T021 |
| AC-02 | T026, T027, T030, T031, T032, T035 | AC-14 | T010, T011, T014, T015, T041, T042 | AC-26 | T024, T025, T026, T027, T033, T034, T035, T037 |
| AC-03 | T007, T012, T013, T014, T015, T024, T025, T026, T027, T035, T036 | AC-15 | T003, T004, T014, T015, T041 | AC-27 | T033, T035 |
| AC-04 | T003, T004, T005, T006, T010, T011 | AC-16 | T010, T011, T014, T015 | AC-28 | T033, T035, T036, T038, T042 |
| AC-05 | T012, T013, T026, T027, T042 | AC-17 | T010, T011, T014, T015, T041 | AC-29 | T039, T040 |
| AC-06 | T005, T006, T042 | AC-18 | T010, T011, T014, T015 | AC-30 | T007, T033, T034, T035 |
| AC-07 | T003, T004, T005, T006 | AC-19 | T003, T004, T010, T011, T014, T015 | AC-31 | T005, T006, T018 |
| AC-08 | T005, T006, T014, T015 | AC-20 | T016, T017, T018, T019, T020, T021, T042 | AC-32 | T033, T034, T037, T038（验收随 PRD-2 WB-01） |
| AC-09 | T005, T006 | AC-21 | T016, T017, T018, T019, T020, T021, T041 | AC-33 | T007 |
| AC-10 | T005, T006, T042 | AC-22 | T016, T017, T018, T019, T020, T021 | AC-34 | T034, T041, T042（旅程引用） |
| AC-11 | T014, T015 | AC-23 | T016, T017, T020, T021, T042 | AC-35 | T033, T035 |
| AC-12 | T007, T014, T015 | AC-24 | T016, T017, T021, T041 | AC-36 | T033, T035 |

**计数**：44 任务（T000–T043）；工时合计约 **80.5h**（Wave 0 ≈ 0.5 · Wave 1 ≈ 17.5 · Wave 2 ≈ 13 · Wave 3 ≈ 12.5 · Wave 4 ≈ 10 · Wave 5 ≈ 4 · Wave 6 ≈ 14.5 · Wave 7 ≈ 7；不含归对方 Feature 的阻塞项 ②③ 与契约 ③④⑦）。

**AC 覆盖结论**：36 条 AC 全部至少被一个带「覆盖 AC」标注的任务覆盖（上表逐条可查）。其中 **AC-13 / AC-34 只由 T041 / T042 覆盖**（服务端旅程，SDK 侧无可单测的行为），**AC-32 的「与 PRD-2 WB-01 同一范式」半边随 PRD-2 验收**（release-contract 表 3 F057 行已如此约定）——两者都不是遗漏，是刻意的旅程引用。

---

## 114 验证记录

（T032 / T042 回填）

## 评测记录（AC-29）

（T040 回填）

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复。推翻已定案的决策先记 design 决策再记这里。

- **retrieve 的凭据形状按 F055 已合入实现改写**（2026-09-16，design D5 / CON-3 已同步）：一次检索送**两把**凭据——`Authorization: Bearer <BISHENG_APP_TOKEN>`（应用运行期凭据，平台据此取当前生效声明的白名单）与 `X-BiSheng-Access-Token`（本请求注入的访问者凭据，平台据此确立访问用户）。初稿「只把访问者凭据当 Bearer 送」作废：`credential_validator` 不受理 OBO 令牌，且门面无从知道是哪个应用在调、取不到白名单。访问者凭据仍然只从请求上下文取，应用凭据只经 `_env.app_token()` 一处读取。
- **新增异常类 `AppCredentialMissingError`**（D6 表由 18 类变 19 类）：应用运行期凭据未注入时的明确错误。本地 `bisheng dev` 期必然命中它（本地没有已上线的应用，因此没有应用凭据），这正是「本地期 retrieve 不可端到端验证」在 SDK 侧的如实呈现——不开兼容分支、不拿 `login` 密钥顶替。
- **`_codes.py` 不再留空位**：F052 的门面码已分配（`26320` 无执行身份 / `26321` 不可及含 `unreachable_ids` / `26322` 能力已收回 / `26323` 范围过大），前三个已登记映射，`26323` 按「未登记码原样呈现」走 `PlatformRefusedError`。
- **新增私有模块 `_attachment.py`**（design §4.3 模块表已补）：`AttachmentMeta` 放在这里而不是 `storage.py`，否则两个后端 import 它会与 `storage` 形成循环 import。公开面集合不受影响（仍是四个非下划线模块）。
- **`tag_match_mode` 字面量是大写 `"ANY"`**：design §4.2 ③ 初稿的示例写的是小写，服务端 `RetrieveFilters` 的 Literal 只认 `"ANY"` / `"ALL"`，小写会 422。已就地改正 design。
- **审查回合修掉的两处实现缺陷**（2026-09-16，详见 T019 / T020 条目下）：① 附件端点的传输层失败漏翻成 `StorageUnavailableError`，托管期最常见的 storage 故障被呈现成"平台连不上"（design D6 / 坑 27 / AC-25）；② `storage.aopen` 从未实现，而 `test_six_functions_and_six_async_twins_exist` 只断言了五个孪生，让缺失看不出来（D10）。两处的测试都已收紧成"缺了就会点名"的形状。
- **一条留给 F052 的 fail-closed 预警**（design §8 已登记）：`knowledge_base_ids=[]` 今天被服务端 `min_length=1` 拒，SDK 原样送出即可；F052 放宽必填时若把 `[]` 也当成「未指定 = 全部被授予范围」，一个把目标库过滤到空的应用就会静默检索得**比它要的更宽**——那时 SDK 要在 `_body` 里把 `[]` 挡成明确错误。
- **本切片范围**：Wave 1–3（T001–T021）+ T008 的 CI 门。T022–T043（打包脚本、manifest、四个分发端点、runtime-manager 取包、技能包增量、指南、评测样本、114 联调）归姊妹切片 `f057-sdk-dist` 与后续波次，本切片未动 `src/backend/bisheng/dev_toolkit/artifacts/`。
