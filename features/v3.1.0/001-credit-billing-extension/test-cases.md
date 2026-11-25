# 积分扣费扩展测试用例（测试工程师参考）

## 依据与范围

- 已确认规格：[spec.md](./spec.md)（2026-11-24 确认，覆盖 `AC-01` ~ `AC-32`）。
- 设计复查：[design.md](./design.md)（2026-11-25 确认，已将接口路径、权限入口、错误码渲染、数据表与观察方法同步至下方用例；无需求与设计冲突）。
- 目标版本与构建：`v3.1.0` / 待实现（规划分支 `feat/v3.1.0/001-credit-billing-extension`）。
- 其他依据：《积分扣费扩展-需求文档与界面原型 v1.0》（2026-11-19）、《积分扣费扩展-技术实现与评审文档 v1.0》（2026-11-24 评审定稿）。
- 代码核对：`feat/3.1.0@79c40fdc4a`；已核实 `dsh/domain/services/chat_credits.py`、`tool/domain/services/executor.py`、`open_api/domain/services/model_gateway_service.py`、`open_api/domain/services/model_range_policy.py`、`linsight/domain/task_exec.py`、`worker/workflow/tasks.py`、`platform/src/pages/BuildPage/tools/ToolItem.tsx`、`client/src/pages/appChat/useWebsocket.ts`；新增表/接口/前端弹框均为规格与设计推导，待实现后复验。
- 覆盖范围：覆盖工具设价管理与权限、工具换算与实时扣费/拦截、任务模式单周期豁免、助手/工作流/调试/免登录计费、开放 API 免计费与托管应用 OBO 计费、账本对账恢复、全局总开关与双库兼容；不含员工端工具价格展示及新统计报表（本期排除）。

## 环境、账号与测试数据

| 代号 | 角色或数据 | 准备方法 | 确认方式或待确认项 |
| --- | --- | --- | --- |
| `U-SUPER` | 总公司超级管理员 | 使用总公司（Root）超管账号登录管理后台 | 右上管理视图可切换总公司与子公司 |
| `U-SUB-ADMIN` | 子公司管理员 | 在子公司 `T-SUB-NEW` 具备租户管理员角色 | 可管理子公司积分设置与工具价格，不可改总公司数据 |
| `U-EMP` | 总公司普通员工（限额） | 总公司普通员工，在「积分规则」将其月度额度设为可验证数值（如 `10` 或 `1` 积分） | 工作台侧边栏可看到剩余积分；无后台改价权限 |
| `U-SUB-EMP` | 子公司普通员工 | 子公司 `T-SUB-NEW` 普通员工，月度额度设为 `10` 积分 | 登录后仅归属子公司租户 |
| `U-GUEST-OP` | 免登录本租户运行身份 | 在测试助手/工作流的「允许免登录访问」中选定本租户普通员工账号（可调整其月度额度为 `1` 或 `0`） | 访客打开分享链接后对话记录归属该账号 |
| `U-APP-OWNER` | 托管应用负责人 | 已上线托管应用 `APP-HOSTED` 的所有者账号（限额可调） | 托管应用能力声明已绑定至少 1 个收费聊天模型 |
| `T-ROOT-CFG` | 总公司积分设置 | 计价币种 `CNY`，积分单价 `0.01` 元，汇率 `6.72` | 后台「积分设置」页确认已保存 |
| `T-SUB-NEW` / `T-SUB-OLD` | 新建子公司 / 升级前存量子公司 | `T-SUB-OLD` 为功能上线前已存在的子公司；`T-SUB-NEW` 为总公司设价后新建并初始化内置工具的子公司 | 切管理视图确认内置工具列表存在 |
| `APP-ASST` / `APP-WF` | 含收费模型与收费工具的助手 / 工作流 | 均配置 1 个不在 `U-EMP`「用户可选模型」列表内的收费模型；`APP-WF` 包含「大模型节点 → 收费工具节点 → 大模型节点」 | 发布上线并开启构建页调试与免登录分享测试用 |
| `KEY-OPENAPI` | 开放 API 凭证（服务账号 & 代员工） | 在开放平台分别创建服务账号 Key 与代 `U-EMP` 操作的凭证 | 具备调助手、工作流、深度研究、模型网关权限 |
| `CFG-SWITCH` | 全局「积分与计费总开关」 | 后端配置文件 `credit_billing.enabled`（默认 `true`，测试关闭时置 `false` 重启服务） | 请求 `GET /api/v1/dsh/browser-config` 核对 `credit_billing_enabled` |

