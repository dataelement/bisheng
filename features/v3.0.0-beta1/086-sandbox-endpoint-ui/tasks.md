# Tasks: 沙箱接入参数页面配置

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户确认 |
| design.md | ✅ 已评审 | 用户确认；保存分两次请求、鉴权用 `is_global_super` |
| tasks.md | ✅ 已拆解 | 8 Wave / 21 项 |
| 实现 | 🔲 进行中 | 20 / 21 完成。T020 需要两台 runner 与已连接的助手，这次没有跑 Compose 联调 |

---

## 开发模式

按 Wave 组织。后端先写测试再写实现。前端把地址解析、保存顺序抽成纯函数，用 vitest 覆盖；弹窗交互用手动验证。

没有新的 Celery 任务，也没有 Client 改动。新建执行器仍走 `build_code_executor`，在那里改为读 `settings.get_sandbox_conf()`。日常会话每条消息、工作流每次运行都会新建。助手连接复用执行器，由 `refresh_open_code_executors` 在每轮对话开始时就地更新地址与令牌。`config` 表没有 `tenant_id`，不传租户。

鉴权只判断 `login_user.is_global_super`，不调用 PermissionService，不写 OpenFGA。保存时前端先 `POST /api/v1/tool/sandbox_conf`，成功后再走原有的工具配置保存。

不建表、不改列。回滚是删掉 `config` 表 `key=sandbox_endpoint` 的行，并删掉 Redis key `config:sandbox_endpoint`（db 以 `redis_url` 为准，发行配置是 `/1`）。

---

## Tasks

### Wave 1 — 基础设施

- [x] **T001**: 错误码与配置 key
  **文件**: `src/backend/bisheng/common/errcode/sandbox.py`,
           `src/backend/bisheng/common/models/config.py`
  **逻辑**: 新增 `SandboxEndpointInvalidError`，`Code=28009`，`Msg` 用英文。`ConfigKeyEnum` 增加 `SANDBOX_ENDPOINT = "sandbox_endpoint"`。不建表。
  **依赖**: 无

- [x] **T002**: 28009 三语文案
  **文件**: `src/frontend/packages/locales/src/api_errors/zh-Hans.json`,
           `src/frontend/packages/locales/src/api_errors/en.json`,
           `src/frontend/packages/locales/src/api_errors/ja.json`
  **逻辑**: 增加 `"28009"`。中文说明地址必须是 http/https、带主机名、端口合法、不能是空地址、去掉末尾 `/` 后不能重复、不超过 32 个。不手改 `platform/public/locales/*/api_errors.json` 与 `client/src/locales/*/api_errors.gen.json`。
  **覆盖 AC**: AC-12
  **依赖**: 无

- [x] **T003**: 审计事件
  **文件**: `src/backend/bisheng/database/models/audit_log.py`,
           `src/backend/bisheng/api/services/audit_log.py`
  **逻辑**: `EventType` 增加 `UPDATE_SANDBOX_CONF = "update_sandbox_conf"`。`AuditLogService.update_sandbox_conf(user, ip, note)` 内部调用 `_system_log(user, ip, group_ids=[], event_type=UPDATE_SANDBOX_CONF, object_type=ObjectType.TOOL, object_id="sandbox_endpoint", object_name="sandbox_endpoint", note=note)`。`note` 由调用方传入，本方法不拼令牌。调用方不传 `group_ids`。
  **依赖**: 无

### Wave 2 — 生效值读取

- [x] **T004**: `get_sandbox_conf` 测试
  **文件**: `src/backend/test/sandbox/test_get_sandbox_conf.py`
  **逻辑**: mock Redis 与 `ConfigDao.get_config`。库记录的 `value` 是 JSON 字符串，不是 dict。结构合法指 dict，且 `endpoints` 是字符串列表（可为空）、`token_enc` 是字符串（可为空串）。`null`、数组、缺字段、列表里有非字符串，都算不合法。无记录时返回值与 `settings.sandbox_conf` 逐字段相同。页面 `endpoints` 非空只覆盖地址，页面 `token_enc` 非空只覆盖令牌，另一项留空仍用部署值。空数组与空 `token_enc` 回退部署值。设置 `BS_SANDBOX_CONF__TOKEN` 后页面令牌仍生效（合并必须用 `model_copy`，不能重新构造 `SandboxConf`）。Redis 抛错或命中的值结构不合法时都改读库。库结构合法则本次用库里的值，且不调用 `set` 或 `setNx`。库也抛错、`value` 不是合法 JSON、或结构不合法时，回退部署配置并有 error 日志，不向外抛异常，日志不含令牌明文。`decrypt_token` 抛错同样回退部署配置并记 error 日志。未命中回填调用 `setNx`，写入的是结构合法的 dict `{"endpoints", "token_enc"}`，不是 JSON 字符串，也不是合并后的 `SandboxConf`，缓存中无令牌明文；已有合法 key 时 `setNx` 不覆盖。`setNx` 抛错时仍返回库里的值。先写入新缓存再回填，读到的仍是新值。
  **覆盖 AC**: AC-06, AC-07, AC-09, AC-10
  **依赖**: T001

