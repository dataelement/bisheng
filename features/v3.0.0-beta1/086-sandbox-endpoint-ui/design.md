# Design: 沙箱接入参数页面配置

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答做什么；本文回答为什么这么实现；`tasks.md` 是流水账。
> - 实现变化 → 覆盖更新本文档；推翻已 ★ 确认的决策要停下与用户重新确认。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-10-21

---

## 1. 目标与非目标

- **目标**：让超级管理员在代码执行器配置弹窗里填写沙箱服务地址与访问令牌，保存后 60 秒内，三类进程（backend、Celery worker、Linsight）新发起的沙箱执行改用新值；没填的项继续用部署配置里的服务地址列表。
- **非目标**：
  - 不恢复按主机名扫描副本。地址只来自页面或 `endpoints`。
  - 不把超时、副本池大小等参数搬到页面（spec 范围排除）。
  - 不改 F068 的执行、租约、失败与隔离语义，不改 runner。
  - 不按租户区分沙箱配置。
  - 不解决 Fernet 主密钥是开源常量的问题（F068 已排除，见 §8）。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C8，版本契约见 `release-contract.md`（F086 行、280 错误码段）。本功能特有的约束：
- **生效链路必须覆盖三类进程**：执行器在 backend（日常会话、助手、编辑器「运行一次」）、Celery worker（工作流运行）、Linsight（任务模式）里各自构建。只在 backend 内存里改值不算生效。
- **新建执行器都经过 `build_code_executor`**（`bisheng_langchain/gpts/tools/code_interpreter/factory.py`）。日常会话每条消息在 `_prepare_tools` 里新建；工作流每次运行新建。助手的 WebSocket 在连接期间复用同一个执行器，每轮对话开始时就地改地址与令牌（坑 8），不再次调用 `build_code_executor`。任务模式在任务开始时构建一次并粘滞到本轮结束（AC-11）。
- **`build_code_executor` 是同步函数**，会在 Celery 线程、Linsight 的 asyncio 任务里被调用。读配置只能用同步客户端，且要足够便宜（一次 Redis GET）。
- **工具配置按租户分行**：`t_gpts_tools_type` 有 `tenant_id`，而沙箱副本池是部署级的。spec AC-03 要求全局一份。
- **runner 只在创建会话时校验 token**（`src/sandbox-runner/app.py` 的 `create_session`），`/health` 不校验。验证 token 必须真的建一个会话再删掉。
- **没有页面配置时只用部署地址**（AC-10）：生效地址等于部署配置的 `endpoints`。列表为空则没有副本，不扫描主机名。

---

## 3. 方案对比与选定

### 决策 1：页面配置存在哪里

- **备选**：
  - A. 内置工具 `t_gpts_tools_type.extra.config.container` — 与 E2B 的 `api_key` 同一处，前端改动最小；但该表按租户分行，多租户下每个租户各一份，违背 AC-03；且 F068 的 `factory.py` 明确把沙箱参数从 `extra` 剥掉（`_CONTAINER_POOL_KEYS`），这条约定是为了防止残留工具配置覆盖池参数。
  - B. 系统配置 YAML（`config` 表 `initdb_config`）新增一段 — 已有 Redis 缓存与保存即删缓存的机制；但 `GET /api/v1/settings` 原样返回整段 YAML 文本，令牌只能明文展示，无法满足 AC-04。
  - C. `config` 表新增一条独立记录，key 为 `sandbox_endpoint`，值为 JSON — 表无 `tenant_id`，天然全局；值可单独加密、脱敏、校验。
- **选定**：C。
- **原因**：只有 C 同时满足全局一份（AC-03）和令牌不明文（AC-04）。先例：`jwt_secret`（`user/domain/services/jwt_secret.py`）也是 `config` 表独立记录。key 不叫 `sandbox_conf`，避免与 YAML 顶层段 `sandbox_conf` 混淆。
- **何时该重新考虑**：出现按租户分配沙箱池的需求时，改为带租户维度的存储。

### 决策 2：生效值怎么合并、在哪里读

