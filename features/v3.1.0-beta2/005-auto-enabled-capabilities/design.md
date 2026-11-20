# Design: 工作台工具与技能「自动启用」

> 本文是 How 的唯一真相。需求口径见 [spec.md](./spec.md)，执行流水见 [tasks.md](./tasks.md)。
> 取证基线：分支 `feat/3.1.0-beta2/005-auto-enabled-capabilities`，起点 `21d642d831`（F004 分支最新提交）。下文行号以该提交为准。

---

## 1. 目标与非目标

**目标**：管理员把工作台工具或企业技能设为「自动启用」后，用户端的所有选择入口都不再出现它；用户在工作台的每次发送（直接回答、深度研究、接力运行）都自动带上它，用户的个人停用对它无效。

**非目标**：开放 API 不补入；助手、工作流不变；执行过程照常显示；不改默认值。见 spec 范围边界。

## 2. 关键约束

- **C2 双库**：技能表新增一个 `Integer NOT NULL DEFAULT 0` 列，MySQL 与 DM8 同一写法，沿用 `v3_0_0_linsight_skill_default_checked.py` 的 `column_exists` 守卫。
- **C3 多租户**：工具的使用方式存在租户的工作台配置 JSON 里，随配置继承；技能的使用方式在 `linsight_skill` 行上，按租户存。新增的 `update` 语句手写 `tenant_id` 条件（批量 update 不经过租户过滤器，见 backend AGENTS.md）。
- **C4 权限**：自动启用不绕过权限。工具先经过 `afilter_tools_by_use_permission`（`use` 权限），技能先经过 `UserSkillsService.records` 里的 `visible` 权限，再补入。
- **C8 多节点**：没有进程内状态。补入在 API 进程里完成，结果随消息写进 F004 的收件箱；Linsight worker 只读请求里已经带上的工具，以及数据库里技能行的 `auto_enabled` 列。
- **错误码**：本特性不新增错误码。

## 3. 方案对比与选定

### 决策 1：在后端补入，前端只负责不显示

- **选定**：后端在工作台的登录态发送入口（`workstation/api/endpoints/chat.py` 调 `stream_chat_completion` 之前）把自动启用的工具补进 `data.tools`。前端只从展示列表里去掉这些工具。
- **备选**：A. 前端在发送时自动带上隐藏工具。这要求网页端、桌面端嵌入页、旧版缓存页面都同步升级，任一处漏改，工具就静默失效；而且用户可以篡改请求把它去掉。B. 在 `run_send._send` 里补入。开关关闭时会走旧的 `chat_service` 分支（`chat_service.py:2884`），这条分支照样会漏。
- **原因**：入口这一处同时覆盖统一运行时和旧分支；开放 API 走 `open_endpoints/api/endpoints/workstation.py:100`，不经过这个入口，天然满足 AC-21。补入的工具写进 `data.tools` 后会随消息一起存进收件箱，接力运行读收件箱里的第一条消息，因此 AC-19 不需要另外处理。
- **何时推翻**：如果以后开放 API 也要补入，把补入函数移到 `stream_chat_completion` 里，用参数区分调用方。

### 决策 2：工具的使用方式用新增布尔字段 `auto_enabled` 表示，不改成枚举

- **选定**：`ToolConfig` 新增 `auto_enabled: bool = False`。用 model validator 保证互斥：`auto_enabled=True` 时把 `default_checked` 置为 False。三种使用方式由两个布尔组合得到：用户自选 = (False, False)，默认勾选 = (False, True)，自动启用 = (True, False)。
- **备选**：新增枚举字段 `usage`，废弃 `default_checked`。`default_checked` 有四个读方：客户端、DSH `capability_catalog`、开放 API 的日常配置、平台配置页。改成枚举就要改全部读方，并兼容存量 JSON。
- **原因**：只加字段，老数据不用迁移就满足 AC-03（缺字段即 False）；老读方继续读 `default_checked`，读到的值不变。
- **何时推翻**：如果出现第四种使用方式，两个布尔不够表达时，再统一改成枚举。