- [x] **T005**: `ConfigService.get_sandbox_conf`
  **文件**: `src/backend/bisheng/common/services/config_service.py`
  **逻辑**: 同步方法。Redis key `config:sandbox_endpoint`，TTL 60 秒，客户端用 `get_redis_client_sync()`（db 跟 `redis_url`）。结构合法指 dict，且 `endpoints` 是字符串列表（可为空）、`token_enc` 是字符串（可为空串）。命中且结构合法则直接用，不读库。未命中、抛错或结构不合法都 `ConfigDao.get_config(ConfigKeyEnum.SANDBOX_ENDPOINT)`，对 `config.value` 做 `json.loads`。库结构合法则本次用这份 dict。只有最初未命中（key 不存在）时 `setNx` 回填（已有 key 不改值；`setNx` 在 key 已存在时仍会 `expire`，只刷新 TTL）。缓存结构不合法或 Redis 抛错时不再写入，坏 key 留到自身 TTL 结束。`setNx` 抛错仍返回这份库值，不回退部署配置。库结构不合法或 `json.loads` 失败则不回填，回退部署配置。解密只用于本次合并，结果不写入 Redis。`decrypt_token` 抛错视同读失败。合并只用 `settings.sandbox_conf.model_copy(update=...)`。同文件提供 `write_sandbox_endpoint_cache(payload)`，`payload` 是刚落库并确认结构后的 dict，用 `set(key, payload, expiration=60)` 覆盖写入；只有保存路径调用。不要自己 pickle，不要把 JSON 字符串或坏结构写入 Redis。库不可用、JSON 解析失败、库结构不合法与解密失败都记 `sandbox endpoint config unreadable; using deployment config`，日志不含令牌明文，异常不向外抛。
  **测试**: T004 全部通过
  **覆盖 AC**: AC-06, AC-07, AC-09, AC-10
  **依赖**: T004

### Wave 3 — 执行器接入

- [x] **T006**: factory 改读页面配置的测试
  **文件**: `src/backend/test/sandbox/test_factory_page_conf.py`
  **逻辑**: `build_code_executor("container")` 把 `settings.get_sandbox_conf()` 的返回值传给 `ContainerExecutor`，不再读 `settings.sandbox_conf`。执行器只用这份 `endpoints`，空列表不可达，不扫描主机名。先构建出的执行器在随后配置变化后仍持有构建时的地址与令牌。`local` / `e2b` 分支不读沙箱配置。
  **覆盖 AC**: AC-07, AC-11
  **依赖**: T005

- [x] **T007**: factory 接入
  **文件**: `src/backend/bisheng_langchain/gpts/tools/code_interpreter/factory.py`
  **逻辑**: container 分支改为 `kwargs["sandbox_conf"] = settings.get_sandbox_conf()`。`_CONTAINER_POOL_KEYS` 仍从调用方 kwargs 剥掉（含已退役的 `discover_*`）。不改 local / e2b。不扫描主机名。
  **测试**: T006 全部通过
  **覆盖 AC**: AC-06, AC-07, AC-11
  **依赖**: T006

- [x] **T021**: 助手每轮刷新执行器
  **文件**: `src/backend/test/sandbox/test_refresh_open_code_executors.py`，`src/backend/bisheng_langchain/gpts/tools/code_interpreter/factory.py`，`src/backend/bisheng/api/services/assistant_agent.py`
  **逻辑**: `refresh_open_code_executors(tools)` 只处理名为 `bisheng_code_interpreter`、执行器是 `ContainerExecutor`、且 `keep_session` 为假的工具。若 `_bound_url` 与 `_session_id` 都在，先调用 `_release()`（它会 `DELETE` 远端会话，并清掉 `_bound_url`、`_session_id`、`_lease_token`）。不要自己把这两个字段置空。然后就地改这个执行器对象的 `endpoints` 与 `token` 为 `settings.get_sandbox_conf()` 的当前值，每个地址去掉末尾 `/`。不新建执行器对象。`keep_session` 为真、`local`、`e2b` 都不改。浅拷贝后共享同一执行器的工具，刷新后两边看到同一组新地址。`AssistantAgent.run` 在调用模型之前调用它，传入 `self.tools`。不重跑 `init_tools`。日常会话的 `_prepare_tools` 不调用它。
  **测试**: 先写测试再改实现。未粘滞且仍占会话的容器执行器会先 `_release()`，再被就地更新；带末尾 `/` 的地址更新后不带 `/`。粘滞的不变，也不调用 `_release()`。浅拷贝共享的执行器一起变。
  **覆盖 AC**: AC-06, AC-11
  **依赖**: T007