- **备选**：
  - A. 保存时写进每个进程的 `settings.sandbox_conf` — 跨进程做不到，需要广播或重启。
  - B. 每次 `build_code_executor` 时读页面配置，与 `settings.sandbox_conf` 合并成本次的生效值 — 每次构建多一次 Redis GET。
  - C. 进程内缓存几十秒再读 — 省 Redis 调用，但「保存后多久生效」变成取决于各进程缓存的时间窗。
- **选定**：B。读取逻辑放在 `ConfigService.get_sandbox_conf()`（`common/services/config_service.py`），`factory.py` 在新建执行器时调用它。助手不在每轮重建执行器：`refresh_open_code_executors` 再调一次 `get_sandbox_conf()`，就地改已有 `ContainerExecutor` 的 `endpoints` 与 `token`（坑 8）。
- **原因**：
  - 执行器构建频率远低于 Redis 承受能力（新建时一次，助手每轮对话再读一次）。缓存 TTL 是 60 秒，与 AC-06 的时限相同：保存时把新值写入缓存，写入失败不让保存失败。未命中后的回填只在 key 不存在时写入，避免一次还在进行的旧读取盖掉刚保存的新值。写失败后若 key 里仍是旧值，过期后下一次执行仍会读到库里的新值。
  - 放在 `ConfigService` 与既有的热加载读法同处（`get_workflow_conf`、`get_cofco_forwarding_conf`），`factory.py` 原本就只依赖这个模块，不新增 `bisheng_langchain` 对领域模块的依赖。
  - 合并规则：两项分别判定。页面 `endpoints` 非空则覆盖；页面 `token` 非空则覆盖；否则沿用部署值。用 `settings.sandbox_conf.model_copy(update=...)` 生成新对象（原因见 §5 坑 1）。
- **何时该重新考虑**：执行器构建进入高频热路径（例如每个 token 流式片段都构建），或 Redis 成为瓶颈时，改为带版本号的进程内缓存（参考 `ConfigDao.aget_config_version`）。

### 决策 3：读写接口放在哪个模块、页面怎么保存

- **备选**：
  - A. 新建顶层模块 `bisheng/sandbox/`（api + domain） — 归属最清楚，但只有三个接口，还要注册新路由。
  - B. 放进 `tool` 模块，挂在 `/api/v1/tool/sandbox_conf` 下 — 入口本来就是工具页的代码执行器弹窗，权限判定与 `update_tool_config` 一致（`is_global_super`）。
  - C. 复用 `/api/v1/tool/config`：前端把地址和令牌塞进 `extra`，后端识别代码执行器后拆出来存全局 — 一次请求；但工具配置是租户维度的写操作，混入全局写会让一个接口同时有两种作用域，且违背决策 1 不进 `extra` 的约定。
- **选定**：B。弹窗保存时前端先调沙箱配置保存接口，成功后再调原有的工具配置保存。
- **原因**：B 的改动面最小且作用域清晰。两次请求的不一致窗口只有一种：沙箱配置已保存、执行方式没保存成功。此时执行方式仍是旧值，地址只在选「沙箱运行」时才被使用，不会造成错误执行。
- **何时该重新考虑**：沙箱配置出现工具页以外的入口（例如系统设置页）时，迁到独立模块。

### 决策 4：令牌怎么存、怎么脱敏

- **备选**：
  - A. 把 `token` 加进 `JsonFieldMasker.sensitive_fields`（`utils/mask_data.py`），复用工具配置的脱敏合并 — 该表是全局的，会把其他工具 `extra` 里所有名为 `token` 的字段一并改为掩码，影响面不可控。
  - B. 在沙箱配置服务内自行处理：存储时用 `encrypt_token`（Fernet，`core/config/settings.py`）加密；读取接口只返回 `********` 与「是否已设置」；保存时收到 `********` 视为不修改，收到空串视为清空。
- **选定**：B。
- **原因**：避免 A 的连带影响；掩码字面量沿用 `JsonFieldMasker.mask_api_key` 的 `********`，前端已有处理这种掩码的写法。
- **何时该重新考虑**：Fernet 主密钥外置立项后（§8），改用新的密钥管理方式。

### 决策 5：测试连接怎么判定