### 决策 3：技能的使用方式用新列 `linsight_skill.auto_enabled`

- **选定**：新增列，新增接口 `PATCH /api/v1/linsight/skill/{name}/auto-enabled`，写法照 `set_default_checked`，只更新这一列和 `update_time`。
- **原因**：接口不经过 `update_from_form` / `update_from_upload`，所以不会把内置技能的 `source` 翻成 `manual`。内置技能重新同步时（`builtin_skill_seeder._seed_one`）只改名称、描述和包，不改这一列，满足 AC-08。
- **停用技能**：后端照常保存，`auto_enabled` 只在 `enabled=1` 时生效；前端在技能停用时把开关置灰（AC-07）。后端不拒绝，避免为「先停用、再改使用方式」这种操作顺序新增错误码。
- **何时推翻**：如果技能的使用方式也要按租户配置继承（像工具那样），就要把它移进配置 JSON。

### 决策 4：个人停用对自动启用项无效，在读停用记录的地方剔除

- **选定**：不删除用户的停用记录。
  - 技能：`UserSkillsService.records` 把 `auto_enabled` 的行一律视为启用。
  - 工具：`UserToolAvailabilityService.disabled_ids` 和 `is_enabled_sync` 剔除当前租户自动启用的工具（按 `tool_key` 匹配）。
- **备选**：管理员设为自动启用时，批量删除所有用户对它的停用记录。这是一次对已有行的「读后写」数据操作，而且改回用户自选后，用户原来的选择无法恢复。
- **原因**：读时剔除不改数据，切换可以来回进行。工具执行器在初始化时会检查个人停用（`tool/domain/services/executor.py:347`，应用类型为 `daily_chat` / `linsight` / `dsh_desktop`），所以剔除必须放在 `UserToolAvailabilityService` 这一层，否则补进去的工具会在初始化时报「已对此账号关闭」。
- **何时推翻**：如果停用记录以后要支持「管理员强制关闭」之类的第三方写入，读时剔除的逻辑会变复杂，届时改为写时处理。
- **按 `tool_key` 匹配**：子租户继承根租户配置时，配置里的工具 id 属于根租户，要经过 `_aproject_tools_for_current_tenant` 按 `tool_key` 投影成本租户的 id。执行器是同步代码，拿到的是本租户的工具行，用 `tool_key` 匹配可以省掉投影。

### 决策 5：直接回答总是挂载全部可用技能；技能挂载不再写会话工作区的 MinIO

- **选定（2026-11-20 用户确认）**：
  - `DirectRunner._mount_skills`（`direct_run.py:1109`）去掉「`ctx.skills` 为空就不挂载」的分支，与深度研究一致：总是挂载该用户的全部可用技能（含自动启用项），`selected` 只传用户自己选的，作为标注（AC-16）。
  - 技能挂载改为只写本地：`_copy_one` 不再调用 `WorkspaceBackend.upload_files`（逐文件写本地缓存 + 同步 PUT 到 `workspace/{会话}/skills/...`），改为把技能包从本节点的技能缓存（按 content_hash 缓存，`SkillStore.materialize`）**复制**到 `file_dir/skills/<name>/`。会话里只记快照（name、skill_id、owner、content_hash）。每次挂载都按快照把全部条目复制到本地：既包括这次新增的技能，也包括快照里已有的技能，因为同一会话的下一轮从空的 `file_dir` 开始（linsight AGENTS.md）。
  - `WorkspaceBackend` 对 `skills/` 路径单独处理：`read` 先读本地，本地没有时按快照从技能存储取，不访问会话工作区；`ls` / `glob` / `grep` 的 `skills/` 部分按快照列出（`SkillStore.list_files`），与 MinIO 的列表合并。原因是工作区的 `ls` 以 MinIO 为准，不处理的话模型 `ls /skills` 会是空的。
  - **不用硬链接**：硬链接与节点缓存共用 inode。代码执行器里的代码如果原地改写 `skills/` 下的文件，会改坏这个节点上所有会话共用的缓存。114 的执行器以 root 运行，只读权限拦不住。复制比硬链接多约 60 ms（§7.1），换来会话之间的隔离。