### Wave 4 — 读取视图与保存

- [x] **T008**: 沙箱配置服务测试
  **文件**: `src/backend/test/sandbox/test_sandbox_conf_service.py`
  **逻辑**: mock `ConfigDao`、Redis、`AuditLogService`。保存写入的 key 是 `sandbox_endpoint`，`insert_or_update_config` 的 `value` 是 `json.dumps` 得到的字符串，payload 无 `tenant_id`。比较前去掉每个地址末尾的 `/`。非法地址（非 http/https、无主机名、端口越界、去掉末尾 `/` 后重复、超过 32 个、空串项）抛 `SandboxEndpointInvalidError`，不写库。合法地址落库时不带末尾 `/`。`token` 为 `********` 时 `token_enc` 不变；空串时 `token_enc` 变为空；其他值落库为 `encrypt_token` 密文，库内与日志、审计 `note` 都无明文。`note` 只含变更字段名，令牌变更写「已修改」。审计调用是 `update_sandbox_conf(user, ip, note)`，其内部传给 `_system_log` 的 `group_ids` 为 `[]`、`object_name` 为 `sandbox_endpoint`。保存后调用 `write_sandbox_endpoint_cache(解析后的 dict)`，参数是 `{"endpoints", "token_enc"}`，不是 JSON 字符串，不含明文令牌；该调用抛错时保存仍然成功，并记 error 日志。保存不发起任何 HTTP。读取响应的 `endpoints` 是页面存的列表：页面地址为空、部署有地址时，响应 `endpoints` 为 `[]`，`address_source` 为 `deployment`。库里的 `value` 不是合法 JSON，或不是「`endpoints` 为字符串列表、`token_enc` 为字符串」的 dict 时，`get()` 按没有页面配置返回（`endpoints` 为 `[]`，来源按部署配置是否有值），不抛异常。来源按字段分开：页面该项非空则该项为 `page`（令牌显示 `********`）；该项页面空且部署该项非空为 `deployment`；该项两边都空为 `default`。页面只填地址、部署只设令牌时，`address_source=page` 且 `token_source=deployment`；反过来 `token_source=page` 且 `address_source=deployment`。`deployment_address` 在部署配了 `endpoints` 时为这些地址的逗号拼接，否则为空串。
  **覆盖 AC**: AC-03, AC-04, AC-06, AC-08, AC-09, AC-12, AC-13, AC-17
  **依赖**: T001, T003, T005

- [x] **T009**: `SandboxConfService` 的读取与保存
  **文件**: `src/backend/bisheng/tool/domain/services/sandbox_conf_service.py`
  **逻辑**: `get()` 返回 design §4.2 的读取结构。响应里的 `endpoints` 是页面存的列表，页面没填地址时为 `[]`，不填入部署地址。库里的 `value` 解析失败或结构不合法（不是 dict、`endpoints` 不是字符串列表、或 `token_enc` 不是字符串）时，按没有页面配置返回，不抛异常。`save` 是 async。`save(endpoints, token, user, ip)` 做 T008 的校验、去掉末尾 `/` 与令牌合并，必须 `await ConfigDao.insert_or_update_config("sandbox_endpoint", json.dumps(...))`（`value` 只能是字符串；只有异步版本；`get_config` 才是同步的），再 `write_sandbox_endpoint_cache(json.loads 后的 dict)`（dict 只含 `endpoints` 与 `token_enc`；失败只记 error 日志，不让保存失败；缓存 TTL 60 秒，与 AC-06 相同），再 `AuditLogService.update_sandbox_conf(user, ip, note)`。来源按字段分开：该项页面值非空为 `page`；否则该项部署值非空为 `deployment`；否则 `default`。地址只看页面 `endpoints`，令牌只看页面 `token_enc`。不读不写 `gpts_tools.extra`。不读取 `discover_*`。
  **测试**: T008 全部通过
  **覆盖 AC**: AC-03, AC-04, AC-08, AC-09, AC-12, AC-13, AC-17
  **依赖**: T008