- **备选**：
  - A. 只探 `/health` — 无副作用，但无法判断令牌对不对（`/health` 不校验令牌），满足不了 AC-14。
  - B. 先探 `/health`，再用令牌 `POST /v1/sessions`，成功则立即 `DELETE` 释放 — 能区分四种结果，代价是短暂占用一个槽位。
- **选定**：B。请求里地址为空时，逐个探测部署配置的 `endpoints`；这份列表也空则结果为空，不发请求。待探测的地址先按保存规则校验，不合法则返回 28009 且不发请求。合法地址去掉末尾 `/` 后再拼 `/health` 与 `/v1/sessions`。探测用 `httpx.AsyncClient`，不在事件循环里调用同步 HTTP。每个地址的这两次请求各等待 5 秒，超时视为不可达。令牌为 `********` 时用已保存的令牌，页面也没有就用部署令牌。结果映射：`/health` 不通或超时 → 不可达；建会话 401 → 令牌不被接受；503 → 副本繁忙、令牌未能验证；200 → 可用，并立即释放（AC-16）。
- **原因**：令牌校验点只有建会话这一个；占槽时间是一次往返，可以接受。
- **何时该重新考虑**：runner 增加不占槽的鉴权探测接口时，改用该接口。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**保存**：
`CodeExecutor 弹窗「保存」 → saveSandboxConfApi → POST /api/v1/tool/sandbox_conf → SandboxConfService.save（校验并去掉地址末尾 / → 令牌合并加密 → json.dumps 后 await ConfigDao.insert_or_update_config 写 sandbox_endpoint → 把解析后的 dict 写入 Redis → 审计） → 前端再调 updateToolApi 保存执行方式`

**执行时读取**：
`日常会话每条消息在 _prepare_tools 里新建执行器。工作流每次运行新建执行器。助手的 WebSocket 在连接期间复用同一个执行器对象：AssistantAgent.run 开头，若未粘滞的 ContainerExecutor 仍占着会话则先 _release()，再把 endpoints（去掉末尾 /）与 token 改成 settings.get_sandbox_conf() 的当前值。灵思任务在任务开始时构建一次并粘滞，本轮不刷新（AC-11）。`
`build_code_executor("container") → settings.get_sandbox_conf()（Redis 中的合法 dict 直接用；未命中、抛错或结构不合法则 json.loads 库里的字符串。结构合法指 dict，endpoints 为字符串列表，token_enc 为字符串。库合法则本次用库的值。只有 key 不存在时 setNx 回填；坏缓存或 Redis 抛错都不在读取路径上写入。库也不合法或解密失败则回退部署配置） → ContainerExecutor(sandbox_conf=生效值）。副本就是生效 endpoints；空列表则不可达`