- **备选**：
  - A. 用户没选时只挂载自动启用项（本文初稿）。直接回答和深度研究的行为不一致，用户被否决。
  - B. 按需拷贝：只预先放 SKILL.md，其余文件在第一次读到时再取。去掉 MinIO 写入以后，挂载只剩本地硬链接，按需拷贝省不下多少时间。而且有两个约束：技能列表由 `SkillsMiddleware` 扫描本地 `file_dir` 生成；代码执行器直接读本地目录，执行代码前还要补落盘。不做。
- **原因**：耗时主要在逐文件同步写 MinIO（`workspace_backend.py:1338` 的 `upload_files` 逐文件 `_minio_put_sync`）。技能包本身已经是对象存储里内容寻址、不可变的文件，工作区的 `skills/` 也是只读的（`_skills_readonly_error`），再复制一份到会话工作区，唯一用途是换节点续跑能取回，而按快照从技能存储同样能取回。
- **影响范围**：直接回答和深度研究共用 `materialize_session_skills`，两边都受益。深度研究已有的会话快照（`skill_snapshot`）语义不变。
- **沙箱 runner 部署的遗留开销**：配置了 `sandbox_conf.endpoints` 的部署，代码执行器每次执行都会把 `file_dir` 下的全部文件做 md5、把变化的文件打成 tar.gz 传给 runner（`container_executor._copy_in`）。同一个租约内只传一次，但技能包会占用 `max_copy_in_total_bytes` 的会话额度。见 §5 坑 6。
- **何时推翻**：如果技能包变成可写的（例如允许模型修改技能），就不能再从技能存储直读，要退回写入会话工作区。
- **实测**：见 §7.1。

### 决策 6：所有面向用户的列表都在后端过滤

需要过滤的入口如下，全部改后端，前端只需要处理浏览器里保存的旧选择：

| 入口 | 接口 | 过滤位置 |
|---|---|---|
| 输入框工具菜单 | `GET /workstation/config` 的 `tools` | `CapabilityCatalogService.picker_tools` 的 `configured_tools` 分支 |
| 能力中心（`/capabilities`）的工具和技能 | `GET /dsh/capabilities` | `CapabilityCatalogService.list` |
| 技能选择器 | `GET /linsight/skill/selectable` | `SkillService.get_selectable` |
| 技能中心的企业技能 | `GET /linsight/skill/center` | `personal_skill.skill_center` |

**何时推翻**：如果新增了用户端的选择入口，必须在这张表里登记并加过滤。漏掉的入口会让自动启用项重新出现。

以下列表**不过滤**，因为它们表示「运行时能用什么」，不是选择入口：`/skill/candidates`、`/skill/runtime/catalog`、桌面端 Work 模式的 `WorkCapabilitiesService`；开放 API 日常配置（AC-22）。

> 说明：能力中心（`/capabilities`，侧边栏「工具与技能」）同时列出工具和技能，并提供个人停用开关。spec 原文的 AC-10 / AC-11 没有写到它，本 design 按「所有选择入口」的定义一并过滤，并在 spec 里补 AC-23（工具的个人停用对自动启用无效）。见修订历史。

### 决策 7：管理端交互

**已选工具行（工作台配置 → 可用工具）**

右上角的「是否默认勾选」改成「使用方式」；每行的复选框换成 `@bisheng/ui` 的描边 `Select`，尺寸 small，宽 112px，接入 `useSelectLabels()`。