### Wave 5 — 测试连接

- [x] **T010**: 测试连接分类测试
  **文件**: `src/backend/test/sandbox/test_sandbox_conf_probe.py`
  **逻辑**: `test` 是 async，用 `httpx.AsyncClient` 与 `httpx.MockTransport`，不调用同步 `httpx`。非法地址（非 http/https、无主机名、端口越界、去掉末尾 `/` 后重复、超过 32 个、空串项）抛 `SandboxEndpointInvalidError`，transport 收到 0 次请求。合法地址先去掉末尾 `/`，再用规范化后的地址拼 `/health` 与 `/v1/sessions`（`http://host:8080/` 不得请求成双斜杠）。每次请求超时 5 秒，超时记为 `unreachable`。`/health` 失败 → `unreachable`，且不调用建会话。建会话 401 → `token_rejected`。503 → `busy`。200 → `ok`，并且用响应里的 `lease_token` 调用 `DELETE /v1/sessions/{id}`。请求地址为空时，逐个探测部署配置的 `endpoints`（同样先校验）；这份列表也空则结果为空。请求令牌为 `********` 时用已保存令牌，页面也没有则用部署令牌。结果里没有 runner 响应体。
  **覆盖 AC**: AC-12, AC-14, AC-16
  **依赖**: T009

- [x] **T011**: `SandboxConfService.test`
  **文件**: `src/backend/bisheng/tool/domain/services/sandbox_conf_service.py`
  **逻辑**: 只新增 async `test(endpoints, token)`，不改 T009 的 `get` / `save`。先按与保存相同的规则校验地址，不合法抛 `SandboxEndpointInvalidError` 且不发请求。通过后再去掉末尾 `/`，用 `httpx.AsyncClient` 按 T010 的分类探测，不在事件循环里调用同步 HTTP。每个地址 `GET {url}/health` 与 `POST {url}/v1/sessions`（`Authorization: Bearer`）各等待 5 秒，超时记为 `unreachable`；成功则 `DELETE`（`x-lease-token`）。写一条 info 日志，不含令牌与响应体。
  **测试**: T010 全部通过
  **覆盖 AC**: AC-12, AC-14, AC-16
  **依赖**: T010

### Wave 6 — HTTP 接口

- [x] **T012**: 三个接口的权限与保存测试
  **文件**: `src/backend/test/sandbox/test_sandbox_conf_api.py`
  **逻辑**: `GET/POST /api/v1/tool/sandbox_conf` 与 `POST /api/v1/tool/sandbox_conf/test`。`is_global_super` 为假时三个接口都是 `UnAuthorizedError`，不写库。为真时委托 `SandboxConfService`，响应为 `resp_200`。保存请求不要求先测试成功。
  **覆盖 AC**: AC-02, AC-13
  **依赖**: T009, T011

- [x] **T013**: 挂到工具路由
  **文件**: `src/backend/bisheng/tool/api/tool.py`
  **逻辑**: 三个接口只做参数接收与 `is_global_super` 判断（否则 `UnAuthorizedError`），业务交给 `SandboxConfService`。不注册新 router，不调用 PermissionService。
  **测试**: T012 全部通过
  **覆盖 AC**: AC-02
  **依赖**: T012

### Wave 7 — Platform 弹窗

- [x] **T014**: 地址解析与保存顺序测试
  **文件**: `src/frontend/platform/src/test/sandboxEndpoint.test.ts`
  **逻辑**: 多行文本解析成地址数组：去空白、去掉空行、去掉每个地址末尾的 `/`。去掉斜杠后的重复、非法地址、超过 32 个能被标出。`sandboxSavePlan("container", true)` 为先沙箱后工具；`sandboxSavePlan("local", true)` 与 `sandboxSavePlan("container", false)` 为只保存工具配置。三语 `tool.json` 含地址提示（逐个填副本、不要只填负载均衡）、测试结果只代表平台服务进程、四条测试状态文案。
  **覆盖 AC**: AC-01, AC-05, AC-12, AC-15, AC-19
  **依赖**: 无

- [x] **T015**: 纯函数
  **文件**: `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/sandboxEndpoint.ts`
  **逻辑**: 实现 T014 依赖的解析、校验与 `sandboxSavePlan`。不发请求。
  **测试**: T014 中纯函数部分通过
  **覆盖 AC**: AC-01, AC-05, AC-12
  **依赖**: T014