**测试连接**：
`弹窗「测试连接」 → POST /api/v1/tool/sandbox_conf/test（async 路由） → AC-12 校验，不合法则 28009 → 去掉地址末尾 / → httpx.AsyncClient 逐地址 /health（5 秒）→ POST /v1/sessions（5 秒）→ DELETE → 每个地址一条结果`

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `config` 表 key `sandbox_endpoint` 的 `value` | `str`，内容是 `json.dumps` 后的 `{"endpoints": [str], "token_enc": str}` | `Config.value` 与 `insert_or_update_config` 只收字符串。`token_enc` 为 Fernet 密文，空串表示页面未设令牌；行不存在等价于两项都未设。读出后 `json.loads` | `ConfigService.get_sandbox_conf` |
| Redis key `config:sandbox_endpoint` | 解析后的 dict `{"endpoints", "token_enc"}`，TTL 60 秒 | 只缓存这份密文 dict，不缓存解密后的 `SandboxConf`、令牌明文，也不缓存 JSON 字符串。`endpoints` 的每一项与 `token_enc` 都是字符串，列表可以为空。保存时用 `get_redis_client_sync().set(..., expiration=60)` 覆盖写入刚落库的 dict。未命中回填用 `setNx`，key 已存在则不改值。命中但结构不合法，或 Redis 抛错时，改读库且读取路径不再写入；坏 key 留到自身 TTL 结束。写入失败只记日志，已经读到的合法库值仍然使用。位于 `redis_url` 指定的 db。读写都走该客户端（值经 pickle） | 三类进程 |
| `GET /api/v1/tool/sandbox_conf` 响应 `data` | `{"endpoints": [str], "token": "********" \| "", "address_source": "page" \| "deployment" \| "default", "token_source": 同, "deployment_address": str}` | `endpoints` 是页面存的列表，可以为空，不是与部署配置合并后的生效地址。来源按字段分开：该项页面值非空为 `page`；否则该项部署值非空为 `deployment`；否则 `default`。地址看页面 `endpoints`，令牌看页面 `token_enc`。`deployment_address` 是部署配置 `endpoints` 的逗号拼接，只用于展示来源；部署没配地址时为空串 | platform 前端 |
| `POST /api/v1/tool/sandbox_conf` 请求体 | `{"endpoints": [str], "token": str}` | `token` 为 `********` 表示不改，空串表示清空；`endpoints` 为空数组表示回退部署配置 | platform 前端 |
| `POST /api/v1/tool/sandbox_conf/test` 请求体 / 响应 `data` | 请求同上；响应 `{"results": [{"url": str, "status": "ok" \| "unreachable" \| "token_rejected" \| "busy"}]}` | 不回传 runner 响应体 | platform 前端 |
| 错误码 `28009` | `SandboxEndpointInvalidError` | 地址不合法（非 http/https、无主机名、端口越界、空地址、去掉末尾 `/` 后重复、超过 32 个） | platform 前端 `api_errors` |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `common/models/config.py` | 新增 `ConfigKeyEnum.SANDBOX_ENDPOINT` | 不放读写逻辑 |
| `common/services/config_service.py` `get_sandbox_conf()` | 同步读取页面配置。Redis 命中且结构合法则直接用。未命中、抛错或结构不合法都改读库并 `json.loads`。结构合法指 dict，`endpoints` 为字符串列表（可为空），`token_enc` 为字符串（可为空串）。库合法则本次用库的值。只有 key 不存在时 `setNx` 回填。坏缓存与 Redis 抛错都不在读取路径上写入。库也不合法、解析失败或解密失败则回退部署配置并记 error 日志。回填失败仍用已经读到的合法库值。解密只用于本次合并。另提供 `write_sandbox_endpoint_cache(payload)`，`payload` 是刚落库的合法 dict，仅保存路径调用 | 不写业务配置、不做地址校验；读取路径不得用 `set` 覆盖缓存；未命中回填不得用 `set` 覆盖已有 key；不得把明文令牌、JSON 字符串或坏结构写入 Redis |
| `tool/domain/services/sandbox_conf_service.py`（新） | 读取（脱敏 + 按字段判来源）、保存（校验、去掉地址末尾 `/`、令牌合并、加密、`json.dumps` 后写入、再把 dict 写入缓存、审计）、测试连接。`get()` 遇到坏结构时按没有页面配置返回。`save` 与 `test` 均为 async。`test` 用 `httpx.AsyncClient` | 不碰 `gpts_tools.extra`；不在事件循环里做同步 HTTP；`get()` 不因坏结构抛异常 |
| `tool/api/tool.py` | 三个接口，`is_global_super` 判定 | 不含业务逻辑 |
| `bisheng_langchain/.../factory.py` | container 分支改为 `settings.get_sandbox_conf()`。另提供 `refresh_open_code_executors(tools)`：未粘滞的 `ContainerExecutor` 若仍占会话则先 `_release()`，再就地改 `endpoints`（去掉末尾 `/`）与 `token` | 不读库、不读 Redis 以外的配置；不扫描主机名；不替换执行器对象；不手清 `_bound_url` / `_session_id` |
| `api/services/assistant_agent.py` `run` | 每轮对话开始时调用 `refresh_open_code_executors(self.tools)` | 不重建整份工具列表，不刷新 `keep_session` 的执行器 |
| `common/errcode/sandbox.py` | 新增 `28009` | — |
| `api/services/audit_log.py` | 新增 `update_sandbox_conf(user, ip, note)`，内部走 `_system_log(..., group_ids=[], ..., object_id="sandbox_endpoint", object_name="sandbox_endpoint", note=note)` | 不记令牌值；不让调用方填 `group_ids` |
| platform `controllers/API/tools.ts` | 三个 API 封装 | — |
| platform `builtInTool/SandboxEndpointFields.tsx`（新） | 地址多行输入、令牌输入、来源标注、测试连接与结果展示 | 不直接发请求以外的保存逻辑 |
| platform `builtInTool/CodeExecutor.tsx` | 打开时读取沙箱配置；选「沙箱运行」时渲染上面的子组件；仅在选「沙箱运行」且字段有改动时，保存先存沙箱配置再交给 `onSubmit`，切到其他方式保存不动沙箱配置（AC-05） | 不把地址和令牌写进 `extra`（仍是 `container: {}`） |
| F068 `沙箱部署说明.md`、`沙箱使用说明.md` | 写明页面配置入口、与环境变量的优先级、清空即回退、Redis db 注意事项（AC-18） | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `SandboxConf` 的 `overlay_env` 是 `model_validator`：每次用 `SandboxConf(**dict)` 或 `model_validate` 构造，都会把 `BS_SANDBOX_CONF__*` 环境变量重新盖上去 | 用构造函数合并页面值，环境变量会反过来覆盖页面值，Compose / Helm 部署（都设了 `TOKEN`）上页面令牌永远不生效 | `get_sandbox_conf` 只用 `model_copy(update=...)`，不重新校验 |
| 2 | 配置缓存在 `redis_url` 指定的 db（发行配置是 `/1`），不是 db0。`RedisClient.setNx` 在 key 已存在时仍会 `expire`，只刷新 TTL，不改值。保存时写缓存失败不会让保存失败 | 去 db0 写 key 等于没写；或把回填写成 `set`，进行中的旧读取会盖掉刚保存的新值，再撑满 60 秒。写失败后若 key 里仍是旧值，这 60 秒就是 AC-06 的时限 | 运维说明写明 db；保存用 `set` 覆盖，回填只用 `setNx`；`save` 捕获写缓存异常并记 error 日志 |
| 3 | runner 只在建会话时校验令牌 | 测试连接只探 `/health` 会把令牌错误判为可用，上线后所有沙箱执行 401 | 决策 5；`SandboxConfService.test` |
| 4 | 任务模式每个任务只构建一次执行器，且开着粘滞会话 | 保存后发现正在跑的任务仍打旧副本，会被当成「没生效」 | spec AC-11 已把它定为预期行为；使用说明写明 |
| 5 | Fernet 的 `secret_key` 是开源代码里的常量 | 把「令牌已加密」当成真正的保密措施；拿到库的人可以解密 | 本期接受（与 `config.yaml` 密码同级），§8 |
| 6 | 页面只填一个负载均衡地址（K8s ClusterIP Service）时，粘滞会话的下一跳可能落到别的副本 | 任务模式第二次执行读不到第一次写的文件 | spec AC-19 的页面提示；部署说明已有同样警告 |
| 7 | 测试连接接口能让超级管理员从 backend 探测任意 `host:port`。工具路由是 `async def`，同步 `httpx` 会占住事件循环 | 被当成内网 HTTP 探测器读取内部服务内容。32 个地址逐个同步等待时，这个进程上的其他请求一起卡住 | 先按 AC-12 拒绝非法地址且不发请求；只接受 http/https、最多 32 个地址；`httpx.AsyncClient`，每次请求 5 秒超时；只返回四种状态不回传响应体 |
| 8 | 助手的代码执行器挂在 WebSocket 的 `gpts_agent` 上，只在 `gpts_agent is None` 时构建。工具可能被浅拷贝，但共享同一个 executor 对象。`_release()` 在 `_bound_url` 或 `_session_id` 为空时直接返回，不会 `DELETE` | 只在 `build_code_executor` 里读新配置，已打开的助手下一轮仍打旧地址。换成新的执行器对象，浅拷贝仍拿着旧对象。手清这两个字段会留下远端会话，`_lease_token` 也清不掉。就地赋值若不去掉末尾 `/`，URL 会变成双斜杠 | 仍占会话时先 `_release()`，再就地改 `endpoints`（去掉末尾 `/`）与 `token`。日常会话每条消息走 `_prepare_tools` 新建执行器，不用这条刷新 |
| 9 | `Config.value` 是字符串，`insert_or_update_config(key, value: str)` 不收 dict。`json.loads` 对 `null`、数组或缺字段的对象不会抛错。`setNx` 在 key 已存在时不替换值。读取路径上的 `set` 会盖掉刚保存的新值。`_system_log` 必填 `group_ids` 与 `object_name` | 把 dict 写入 `value` 得到的不是合法 JSON。坏缓存若直接回退部署配置，会挡住库里仍然正确的那一行。读取路径再用 `set` 把刚读到的旧库记录写回，会盖掉保存刚写入的新缓存，最多再撑 60 秒。读取方按字段取值会抛异常。审计调用少参数会在运行时抛错 | 落库 `json.dumps`，读库 `json.loads`。结构合法指 dict，`endpoints` 为字符串列表，`token_enc` 为字符串。缓存不合法或 Redis 抛错时改读库，本次用库的值，读取路径不写缓存。只有 key 不存在时 `setNx`。保存仍用 `set`。库也不合法再回退部署配置。弹窗 `get()` 按没有页面配置返回。Redis 只放合法 dict。审计内部传 `group_ids=[]`、`object_name="sandbox_endpoint"` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/tool/sandbox_conf` | HTTP API（仅全局超级管理员） | platform 代码执行器弹窗 |
| `POST /api/v1/tool/sandbox_conf` | HTTP API（仅全局超级管理员） | 同上 |
| `POST /api/v1/tool/sandbox_conf/test` | HTTP API（仅全局超级管理员） | 同上 |
| `settings.get_sandbox_conf() -> SandboxConf` | 内部 Python API | `factory.build_code_executor`（新建执行器）、`refresh_open_code_executors`（助手每轮就地更新） |
| `config` 表 `sandbox_endpoint` 行 | 数据格式 | 本 Feature 独占写入 |
| 错误码 `28009` | 错误码 | platform 前端 `api_errors` 三语文案 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `SandboxConf` 字段名 `endpoints` / `token` 与 `overlay_env` 行为（F068） | 内部数据结构 | 字段改名或 `overlay_env` 改为非 validator 实现，合并逻辑要同步改 |
| `ContainerExecutor` 只使用 `endpoints`（F068，主机名扫描已删除） | 隐式行为 | 若再引入自动找副本，空地址会重新连上未配置的 runner |
| runner `POST /v1/sessions` 的 401 / 503 语义与 `DELETE /v1/sessions/{id}` 的 `x-lease-token` | HTTP 协议 | runner 改状态码，测试连接分类失准 |
| `encrypt_token` / `decrypt_token` 与 `secret_key` | 内部 Python API | 主密钥轮换后旧密文无法解密 → 与 Redis、库失败相同，回退部署配置并记 error 日志，不把明文写入缓存 |
| Redis 与 `config` 表可用 | 中间件 | 都不可用时回退部署配置（spec §3），页面配置暂时失效 |

---

## 7. 测试与可观测

- **单元测试**（`src/backend/test/sandbox/`）：
  - 合并规则：页面两项分别覆盖、留空回退、无记录时与 `settings.sandbox_conf` 逐字段相同；设置了 `BS_SANDBOX_CONF__TOKEN` 时页面令牌仍生效（坑 1）。
  - 读取降级：Redis 抛错或结构不合法时改读库，本次用库的值，读取路径不写缓存。库失败、密文解密失败、JSON 解析失败，或库的结构也不是「`endpoints` 为字符串列表、`token_enc` 为字符串」的 dict，再回退部署配置并记日志。已经读到合法库值之后，回填失败仍用这份库值。缓存与日志都无令牌明文。只有 key 不存在时用 `setNx` 回填这份 dict，不是库里的 JSON 字符串。
  - 保存：校验各类非法地址返回 28009（含空地址、去掉末尾 `/` 后重复、超过 32 个）；`********` 不改、空串清空；令牌密文落库；保存后缓存是新值，随后的 `setNx` 不覆盖它；审计 `note` 不含令牌。来源按字段分开。
  - `factory`：container 分支使用 `get_sandbox_conf()` 的 `endpoints`，不扫描主机名。`refresh_open_code_executors` 对未粘滞的容器执行器先 `_release()` 再就地更新，地址去掉末尾 `/`；`keep_session` 为真的不变；浅拷贝共享的执行器一起变。
  - 测试连接：用 `httpx.MockTransport` 配 `httpx.AsyncClient` 覆盖四种状态与「成功后必定 DELETE」。非法地址返回 28009 且没有任何请求。带末尾 `/` 的地址先去掉再拼路径。超时为 5 秒，超时记为不可达。探测不在事件循环里调用同步 `httpx`。
  - 权限：非全局超级管理员调用三个接口均被拒绝。
- **前端**：`SandboxEndpointFields` 的地址解析与校验写成纯函数，加 vitest 用例（参照 `src/frontend/platform/src/test/configValue.test.ts`）。
- **e2e**：按 spec 全部 AC 走 `/e2e-test`；其中「三类进程 60 秒内生效」需在 Compose 环境实测。
- **手动验证**（Compose）：
  1. 部署说明 2.1 起两台 runner，确认任务模式正常。
  2. 超级管理员打开「构建 → 工具 → 内置工具 → 代码执行器」，选「沙箱运行」，地址填 `http://code-runner-1:8080`，点测试连接，应显示可用；保存。
  3. 跑一个工作流代码节点、一次日常会话代码执行，并在一条已经连着的助手里再发一条会跑代码的消息。`docker logs bisheng-code-runner-1` 有 `/exec`、`code-runner-2` 没有。
  4. 令牌改成错的再测试，应显示「令牌不被接受」；清空地址与令牌保存，两台 runner 都重新有流量。