## 具体测试用例

| ID | 功能点 | 优先级 | 前置条件 | 步骤 | 预期结果 | 测试结果 | 结果说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-CBE-001 | 工具默认 0 价免费与不记账 | P0 | `CFG-SWITCH=true`，`U-EMP` 剩余额度为 `0`；内置工具「时间（get_current_time）」未设价（默认 0） | 1. 使用 `U-SUPER` 在后台「构建 → 工具与技能 → 内置工具」查看「时间」行价格。<br>2. 使用 `U-EMP` 在日常对话或工具试运行中触发该免费工具。<br>3. 查询 `dsh_tool_call` 与 `U-EMP` 本月已用积分。 | 1. 列表行显示「免费」。<br>2. 即使 `U-EMP` 余额为 0，免费工具仍正常执行成功，不报 `26121`。<br>3. `dsh_tool_call` 无新增记录，`U-EMP` 本月已用积分不变。 | 待执行 | — |
| TC-CBE-002 | 全工具统一设价弹框与参数校验（含联网搜索/网页读取） | P0 | `CFG-SWITCH=true`，`T-ROOT-CFG` 已配置；`U-SUPER` 登录管理后台 | 1. 分别展开「内置工具 → 联网搜索」「内置工具 → 网页读取」「内置工具 → 天眼查」「API 工具」「MCP 工具」，查看二级工具行。<br>2. 点击「联网搜索」的「设置价格」按钮，在弹框中依次输入非法值（次数 `0` 或 `1000001`、负数价格、7 位小数价格）。<br>3. 打开「联网搜索」原有的「编辑内置工具」引擎配置弹框并切换引擎。 | 1. 三个页签所有二级工具行均统一展示价格与「设置价格」按钮。<br>2. 弹框为统一设价弹框（默认「按金额」、次数默认 `1`），非法输入标红且「保存」不可点；清空价格视为 `0`。<br>3. 原引擎配置弹框无价格表单；切换引擎后列表显示的联网搜索价格不变（全引擎共用）。 | 待执行 | — |
| TC-CBE-003 | 工具设价权限与乐观锁并发冲突 | P0 | `CFG-SWITCH=true`；准备 `U-EMP`（非管理员）与两个 `U-SUPER` 浏览器会话 | 1. 使用 `U-EMP` 查看工具列表，并直接调用 `PUT /api/v1/dsh/admin/tool-pricing/{tool_id}` 改价。<br>2. 两个 `U-SUPER` 会话同时打开同一二级工具的「设置价格」弹框，会话 1 先保存成功，会话 2 随后点击保存。 | 1. `U-EMP` 列表看不到「设置价格」按钮；直接调接口被后端鉴权拒绝。<br>2. 会话 1 保存成功提示「已保存」；会话 2 收到错误码 `26130` 与「价格已被他人修改，请刷新后重试」，不覆盖会话 1 的价格。 | 待执行 | — |
| TC-CBE-004 | 按积分设价扣费与积分单价隔离 | P0 | `CFG-SWITCH=true`，`T-ROOT-CFG`；`U-EMP` 剩余 `10` 积分 | 1. `U-SUPER` 给天眼查「企业股东」按积分设 `1 次 · 2 积分`。<br>2. `U-EMP` 触发该工具调用 1 次。<br>3. `U-SUPER` 将总公司积分单价从 `0.01` 元改为 `0.02` 元后，`U-EMP` 再次调用 1 次。 | 1. 列表显示 `2 积分 / 次`。<br>2. 第 1 次调用扣 `2` 积分，`dsh_tool_call` 记录完整快照（`call_count=1`、`billed_tokens=2000000`、`cost_micro=NULL`）。<br>3. 改积分单价后第 2 次仍固定扣 `2` 积分。 | 待执行 | — |
| TC-CBE-005 | 按金额（人民币/美元）与自定义次数换算 | P0 | `CFG-SWITCH=true`，`T-ROOT-CFG`（`0.01` 元/积分，汇率 `6.72`）；`U-EMP` 剩余 `20` 积分 | 1. 给「联网搜索」按金额设 `1000 次 · ¥5`，`U-EMP` 调用 1 次。<br>2. 将「联网搜索」改为按金额 `1000 次 · $8`，`U-EMP` 调用 1 次。<br>3. 将租户积分单价改为 `0.02` 元，`U-EMP` 再调用 1 次。 | 1. 第 1 次扣 `0.5` 积分（`500,000` 微积分）。<br>2. 第 2 次按 `8 × 6.72 ÷ 1000 ÷ 0.01` 向上取整扣 `5.376` 积分（`5,376,000` 微积分）。<br>3. 改单价后第 3 次按新单价折半扣 `2.688` 积分。 | 待执行 | — |
| TC-CBE-006 | 工具执行中改价快照冻结与失败/未执行边界 | P0 | `CFG-SWITCH=true`；准备一个耗时工具或可模拟失败/超时/缺 Key 的已设价工具 | 1. 发起工具调用并进入实际执行，在执行完成前管理员修改该工具价格。<br>2. 分别触发工具执行失败、执行超时，核查扣费与 `dsh_tool_call.result`。<br>3. 清除该工具 API Key 使其在初始化/前置校验阶段失败，再次触发。 | 1. 进行中的调用按开始时冻结的旧价格结算；改价后的新调用按新价格结算。<br>2. 执行失败（含任务模式下异常转软 JSON）与超时均照常扣费，且 `dsh_tool_call.result` 准确记录为 `failed` / `timeout`。<br>3. 缺 Key 前置拦截不执行，不扣费、不写 `dsh_tool_call`。 | 待执行 | — |
| TC-CBE-007 | 非任务模式收费工具实时额度拦截与当次轻微透支 | P0 | `CFG-SWITCH=true`；天眼查「企业股东」设为 `1 次 · 2 积分`；`U-EMP` 剩余 `0.2` 积分 | 1. `U-EMP` 在日常对话或工具试运行中第 1 次调用「企业股东」。<br>2. 第 1 次完成后（此时 `U-EMP` 已超额 `1.8` 积分），第 2 次再调用「企业股东」或发起新模型对话。 | 1. 第 1 次开始前满足 `used < limit`，放行执行并扣 `2` 积分（允许当次轻微透支）。<br>2. 第 2 次调用前因 `used >= limit` 直接拦截返回 `26121`，不执行工具且不扣费，前端提示「本月积分已用完」。 | 待执行 | — |
| TC-CBE-008 | API / MCP 工具刷新与删除联动清价 | P1 | `CFG-SWITCH=true`；已配置包含 2 个二级工具的 API 工具组与 MCP 工具组，且均已设价 | 1. 修改 API OpenAPI 定义或刷新 MCP 工具列表：保留工具 A、删除工具 B、新增工具 C。<br>2. 删除整个 API 工具组。 | 1. 工具 A 保留原价格，工具 C 价格为 `0`，工具 B 的 `dsh_tool_pricing` 记录被清理。<br>2. 删除工具组后组内全部价格记录同步清理。 | 待执行 | — |
| TC-CBE-009 | 多租户内置工具复制与独立计价 | P0 | `CFG-SWITCH=true`；总公司已给「联网搜索」设价 `1000 次 · ¥5`；`T-SUB-OLD` 已存在 | 1. 新建子公司 `T-SUB-NEW` 并完成内置工具初始化，对比 `T-SUB-NEW` 与 `T-SUB-OLD` 的「联网搜索」价格。<br>2. `U-SUPER` 修改总公司价格，再由 `U-SUB-ADMIN` 修改 `T-SUB-NEW` 价格与积分单价。<br>3. `U-SUB-EMP` 调用「联网搜索」。 | 1. `T-SUB-NEW` 复制了总公司当时的价格；`T-SUB-OLD` 保持为 `0`。<br>2. 总/子改价互不同步。<br>3. `U-SUB-EMP` 严格按 `T-SUB-NEW` 自己的工具价格与积分单价扣费。 | 待执行 | — |
| TC-CBE-010 | 任务模式（深度研究）单周期豁免与 `ask_user` 恢复 | P0 | `CFG-SWITCH=true`；`U-EMP` 剩余 `0.5` 积分（足够启动但跑完会超额）；任务内含收费模型、收费工具及 `ask_user` 交互 | 1. `U-EMP` 发起深度研究新任务。<br>2. 任务中途耗尽剩余 `0.5` 积分后触发收费工具与 `ask_user` 暂停，用户提交回答恢复执行直至任务结束。<br>3. 任务结束后，`U-EMP` 发起下一次新任务或追问轮次。 | 1. 启动前额度检查通过，任务开始运行。<br>2. 任务生命周期内（含中途工具调用与 `ask_user` 恢复）均实时入账扣分且**不拦截不中断**，任务完整跑完。<br>3. 下一次发起新任务/追问轮次时在启动前被拦截并返回 `26121`。 | 待执行 | — |
| TC-CBE-011 | 工作台使用助手计费、豁免可选模型与用完卡片 | P0 | `CFG-SWITCH=true`；`APP-ASST` 使用不在 `U-EMP`「用户可选模型」内的收费模型 | 1. `U-EMP` 剩余 `10` 积分时在工作台向 `APP-ASST` 发送消息。<br>2. 将 `U-EMP` 额度调至已用完后，再次发送消息。 | 1. 对话正常完成，不报「模型不可用」，按该模型真实单价扣 `U-EMP` 积分，且 `dsh_model_call` 记录 `source_type` 与 `source_id`。<br>2. 余额用完后被 `26121` 拦截、不回答，应用对话页直接渲染 `ChatErrorCard`（「本月积分已用完」）。 | 待执行 | — |
| TC-CBE-012 | 工作流节点级实时扣费、中途拦截与卡片展示 | P0 | `CFG-SWITCH=true`；`APP-WF` 包含「大模型节点 1 → 收费工具节点（2 积分）→ 大模型节点 2」；`U-EMP` 剩余 `1` 积分 | 1. `U-EMP` 在工作台启动 `APP-WF`。<br>2. 观察节点 1、工具节点、节点 2 的执行与扣费情况，以及工作台界面呈现。<br>3. 在 `U-EMP` 余额已为 `0` 时再次点击运行 `APP-WF`。 | 1. 节点 1 与收费工具节点实时校验并扣费；当余额在工具节点扣至超额后，大模型节点 2 执行前立即被 `26121` 拦截中止，工作流置为失败，已发生节点的扣费保留。<br>2. 工作台运行消息末尾直接渲染 `ChatErrorCard`（不只弹 toast）。<br>3. 余额为 `0` 时再次点击运行立即拦截并渲染 `ChatErrorCard`。 | 待执行 | — |
| TC-CBE-013 | 构建页调试与免登录分享计费与隔离 | P0 | `CFG-SWITCH=true`；`APP-ASST` / `APP-WF` 开启免登录并指定本租户 `U-GUEST-OP` | 1. `U-EMP` 在管理后台「构建」页调试他人搭建的 `APP-ASST` 与 `APP-WF`。<br>2. 匿名访客打开免登录分享链接使用 `APP-ASST` 与 `APP-WF`。<br>3. 将 `U-GUEST-OP` 额度调至用完后，访客再次访问。 | 1. 调试消耗（模型与工具）计入当前调试者 `U-EMP`，用完即拦。<br>2. 免登录调用计入本租户 `U-GUEST-OP`（`dsh_model_call` / `dsh_tool_call` 记录对应来源）。<br>3. `U-GUEST-OP` 额度用完后访客被 `26121` 拦截，免登录页渲染 `ChatErrorCard`。 | 待执行 | — |
| TC-CBE-014 | 开放 API 全场景免计费（含深度研究行为反转） | P0 | `CFG-SWITCH=true`；`U-EMP` 本月积分已用完（`remaining = 0`） | 1. 使用 `KEY-OPENAPI`（服务账号模式与代 `U-EMP` 模式）分别调用助手、工作流、深度研究（任务模式）与模型网关（含触发收费工具）。<br>2. 检查响应结果、`U-EMP` 本月已用及 `dsh_model_call` / `dsh_tool_call`。 | 1. 全部开放 API 调用正常执行成功，不被 `26121` 拦截。<br>2. `U-EMP` 本月已用积分无变化，不写入积分账本与明细表（开放 API 调深度研究不再扣员工分）。 | 待执行 | — |
| TC-CBE-015 | 托管应用 OBO 令牌扣访问人、无令牌/预览扣负责人与过期拒绝 | P0 | `CFG-SWITCH=true`；`APP-HOSTED` 归属 `U-APP-OWNER`；`U-EMP` 为访问人 | 1. `APP-HOSTED` 携带 `U-EMP` 的有效 `X-BiSheng-Access-Token` 调 `/api/v2/model/v1/chat/completions`（余额充足与余额用完各测一次）。<br>2. 不带令牌调模型网关，以及审批人发起上线审批「预览试用」调模型网关。<br>3. 携带过期或伪造的 `X-BiSheng-Access-Token` 调模型网关。 | 1. 带有效令牌扣 `U-EMP` 积分；`U-EMP` 用完时返回 HTTP 429、`error.type="rate_limit_error"`、`error.code="credit_exhausted"`、`error.bisheng_code=26121`。<br>2. 无令牌与审批预览试用均扣 `U-APP-OWNER` 积分（不扣审批人）。<br>3. 过期/伪造令牌维持报错拒绝（错误码 `26504`），不降级扣负责人。 | 待执行 | — |
| TC-CBE-016 | 统一账本守恒校验与故障恢复一致性 | P0 | `CFG-SWITCH=true`；`U-EMP` 当月同时产生了模型扣费与收费工具扣费 | 1. 查询 `U-EMP` 本月实时余额，并由管理员修改其配额规则（触发 `policy.lua` `install`）。<br>2. 清空该用户 Redis 账本键模拟 Redis 重建，再次发起模型调用与余额查询。<br>3. 核对 `dsh_monthly_usage` 的 `usage_type`（`MODEL`/`TOOL`）与重建后余额。 | 1. 查余额与改配额均成功，不触发 `incomplete_model_ledger`。<br>2. 自动恢复合并读取 `dsh_model_call` 与 `dsh_tool_call` 重建 `:models`、`:tools` 与 `:month.used`，恢复前后余额完全一致。<br>3. `dsh_monthly_usage` 按 `usage_type` 分别记录模型与工具月度汇总，历史仅含模型的月份兼容正常。 | 待执行 | — |
| TC-CBE-017 | 全局「积分与计费总开关」关闭与重新开启 | P0 | 将 `CFG-SWITCH`（`credit_billing.enabled`）置 `false` 重启；`U-EMP` 此前额度已用完（`remaining = 0`） | 1. 检查 `GET /api/v1/dsh/browser-config`、管理后台页面、网页工作台侧边栏与桌面客户端登录/对话。<br>2. `U-EMP` 通过网页端、桌面端、助手、工作流、收费工具与托管应用发起调用。<br>3. 将 `credit_billing.enabled` 改回 `true` 重启，发起新调用并核对账本。 | 1. 桌面端仍可正常登录与调用平台可见模型；`browser-config` 返回 `credit_billing_enabled=false`；前端隐藏余额、倍率、后台积分设置/规则/用量与工具价格列/「设置价格」按钮。<br>2. 所有场景均不扣费、不拦截 `26121`，保留平台模型可见范围。<br>3. 重开后从开启时刻起恢复扣费，关闭期间调用不追溯补扣，存量账本连续可用。 | 待执行 | — |
| TC-CBE-018 | 存量配置兼容、旧版桌面客户端与双库迁移校验 | P1 | 准备含旧 `dsh.enabled` 字段的 YAML 配置、旧版桌面客户端、MySQL 与 DM8（回归环境）数据库 | 1. 使用保留旧 `dsh.enabled` 字段的配置启动新版本服务端。<br>2. 在 MySQL 与 DM8 上执行 Alembic 升级迁移（含 `dsh_monthly_usage` 唯一键重建）。<br>3. 使用旧版桌面客户端连接新服务端发起普通对话。 | 1. 服务端平滑启动，不因旧字段报配置校验错误。<br>2. MySQL 与 DM8 迁移均成功，新表租户过滤生效。<br>3. 旧版桌面客户端原有功能不受影响。 | 待执行 | — |