- [x] **T016**: 弹窗文案三语
  **文件**: `src/frontend/platform/public/locales/zh-Hans/tool.json`,
           `src/frontend/platform/public/locales/en-US/tool.json`,
           `src/frontend/platform/public/locales/ja/tool.json`
  **逻辑**: 替换 `executionContainerHint`。新增地址、令牌、来源（页面配置 / 部署配置 / 默认值）、测试连接、四条结果、AC-15 说明、AC-19 提示的 key。三语同时加。
  **测试**: T014 中文案部分通过
  **覆盖 AC**: AC-08, AC-15, AC-19
  **依赖**: T014

- [x] **T017**: 接口封装
  **文件**: `src/frontend/platform/src/controllers/API/tools.ts`
  **逻辑**: 用现有 request 封装 `getSandboxConfApi`、`saveSandboxConfApi`、`testSandboxConfApi`，路径与 T013 一致。不直接 `import axios`。
  **覆盖 AC**: AC-01
  **依赖**: T013

- [x] **T018**: 弹窗
  **文件**: `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/SandboxEndpointFields.tsx`,
           `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/CodeExecutor.tsx`
  **逻辑**: 打开弹窗时 `getSandboxConfApi`。地址输入只用响应里的 `endpoints`（空数组保持空白），`deployment_address` 只用于来源说明，不填进输入框。选中「沙箱运行」才渲染地址（多行）与令牌，并标明两项来源；令牌只显示掩码。测试连接用当前输入调用 `testSandboxConfApi`，结果旁展示 AC-15 说明。保存时按 `sandboxSavePlan`：需要存沙箱时先 `saveSandboxConfApi`，成功后再 `onSubmit`；切到本地或 E2B 时不调用沙箱保存。`extra` 里的 `container` 仍是 `{}`。
  **覆盖 AC**: AC-01, AC-05, AC-08, AC-13, AC-14, AC-15, AC-19
  **手动验证**:
  - 超级管理员打开「构建 → 工具 → 内置工具 → 代码执行器」，选「沙箱运行」，能看到地址、令牌、来源与测试连接
  - 填非法地址点保存，请求被拒绝，弹窗不关
  - 改成合法地址保存成功；再打开令牌为掩码；不改令牌再保存，令牌不变
  - 切到「本地隔离运行」保存后再切回，地址仍在
  - 非超级管理员打开同一弹窗，看不到或保存被拒绝
  **依赖**: T015, T016, T017

### Wave 8 — 文档与联调

- [x] **T019**: 两份说明
  **文件**: `features/v3.0.0-beta1/068-code-execution-sandbox/沙箱部署说明.md`,
           `features/v3.0.0-beta1/068-code-execution-sandbox/沙箱使用说明.md`
  **逻辑**: 写明页面入口（代码执行器弹窗 → 沙箱运行）、页面优先于环境变量与 yaml、留空回退、清空即恢复、保存后 60 秒内新执行生效（日常会话的下一条消息、已打开助手的下一轮对话、工作流的下一次运行；不用断开重连。写缓存失败时旧值仍靠 TTL 落在这 60 秒内）、正在跑的任务本轮仍用旧副本、页面改不了网络、测试结果只代表 backend、缓存 key 在 `redis_url` 的 db。不改 F068 的部署步骤本身。
  **覆盖 AC**: AC-18
  **测试降级**: 文档没有可执行断言，对照 AC-18 的四句话逐条出现在两份文档中
  **依赖**: 无

- [ ] **T020**: Compose 联调
  **文件**: 无代码改动
  **逻辑**: 按 design §7 的四步，生效等待按 60 秒计：两台 runner；页面把地址指到 `code-runner-1` 并测试连接；60 秒内工作流代码节点、一次日常会话，以及一条已经连着的助手的下一条消息，只打到 1；令牌写错时测试结果为令牌不被接受；非法地址测试连接返回 28009。清空页面配置后，执行改用部署配置里的两台地址。正在跑的任务在本轮结束前仍打旧副本。
  **覆盖 AC**: AC-06, AC-09, AC-11, AC-12, AC-14
  **测试降级**: 要同时起 backend、worker、Linsight 与两台 runner，单测覆盖不了跨进程生效
  **依赖**: T007, T013, T018, T019, T021

---

## 实际偏差记录

（实现中如有偏离，只留一行指针，论证回写 design.md。）