- **可观测**：保存与测试各写一条 info 日志（不含令牌）；`get_sandbox_conf` 降级时写 error 日志 `sandbox endpoint config unreadable; using deployment config`。

---

## 8. 后续改进 / 不打算做的事

- **Fernet 主密钥外置**：令牌加密的强度受限于开源常量 `secret_key`，与 `config.yaml` 密码同级。影响全部密文，归独立立项（F068 已排除）。
- **按主机名找副本**：已从产品去掉，不计划加回。扩容时把新副本的地址写进 `endpoints` 或页面。
- **测试连接从 worker / Linsight 进程发起**：需要跨进程下发探测任务，复杂度高；本期在页面明示结果只代表 backend（AC-15）。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-20 | 初版 | spec 确认后编写 |
| 2026-10-20 | 决策 3 与权限判定经用户确认：保存分两次请求（先沙箱配置，再执行方式）；鉴权用 `is_global_super`，不走 OpenFGA | 用户确认 |
| 2026-10-21 | AC-06 时限改为 60 秒，与缓存 TTL 相同；删缓存失败不让保存失败 | 方案评审 |
| 2026-10-21 | 去掉主机名发现及 `discover_*` 配置。副本只来自页面或部署配置的 `endpoints` | 用户要求 |
| 2026-10-21 | 来源按字段分开；保存写入新缓存，回填用 `setNx`；地址去掉末尾 `/` 后判重，并拒绝空地址与超过 32 个 | 方案评审 |
| 2026-10-21 | 读取回显页面存的地址列表；缓存只放含 `token_enc` 的 JSON；测试连接先去掉末尾 `/`；密文解不开回退部署配置 | 方案评审 |
| 2026-10-21 | 助手每轮对话就地刷新未粘滞执行器的地址与令牌；测试连接先做 AC-12 校验，单次请求超时 5 秒 | 方案评审 |
| 2026-10-21 | 库内存 JSON 字符串、Redis 存解析后的 dict；审计补 `group_ids` 与 `object_name`；助手刷新先 `_release()` 再去掉地址末尾 `/`；测试连接用异步客户端 | 方案评审 |
| 2026-10-21 | 保存写入 Redis 的是解析后的 dict；JSON 结构不对与读失败一样回退部署配置 | 方案评审 |
| 2026-10-21 | 缓存结构不合法或 Redis 抛错时改读库且读取路径不写缓存；弹窗坏结构按没有页面配置返回 | 方案评审 |