```
已选工具                                    使用方式
┌──────────────────────────────────────────────────────┐
│ ≡ 联网搜索                     [默认勾选     ▾]   ✕ │
│ ≡ 代码执行器                   [自动启用     ▾]   ✕ │
└──────────────────────────────────────────────────────┘
          面板选项（每项带一行说明）：
          用户自选   出现在工具菜单，默认不勾选
          默认勾选   新会话预先勾选，用户可取消
          自动启用   不在用户端展示，每次对话自动生效
```

- **为什么用 Select，不用单选框或分段控制器**：设计规范《组件-Select选择器》§1 规定选项 ≤5 个且版面放得下时用单选框或分段控制器。已选工具面板只占页面宽度的 1/3（1440 宽屏下约 430px），工具名最多占 240px，三个单选项放不下；而且这里的设置要点「保存」后才生效，不适用分段控制器（即时生效）。选择器面板里的选项可以带一行说明，「自动启用」的含义直接写在选项里，不需要另加帮助图标。
- 点击 Select 时阻止事件冒泡，不触发行点击（行点击会滚动右侧列表），也不触发拖拽。
- 「自动启用」不加额外的图标或颜色。行里的值本身已经说明状态，不增加装饰。

**技能管理表格**

在「状态」列之后新增一列「自动启用」，单元格用 `Switch`，写法与「状态」列相同：乐观更新，失败时回滚并 `showApiError`，成功时 toast。

- 列头加 `Tooltip`，内容为「开启后不在用户端展示，每次对话自动加载」。
- 技能停用时，开关置灰并保留当前值。悬停提示「启用技能后才能设置」。
- 单元格阻止冒泡，不打开详情抽屉。
- 用 Switch 而不用 Select：这一列只有两种状态，而且和「状态」列一样即时生效，与表格里已有的交互一致。列名用术语「自动启用」，与工具的选项同名。

**用户端**：不新增界面。只处理浏览器里保存的旧选择（§5 坑 3）。

## 4. 系统现状（接手必读）

### 4.1 数据流

```
工具
  平台配置页 ──PUT workstation/config──▶ 租户配置 JSON tools[]{id, default_checked, auto_enabled, children[]}
  用户端 ◀── GET workstation/config ── picker_tools（按 use 权限过滤，【新】去掉 auto_enabled 组）
  用户端发送 ──POST workstation/chat/completions──▶ chat.py 入口
      【新】with_auto_enabled_tools(data, user)：取配置 → use 权限过滤 → 自动启用组的 children 按 id 去重并入 data.tools
      → stream_chat_completion → unified_send → 收件箱 → 直接回答 / 深度研究 / 接力运行
  工具初始化 → executor 检查个人停用 →【新】自动启用的 tool_key 视为启用

技能
  技能管理 ──PATCH skill/{name}/auto-enabled──▶ linsight_skill.auto_enabled
  选择入口（selectable / center / dsh capabilities）【新】去掉 auto_enabled
  UserSkillsService.records【新】auto_enabled 的行忽略个人停用
  深度研究：_materialize_candidates 拷贝全部候选（已包含自动启用项）
  直接回答：_mount_skills【新】总是挂载全部候选（同深度研究）
  挂载方式【新】本节点技能缓存 → 复制到 file_dir/skills/，不写会话工作区 MinIO；skills/ 的读和列表按快照取技能存储
```

### 4.2 关键数据结构 / 字段约定

- `ToolConfig.auto_enabled: bool = False`（`api/v1/schemas.py:458`）。以下 dict 重组函数会丢掉未知字段，都要透传这个字段：`_group_tool_rows`、`_ahydrate_tools_from_source_tenant`、`_aproject_tools_for_current_tenant`（按组记录 `default_checked` 的地方同样记录 `auto_enabled`）、`parse_config` 里的旧数据迁移分支、`_abuild_default_daily_config`（显式写 False）。
- `LinsightSkillBase.auto_enabled: bool`，列 `auto_enabled Integer NOT NULL DEFAULT 0`，迁移 revision `f005_linsight_skill_auto_enabled`，`down_revision` 取 `alembic heads` 的输出。
- `SkillBrief`（管理列表）新增 `auto_enabled`。