## 用例依据与待确认项

| 用例 ID | 需求依据 | 设计或代码依据 | 待确认项或差异 |
| --- | --- | --- | --- |
| TC-CBE-001 | AC-01 | `design.md §4.1`、`tool/domain/services/executor.py`（拟实现） | 无 |
| TC-CBE-002 | AC-02, AC-03, AC-04 | `design.md §3 决策 3`、`platform/src/pages/BuildPage/tools/ToolItem.tsx`（拟实现） | 统一设价弹框组件路径待实现后补充 |
| TC-CBE-003 | AC-05, AC-06 | `design.md §6.1`、`dsh/api/endpoints/tool_pricing.py`（拟实现） | 无 |
| TC-CBE-004 | AC-09 | `design.md §4.1`、`dsh_tool_pricing`（拟实现） | 无 |
| TC-CBE-005 | AC-10 | `design.md §2`、`design.md §4.1`（拟实现） | 无 |
| TC-CBE-006 | AC-11, AC-12, AC-25 | `design.md §5 坑 2`、`tool/domain/services/executor.py`（拟实现） | 模拟超时与 Linsight 软错误日志核对方式待研发提供测试夹具 |
| TC-CBE-007 | AC-13 | `design.md §3 决策 2`、`check_tool_quota.lua`（拟实现） | 无 |
| TC-CBE-008 | AC-07 | `design.md §4.1`、`tool/domain/models/gpts_tools.py`（拟实现） | 无 |
| TC-CBE-009 | AC-08, AC-14 | `design.md §4.1`、`workstation_service.py:acopy_root_builtin_tools_to_tenant`（拟实现） | 无 |
| TC-CBE-010 | AC-16 | `design.md §3 决策 4`、`design.md §5 坑 3`、`linsight/domain/task_exec.py`（拟实现） | 无 |
| TC-CBE-011 | AC-17, AC-18, AC-25 | `design.md §4.1`、`dsh/domain/services/chat_credits.py`、`client/src/pages/appChat/`（拟实现） | 无 |
| TC-CBE-012 | AC-15, AC-17, AC-19 | `design.md §3 决策 4`、`design.md §5 坑 5`、`worker/workflow/tasks.py`、`useWebsocket.ts`（拟实现） | 无 |
| TC-CBE-013 | AC-20, AC-21 | `design.md §3 决策 6`、`public_endpoints/domain/services/guest_link.py`、`guest_policy.py` | 无 |
| TC-CBE-014 | AC-22 | `design.md §3 决策 5`、`design.md §5 坑 7`、`open_api/domain/services/task_mode_service.py`（拟实现） | 无 |
| TC-CBE-015 | AC-23, AC-24, AC-32 | `design.md §3 决策 5`、`model_gateway_service.py`、`model_range_policy.py`、`exception_handlers.py` | 托管应用开发文档更新路径待实现阶段确认 |
| TC-CBE-016 | AC-25, AC-26 | `design.md §3 决策 1`、`design.md §5 坑 1/4`、`dsh/domain/repositories/usage.py`（拟实现） | 无 |
| TC-CBE-017 | AC-27, AC-28, AC-29 | `design.md §3 决策 7`、`core/config/settings.py`、`dsh/api/endpoints/models.py`（拟实现） | 无 |
| TC-CBE-018 | AC-30, AC-31 | `design.md §2`、`design.md §5 坑 6`、`alembic/versions/`（拟实现） | DM8 实库迁移验证依赖中央 Linux 回归环境 |