### 4.3 关键模块职责

| 模块 | 新增职责 |
|---|---|
| `WorkStationService.awith_auto_enabled_tools(data, login_user)` | 补入工具，按子工具 id 去重 |
| `WorkStationService.auto_enabled_tool_keys()`（同步、异步各一个） | 读当前租户（含继承）的配置，返回自动启用组的子工具 `tool_key` 集合 |
| `UserToolAvailabilityService` | 剔除自动启用的 `tool_key` |
| `UserSkillsService.records` | 自动启用的行视为启用 |
| `DirectRunner._mount_skills` | 总是挂载全部候选 |
| `skill_provisioning._copy_one` / `WorkspaceBackend` 的 `skills/` 读取和列表 | 本地复制挂载；`skills/` 的读、ls、glob、grep 按快照走技能存储 |
| `ToolSelector.tsx` | 「使用方式」Select |
| `SkillManagement.tsx` | 「自动启用」列 |

## 5. 已知坑 / 反直觉事实

1. **配置重组函数会丢字段**。工具配置在读取时会被 3–4 个函数拆开重组成新 dict，只保留白名单字段。漏掉任何一处，子租户（继承配置）读到的 `auto_enabled` 就是 False，工具重新出现在用户端，而根租户看起来一切正常。测试必须覆盖继承场景。
2. **工具 id 按租户投影**。继承配置里的子工具 id 属于根租户，按 id 比较会在子租户失效。补入函数要用投影后的配置（`get_daily_chat_config` 已经做了投影），执行器的剔除用 `tool_key`。
3. **浏览器里保存的旧选择**。客户端按账号保存工具选择（`agentToolDefaults.ts` 的 `applyToolDefaults`），代码执行器曾作为 `auto` 项写进去。工具改为自动启用后，`availableTools` 里没有它了。实现时要核对客户端是否已经按 `availableTools` 求交集；如果没有，旧选择会显示一个点不掉的标签。后端按 id 去重，所以不会重复挂载。技能选择（`SkillSelector`）同样处理。
4. **超管验证会掩盖权限问题**。验证 AC-17 要用非管理员账号（backend AGENTS.md）。
6. **沙箱 runner 的 copy-in 额度会被技能包占用**。总是挂载全部技能以后，配置了 runner 的部署每个会话都会把全部技能包（114 上是 30.7 MB）计入 copy-in 总量。默认上限 `max_copy_in_total_bytes` 是 512 MB，技能包约占 6%，默认配置下不会挤掉用户文件。如果某个部署调低了这个上限，超出部分会被跳过，可能包括用户上传的文件。深度研究今天已经是这样。本期不改，只记录；如果要改，就在 `_copy_in` 里跳过 `skills/` 下模型没读过 SKILL.md 的技能。
5. **配置缓存**。配置写入后最长 100 秒内读到的可能还是旧值（Redis TTL）。验证时不要在这个时间窗内判断「没生效」。

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

- `GET /workstation/config`（用户端）：`tools[]` 不再包含自动启用的组。字段不变。
- 平台的工作台配置读写：`tools[].auto_enabled` 新字段，缺省 False。
- `PATCH /api/v1/linsight/skill/{name}/auto-enabled`，请求体 `{auto_enabled: bool}`，租户管理员权限，返回 `{ok: true}`；技能不存在时返回已有错误 `SkillNotFoundError`。路由里不含 `config` 字样。
- 管理端技能列表 `GET /linsight/skill` 每项新增 `auto_enabled`。

### 6.2 我依赖别人的（Incoming）

- F004：`run_send`、`direct_run._mount_skills`、收件箱的消息结构。F004 合入 beta2 前，本分支跟随 F004 rebase。风险点：F004 如果把补入之后的 `data.tools` 换成别的字段，或者把收件箱消息改为只存用户勾选，接力运行就会丢失补入的工具（AC-19）。
- F035 / F048：技能的 `visible` 权限、个人停用表；工具的 `use` 权限、个人停用表。

## 7. 测试与可观测

- 后端单测放在 `test/workstation/`、`test/linsight/`：配置字段透传（含继承投影）、互斥 validator、补入去重与权限过滤、个人停用剔除（工具、技能）、四个列表的过滤、`_mount_skills` 无选择时也挂载、挂载不产生 MinIO 写入、换节点（本地目录为空）时按快照重建与读取、`selected` 不含自动启用项、迁移单 head。
- 前端：平台两处组件测试；客户端旧选择的过滤测试。
- 日志：补入时打一条 info，内容为补入的 tool_key 列表和去重数；直接回答挂载时沿用现有的 provisioning 日志（已打印 candidates 和 materialized）。
- 实测：见 §7.1；非管理员账号的端到端验证。
- 手动验证：环境地址和账号见 `.claude/docs/dev-environments.md`（114 个人开发机跑 beta2，部署用 `bash /opt/bisheng-ops/deploy.sh`）。步骤：管理端把代码执行器设为自动启用并保存 → 用非管理员账号打开用户端，确认工具菜单和能力中心都没有它 → 发一条「用 python 算 2 的 100 次方」，确认执行过程里出现代码执行器的调用。

### 7.1 实测记录

2026-11-20，114（代码 c93a27ccb = F004 分支），admin 账号，测量脚本对每个候选技能调用今天的 `_copy_one`，写入一次性前缀 `workspace/f005-measure-*`，测完已删除 1992 个对象。

| 项 | 数值 |
|---|---|
| 候选技能数 | 17 |
| 文件数 / 总字节 | 664 个 / 30.7 MB（最大的 gongwen-draft 45 个文件 22 MB；bisheng-pptx 246 个文件 1.9 MB） |
| 本节点技能缓存读取（已预热） | 0.11 s |
| 今天的挂载（写本地 + 逐文件 PUT MinIO），3 轮 | 3.71 / 3.80 / 4.47 s |
| 改为从技能缓存硬链接，3 轮 | 0.014 / 0.021 / 0.026 s |
| 改为从技能缓存复制（选定），3 轮（第二次测量，同环境） | 0.076 / 0.094 / 0.072 s；同轮的今天方式为 3.57 / 3.78 / 3.59 s |

结论：今天的方式每次直接回答要多 4 秒左右，耗时与文件数成正比；41 个技能的租户会更慢。改为复制后降到 100 ms 以内，所以「总是挂载全部可用技能」可以接受。

执行器：114 没有配置沙箱 runner（`BS_SANDBOX_CONF__ENDPOINTS` 为空），用的是本地执行器，读本地目录，不受影响。

**实现后复测**（2026-11-20，114，代码 c34ba9d0d）：直接回答的 `BS_METRIC domain=agent_run` 中 `prep_ms`（整个准备阶段，含技能挂载）为 0.57–1.1 s，admin 挂载 17 个技能；重启后第一次（节点缓存冷）为 2.3 s。改动前单是技能挂载就要 3.6–4.5 s。

## 8. 后续改进 / 不打算做的事

- 桌面端 Work 模式的技能、工具展示不在本期范围；它读的是运行时列表，自动启用项照常出现。

## 修订历史

| 日期 | 内容 |
|---|---|
| 2026-11-20 | 决策 5 细化：挂载用复制不用硬链接（共用 inode 会让执行器代码改坏节点缓存）；`skills/` 的 ls/glob/grep 按快照列出；每次挂载重新复制快照里的全部条目。复制耗时实测 72–94 ms |
| 2026-11-20 | 决策 5 改为直接回答总是挂载全部可用技能，技能挂载去掉 MinIO 写入，不做按需拷贝（用户确认）。 |
| 2026-11-20 | 初稿。取证时发现能力中心（`/capabilities`）也是选择入口，并且工具也有个人停用；spec 补 AC-23，AC-10 / AC-11 的入口列表补上能力中心（待用户在 design 确认时一并确认） |
