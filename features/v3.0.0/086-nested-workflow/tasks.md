# Tasks: 工作流嵌套工作流

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0（开发分支 `feat/SEC-3.0.0-1016`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 由已确认的 PRD §3、§4 转写；2026-10-19 用户确认 |
| design.md | ✅ 已评审 | 2026-10-19 经 `/sdd-review design` 修订后用户确认；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 2026-10-19 经 `/sdd-review tasks` 修订 |
| 实现 | 🔄 进行中 | 25 / 35 完成；Wave 4 代码与质量门已完成，T25–T31 待同事在 119 共享沙箱部署、手动验证后勾选 |

---

## 开发模式

- 任务按 Wave 组织。同一 Wave 内无依赖的任务可以并行。
- 后端先写测试任务（红），再做配对的实现任务（绿）。测试放在 `T/workflow/`。子引擎测试用最小工作流 JSON 构造，不依赖中间件。
- **测试降级**：API 层集成测试（T24）需要数据库，只能在 CI 运行，本地无法先红后绿，所以排在 API 接入任务之后。API 接入的核心判定逻辑在 `SubflowService` 中，已由 T19 单测先行覆盖。
- 前端用手动验证，环境为 119 共享沙箱，由同事部署（2026-10-20 起改定，不在 114 部署）。
- 设计论证指向 design.md 的决策编号，本文不重复。
- 并发子 agent 共用工作树时，禁止仓库级 git 写操作（`git stash`、`git checkout .`、`git reset --hard`、`git clean`）。
- 路径简写：`B/` = `src/backend/bisheng/`，`F/` = `src/frontend/`，`P/` = `src/frontend/platform/src/`，`T/` = `src/backend/test/`。
- 不涉及 Client 前端，不新增 Celery 任务：子工作流在父工作流所在的 worker 线程内运行，租户上下文沿用 worker 已设置的 ContextVar。

---

## Wave 0：基础设施（无测试配对）

- [x] **T01**：错误码
  **文件**: `B/common/errcode/flow.py`、`features/v3.0.0/release-contract.md`
  **逻辑**: 新增 10560–10565 六个错误码类，消息参数见 design §6.3。release-contract 中：「已分配模块编码」登记六个码；表 1 登记领域对象「子工作流引用关系」；表 2 新增不变量「【结束】节点返回结果开关关闭时，工作流行为与改动前一致」。动手前按 constitution C5 的命令重新扫描占用。
  **依赖**: 无

- [x] **T02**：错误码文案三语
  **文件**: `F/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
  **逻辑**: 为 10560–10565 写三语文案，参数名与 design §6.3 的 `data` 字段一致；运行生成脚本，不手改生成产物。
  **验证**: `pnpm check-i18n` 通过。
  **依赖**: T01

- [x] **T03**：引用表模型与租户登记
  **文件**: `B/workflow/domain/models/__init__.py`、`B/workflow/domain/models/subflow_ref.py`、`B/core/database/tenant_filter.py`
  **逻辑**: SQLModel `table=True`，列见 design §4.2，带 `tenant_id`，只用通用列类型（C2）；新表由 `create_all` 建，不写 alembic 迁移。回滚：新表独立，旧代码不读它，回滚代码后留存的空表无影响，必要时手工 `DROP`。把模块路径 `bisheng.workflow.domain.models.subflow_ref` 登记进 `_TENANT_AWARE_MODEL_MODULES`（design 坑 9）。
  **验证**: `T/workflow/test_subflow_ref_model.py` 断言新表在租户过滤的表集合中。
  **依赖**: 无

- [x] **T04**：引用表 Repository
  **文件**: `B/workflow/domain/repositories/interfaces/subflow_ref_repository.py`、`B/workflow/domain/repositories/implementations/subflow_ref_repository_impl.py`（含两级 `__init__.py`）
  **逻辑**: 异步方法：`replace_for_parent(parent_flow_id, child_flow_ids)`、`delete_for_parent(parent_flow_id)`、`list_referrer_ids(child_flow_id) -> list[parent_flow_id]`（见偏差记录）。结构参照 `B/knowledge/domain/repositories/`。不读 `Flow` 表——`Flow` 的读取沿用现有 `FlowDao`（design §4.3）。
  **依赖**: T03

- [x] **T05**：节点类型注册与空骨架
  **文件**: `B/workflow/common/node.py`、`B/workflow/nodes/node_manage.py`、`B/workflow/nodes/subflow/__init__.py`、`B/workflow/nodes/subflow/subflow.py`
  **逻辑**: `NodeType.SUBFLOW = "subflow"`；新建 `SubflowNode(BaseNode)` 空骨架（`_run` 抛 `NotImplementedError`）并登记进 `NODE_CLASS_MAP`。
  **依赖**: 无

## Wave 1：后端基础能力

- [x] **T06**：`inspect_flow_data` 测试
  **文件**: `T/workflow/test_subflow_inspect.py`
  **测试**: 判定含【输入】节点、含交互型【输出】节点（`input`、`choose`）、普通【输出】节点不算交互、含【子工作流】节点；提取开始节点变量名称；提取所有【结束】节点开关打开时的返回名称；返回名称为 `chat_history` 时判为不合规；数据为空或缺字段时不报错。
  **覆盖 AC**: AC-03、AC-04、AC-05
  **依赖**: 无

- [x] **T07**：`inspect_flow_data` 实现
  **文件**: `B/workflow/domain/services/subflow_inspect.py`
  **逻辑**: 纯函数，不访问数据库。决策见 design 决策 8。
  **测试**: T06 通过。
  **依赖**: T06

- [x] **T08**：【结束】节点返回结果测试
  **文件**: `T/workflow/test_end_node_return.py`
  **测试**: 开关关闭时 `_run` 返回 `None`、日志与改动前一致；开关打开时按引用解析出 `{名称: 值}`，列表值原样保留；旧数据（无新参数）按关闭处理。
  **覆盖 AC**: AC-19
  **依赖**: 无

- [x] **T09**：【结束】节点返回结果实现
  **文件**: `B/workflow/nodes/end/end.py`
  **逻辑**: 读取 `return_enabled`、`return_results`，经 `get_other_node_variable` 取值；补 `parse_log` 展示返回结果。决策见 design 决策 4。
  **测试**: T08 通过。
  **依赖**: T08

- [x] **T10**：`SubflowCallback` 测试
  **文件**: `T/workflow/test_subflow_callback.py`
  **测试**: 会话类事件（流式、输出、开场白、引导问题、用户输入）不产生任何外部调用；`on_node_start`/`on_node_end` 按执行顺序记录，含耗时、`reason`、`log_data`、`input_data`；能取出最后一个失败节点的名称；每个内部节点开始和结束时调用传入的中止检查，返回 true 时触发传入的中止动作。
  **覆盖 AC**: AC-15、AC-17、AC-20
  **依赖**: 无

- [x] **T11**：`SubflowCallback` 实现
  **文件**: `B/workflow/callback/subflow_callback.py`
  **逻辑**: 继承 `BaseCallback`；构造参数接收中止检查函数（父回调有 `get_workflow_stop` 时用它，否则恒为 false）和中止动作。决策见 design 决策 6、坑 6。
  **测试**: T10 通过。
  **依赖**: T10

## Wave 2：引擎与子工作流节点

- [x] **T12**：引擎与基类改动测试
  **文件**: `T/workflow/test_subflow_engine.py`
  **测试**: 引擎为【子工作流】节点预扫出 `referenced_outputs`，覆盖 `<id>.<名>`、`<id>.<名>#0`、`{{#<id>.<名>#}}` 三种形态，且不误匹配以该 id 为后缀的其它 id；`subflow_depth`、`start_node_id` 透传到节点；`BaseNode` 失败路径用 `parse_failed_log` 的返回值作为 `on_node_end` 的 `log_data`，默认仍为 `None`。
  **覆盖 AC**: AC-14、AC-17
  **依赖**: 无

- [x] **T13**：引擎与基类改动实现
  **文件**: `B/workflow/graph/graph_engine.py`、`B/workflow/graph/workflow.py`、`B/workflow/nodes/base.py`
  **逻辑**: `GraphEngine`、`Workflow` 新增 `subflow_depth`（默认 0）、`start_node_id` 并透传给节点；实例化节点之前预扫原始 nodes JSON 算出 `referenced_outputs`（正则见 design 决策 5）；`BaseNode` 新增 `parse_failed_log` 钩子。决策见 design 决策 5、决策 6、决策 9、决策 12。
  **测试**: T12 通过。
  **依赖**: T12

- [x] **T14**：`SubflowNode` 运行测试
  **文件**: `T/workflow/test_subflow_node.py`
  **测试**:
  - 按名称覆盖子工作流变量；多传的参数被忽略；未传的取子工作流自身值；「输入」方式为字符串、「引用」方式原样传递列表（AC-01、AC-13、AC-19）。
  - 子工作流含非交互型【输出】节点时仍能跑到【结束】节点（design 坑 1）。
  - 多个【结束】节点按执行顺序合并返回结果；返回结果开关关闭时输出为空（spec §3）。
  - 同一子工作流被两个节点调用时，两次运行的变量互不影响（spec §3）。
  - 引用的返回结果缺失时抛 10562，未被引用的缺失不报错（AC-14）。
  - 子工作流不存在时抛 10561（spec §3）。
  - 子工作流数据有非法连线导致构造失败时，抛 10560 且 `node_name` 为空（design 决策 10）。
  - 子工作流内节点失败、或超过单节点执行次数上限时，异常文本带标记，`data` 含子工作流名、失败节点名、原始错误（AC-20、AC-21）。
  - 成功时 `parse_log`、失败时 `parse_failed_log` 都含 `subflow_logs`（AC-17）。
  **覆盖 AC**: AC-01、AC-13、AC-14、AC-17、AC-19、AC-20、AC-21
  **依赖**: T05、T07、T09、T11、T13

- [x] **T15**：`SubflowNode` 兜底、上下文与中止测试
  **文件**: `T/workflow/test_subflow_node_guard.py`
  **测试**:
  - `subflow_depth >= 1` 时抛 10563；执行到【输入】节点（含表单为空的）或交互型【输出】节点时抛 10563（AC-06、design 决策 9）。
  - 子引擎拿到父引擎的聊天记录、运行者 `user_id`，开始节点 `current_time` 等于父开始节点的值（AC-09、AC-16）。
  - 子引擎的 `workflow_id`、`tmp_session_id` 等于父引擎的值（AC-21、design 决策 12）。
  - 中止标记出现后子引擎在下一个内部节点处停止，父节点原样抛出 `stop by user`，不包装成 10560（spec §3、design 坑 6）。
  **覆盖 AC**: AC-06、AC-09、AC-16、AC-21
  **依赖**: T05、T07、T09、T11、T13

- [x] **T16**：`SubflowNode` 实现
  **文件**: `B/workflow/nodes/subflow/subflow.py`
  **逻辑**: 按 design §4.1「运行」八步实现。用同步的 `FlowDao.get_flow_by_id` 读子工作流，依赖 worker 已设置的租户上下文自动过滤；用 `Workflow.run()`（决策 2）；运行上下文按决策 12；子引擎构造完成后再拷入聊天记录、设置 `current_time`（坑 5、坑 8）；`stop()` 同时停止子引擎；不做权限检查（决策 11）。本文件同时定义 `SUBFLOW_ERROR_MARKER`、包装函数与解析函数（决策 10），供 T18 使用。
  **测试**: T14、T15 通过。
  **依赖**: T14、T15

- [x] **T17**：失败信息识别测试
  **文件**: `T/workflow/test_subflow_failed_parse.py`
  **测试**: `parse_workflow_failed` 对带子工作流标记的文本返回 10560 错误事件；子工作流内部「执行次数超限」和 F078 技能错误的文本被包在标记里时，仍识别为 10560；`stop by user` 仍返回 `None`。
  **覆盖 AC**: AC-20
  **依赖**: T16

- [x] **T18**：失败信息识别实现
  **文件**: `B/worker/workflow/redis_callback.py`
  **逻辑**: `parse_workflow_failed` 先判断 `stop by user`，再用 T16 的解析函数识别子工作流标记，最后走其它子串分支。决策见 design 决策 10。
  **测试**: T17 通过。
  **依赖**: T17

## Wave 3：引用关系、校验与接口

- [x] **T19**：`SubflowService` 测试
  **文件**: `T/workflow/test_subflow_service.py`
  **测试**:
  - 引用同步：按父工作流当前版本整体替换；删除工作流时清除以它为父的记录。
  - 上线校验：子工作流含三类禁止节点时抛 10564，带子工作流名称与原因（AC-04）。
  - 保存提醒：给定旧数据与新数据，被引用的工作流新数据含禁止节点时返回 `subflow_warning.forbidden_nodes`（AC-05）；输入参数或返回名称增删时返回 `interface_changes`（AC-12）；未被引用时不返回。
  - 删除拦截：被引用时抛 10565 并列出引用方（AC-11）。
  - 候选过滤：给定一页行数据，排除自身和三类禁止节点（AC-03）。
  - 接口查询：返回输入参数名与当前值、返回名称；无编辑权限时拒绝。
  Repository 与 `FlowDao` 用 mock。
  **覆盖 AC**: AC-03、AC-04、AC-05、AC-11、AC-12
  **依赖**: T04、T07

- [x] **T20**：`SubflowService` 实现
  **文件**: `B/workflow/domain/services/subflow_service.py`
  **逻辑**: 方法：`sync_refs(flow_id, data)`、`check_online(data)`、`build_save_warning(flow_id, old_data, new_data)`、`check_delete(flow_id)`、`filter_candidates(rows, exclude_flow_id)`、`get_interface(login_user, flow_id)`。不调用 `B/api/services/`；`Flow.data` 用现有 `FlowDao.aget_flow_by_ids` 读取；接口查询用 `require_business_action(action="edit")`（C4）。决策见 design 决策 7、决策 8。
  **测试**: T19 通过。
  **依赖**: T19

- [x] **T21**：接入保存与切换版本
  **文件**: `B/api/services/flow.py`
  **逻辑**: `update_version_info`：**在覆盖 `version_info.data` 之前**留存旧数据（`B/api/services/flow.py:220`）；写入后若 `is_current == 1`，调用 `sync_refs` 与 `build_save_warning(旧数据, 新数据)`，把 `subflow_warning` 附在响应中。`change_current_version`：**切换前**读出旧 `Flow.data`，切换后同样处理。见 design §4.1「保存」。
  **依赖**: T20

- [x] **T22**：接入上线、新建与删除
  **文件**: `B/api/services/workflow.py`、`B/api/v1/workflow.py`、`B/api/v1/flows.py`
  **逻辑**: `update_flow_status` 上线时用待上线版本数据调用 `check_online`，切换版本后调用 `sync_refs`；`PATCH /workflow/update/{id}` 带 `status=2` 时用 `Flow.data` 调用 `check_online`（坑 2）；`POST /workflow/create` 创建后调用 `sync_refs`；`DELETE /flows/{id}` 在 `project_flow_delete` **之前**调用 `check_delete`，删除成功后清除以它为父的记录（坑 10）。写入口清单以 design §4.3 为准。
  **依赖**: T20

- [x] **T23**：候选与接口查询端点
  **文件**: `B/api/v1/workflow.py`
  **逻辑**: 新增 `GET /workflow/subflow/candidates` 与 `GET /workflow/subflow/{flow_id}/interface`。候选端点调用 `get_all_flows_envelope(flow_type=WORKFLOW, managed=True)` 分页取行，交给 `filter_candidates`；一页不满时继续取下一页，每次请求最多 5 页，返回游标（design 决策 8）。路径不含 `config`。
  **依赖**: T20、T22

- [x] **T24**：API 集成测试（测试降级，见「开发模式」）
  **文件**: `T/workflow/test_subflow_api.py`
  **测试**: 保存与切换版本的 `subflow_warning`；两个上线入口的拦截；删除拦截早于权限投影删除；新建后引用表有记录；候选列表凑页与 5 页上限；候选列表与接口查询用非管理员账号验证权限过滤。需要数据库，CI 运行。
  **覆盖 AC**: AC-03、AC-04、AC-05、AC-11、AC-12
  **依赖**: T21、T22、T23

## Wave 4：前端 Platform（手动验证）

- [ ] **T25**：`CodeInputItem` 增加可选 prop
  **文件**: `P/pages/BuildPage/flow/FlowNode/component/CodeInputItem.tsx`
  **逻辑**: 新增 `refOnly`（隐藏「输入」方式）与 `validateName`（额外名称校验）两个可选 prop；不传时代码节点的行为与样式完全不变。
  **手动验证**: 代码节点的输入参数增删改、引用与输入两种方式与改动前一致。
  **依赖**: 无

- [ ] **T26**：【结束】节点 v2
  **文件**: `P/controllers/API/workflow.ts`、`P/util/flowCompatible.ts`、`P/pages/BuildPage/flow/FlowNode/Parameter.tsx`、`F/platform/public/locales/{zh-Hans,en-US,ja}/flow.json`
  **逻辑**: 模板 `v: "2"`，新增「返回结果」分组：开关 `return_enabled`（默认关）、列表 `return_results` 用 `CodeInputItem` 并传 `refOnly`，`validateName` 拒绝 `chat_history`（design 决策 4）；开关关闭时隐藏列表；不显示类型列（R-7.3）。`flowCompatible` 增加 `end` v1→v2。新增文案三语，不写硬编码中文。
  **覆盖 AC**: AC-19
  **手动验证**: 打开旧工作流，【结束】节点显示开关且为关闭；打开后添加两个返回结果并保存，重新打开内容保留；名称重复或为 `chat_history` 时提示。
  **依赖**: T09、T25

- [ ] **T27**：【子工作流】节点模板与注册
  **文件**: `P/controllers/API/workflow.ts`、`P/pages/BuildPage/flow/FlowNode/NodeLogo.tsx`、`F/platform/public/locales/{zh-Hans,en-US,ja}/flow.json`
  **逻辑**: `workflowTemplate` 新增 `subflow` 模板，含 `subflow_id`、`subflow_inputs`、`subflow_outputs` 三个分组（design §4.2），`subflow_outputs` 用 `global: "code:..."` 暴露给变量选择器；`NodeLogo` 配图标与颜色；节点名称、描述、分组与帮助文案三语，帮助文案说明「运行时使用子工作流已保存的当前版本」（design 坑 11）。新增两个 API 函数：候选列表、接口查询。
  **手动验证**: 基础节点列表出现【子工作流】，拖入画布后显示三个分组。
  **依赖**: T23

- [ ] **T28**：子工作流选择与输入参数组件
  **文件**: `P/pages/BuildPage/flow/FlowNode/component/SubflowSelectItem.tsx`、`P/pages/BuildPage/flow/FlowNode/component/SubflowInputItem.tsx`、`P/pages/BuildPage/flow/FlowNode/Parameter.tsx`
  **逻辑**: 选择组件调候选接口，参照 `KnowledgeSelectItem` 的分页下拉；选定后调接口查询，生成固定名称的输入参数行（「引用/输入」两种方式，交互同 `CodeInputItem`）与只读的输出结果列表（只显示名称）。打开已配置的节点时重新查询接口：无权限时沿用节点里的快照；子工作流已不满足条件时在节点上显示提示。在 `Parameter.tsx` 注册两个新参数类型。
  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-10
  **手动验证**: 下拉只出现满足条件的工作流；选定后输入参数与子工作流变量一致；下游节点能在变量选择器中选到返回结果；把子工作流改为含【输入】节点后重新打开父工作流，节点上有提示；收回编排者对子工作流的编辑权限后打开节点，配置仍显示。AC-02 由开始节点已有的变量名唯一校验满足（`GlobalVarItem.tsx:34-50`），在子工作流里添加同名变量确认被拒。
  **依赖**: T27

- [ ] **T29**：保存提醒弹窗
  **文件**: `P/pages/BuildPage/flow/SubflowWarningDialog.tsx`（新）、`P/pages/BuildPage/flow/Header.tsx`、`P/pages/BuildPage/CardSelectVersion.tsx`
  **逻辑**: 弹窗组件列出引用方、禁止节点、接口变化；`Header.tsx`（保存、切换版本）与 `CardSelectVersion.tsx:28`（切换版本）在响应带 `subflow_warning` 时调用它。`Header.tsx` 已有 862 行，只加调用，不放弹窗实现。使用 `bsConfirm` 等现有组件，不新增组件样式。
  **覆盖 AC**: AC-05、AC-12
  **手动验证**: 在编辑页保存、在编辑页切换版本、在版本卡片切换版本，三处都能弹出提醒。
  **依赖**: T21、T27

- [ ] **T30**：上线与删除错误展示
  **文件**: `P/pages/BuildPage/flow/Header.tsx`、`P/pages/BuildPage/apps.tsx`
  **逻辑**: 上线 10564、删除 10565 按错误码文案展示并列出名称，沿用 `captureAndAlertRequestErrorHoc`；确认应用列表的上线开关也能展示 10564。
  **覆盖 AC**: AC-04、AC-11
  **手动验证**: 编辑页上线、应用列表上线、应用列表删除，各触发一次拦截。
  **依赖**: T02、T22

- [ ] **T31**：调试面板嵌套日志
  **文件**: `P/pages/BuildPage/flow/FlowNode/RunLog.tsx`
  **逻辑**: 识别 `type: "subflow_logs"`，以可展开列表展示每个内部节点的名称、耗时、失败原因、输入与输出，值复用现有 `ResultText`/`ResultFile` 渲染。
  **覆盖 AC**: AC-17
  **手动验证**: 运行含【子工作流】节点的父工作流，在节点日志中展开，看到子工作流各节点的输入、输出与耗时；让子工作流某节点失败，展开后能看到失败节点和原因。
  **依赖**: T16

- [x] **T32**：前端质量门
  **文件**: 上述前端文件
  **逻辑**: `src/frontend/` 下 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n` 通过；新文件不超过 600 行。
  **依赖**: T26、T28、T29、T30、T31

## Wave 5：验收

- [ ] **T33**：契约登记复核
  **文件**: `features/v3.0.0/release-contract.md`
  **逻辑**: 确认 T01 的登记完整；补「变更历史」一行。
  **依赖**: T01

- [ ] **T34**：E2E
  **逻辑**: `/e2e-test features/v3.0.0/086-nested-workflow`，逐条覆盖 spec 的全部 AC。AC-07 在子工作流保存后、以及切换当前版本后各运行一次父工作流；AC-09 用对子工作流无权限的普通用户；AC-18 走开放 API；AC-08 确认未上线子工作流不出现在工作台；AC-21 确认子工作流中模型调用的记录归属父工作流。验证环境为 119 共享沙箱。
  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21
  **依赖**: T24、T32

- [ ] **T35**：代码审查
  **逻辑**: `/code-review --base feat/3.0.0`；DM8 兼容按 C2 人工复核新表定义。
  **依赖**: T34

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时，先停下与用户重新确认。

- T04：Repository 的 `list_referrers` 改为 `list_referrer_ids`，只返回父工作流 id；引用方名称由 `SubflowService` 用 `FlowDao.aget_flow_by_ids` 补齐。原写法要求 Repository 读 `Flow` 表，与同一任务「不读 `Flow` 表」的约束冲突。
- T04：`replace_for_parent` 先查出已有行再逐行删除，不用批量 `DELETE`：批量删除不经过租户自动过滤（`src/backend/AGENTS.md` Known Pitfalls）。
- T13：`Workflow` 只新增 `subflow_depth`；`start_node_id` 由 `GraphEngine` 在构建节点前从原始数据找出，不作为 `Workflow` 参数（design 决策 12 已同步）。
- T18：`parse_workflow_failed` 最先识别子工作流标记，再判断 `stop by user`，与 design 决策 10 原写的顺序相反；用户中止从不包装，两种顺序结果相同，先认标记不会吞掉内部错误文本（design 决策 10 已同步）。
- T14：本地「执行次数超限」的用例用测试节点抛出同样的文本代替真实循环，构造真实循环需要条件节点，与本任务要验证的包装逻辑无关。
- T20：10564 的 `reasons`、10565 的 `referenced_by` 改为用「, 」连接的名称字符串，另附机器可读字段 `reason_codes`、`referrers: [{id, name}]`。原因：前端沿用通用错误提示，文案插值只能放字符串；10564 三语文案随之改为「含有不能在子工作流里使用的节点或返回结果：{名称}」（design §6.3 已同步）。
- T20：上线时子工作流已被删除抛 10561。引用表只记录当前版本，草稿版本指向的工作流可能已被删除，上线校验必须覆盖这种情况。
- T20：新增 `clear_refs(flow_id)`，删除工作流后由 T22 调用。
- T24：拆成两部分，都在本地运行：`test_subflow_ref_repository.py` 用 SQLite 实测 Repository；`test_subflow_api.py` 直接调用各入口函数、mock 协作方，断言调用顺序（删除拦截早于权限投影删除、两个上线入口、保存与切换版本用写入前的旧数据、新建后同步、候选凑页与 5 页上限）。真实 HTTP、MySQL 建表与非管理员权限过滤由 T34 E2E 覆盖：测试夹具是手写 SQLite DDL，不含 OpenFGA。
- T25：`CodeInputItem` 另加第三个可选 prop `fixedKeys`（名称只读、不能增删），供【子工作流】节点的输入参数表复用；不传时代码节点行为不变。删掉了原本未使用的 `i18nPrefix` 解构，按规则 `lint:prune` 收紧了对应的冻结计数。
- T26：开关 `return_enabled` 做成隐藏参数，由新组件 `EndReturnItem` 同时渲染开关和返回结果表，开关关闭时不校验列表；【结束】节点在有返回结果时显示运行日志（原先【结束】节点一律不显示日志）。
- T27、T28：【子工作流】节点只用一个分组：`subflow_id` 由 `SubflowSelectItem` 渲染，`subflow_inputs`、`subflow_outputs` 是隐藏参数，由该组件写入；变量选择器读取 `global` 时不看 `hidden`，下游仍能引用返回结果。不新建 `SubflowInputItem`，输入参数表复用 `CodeInputItem`（`fixedKeys`）。原因：三个参数分属三个组件时，选定工作流后要跨组件同步状态。
- T28：接口查询请求带 `silent`。请求拦截器把任何返回 403/404 的 GET 跳转到 403/404 页面，编排者失去子工作流编辑权限后打开节点（AC-10）会被带离编辑页；现在失败时沿用节点快照，404 时在节点上提示「不存在或已被删除」。
- T28 连带的后端修正：「输入」方式留空的参数行视为未配置，使用子工作流中变量自身的值（R-1.3、AC-01）；此前会用空字符串覆盖。`SubflowNode._resolve_inputs` 已改，`test_subflow_node.py` 已补用例。
- T29：编辑页的「切换版本」只在本地加载该版本数据，不调用 `change_version`、不改变当前版本，所以不需要提醒；调用 `change_version` 的只有版本卡片 `CardSelectVersion.tsx`。提醒接在编辑页保存（含上线前的保存）和版本卡片两处。
- T30：不需要改代码。编辑页上线、应用列表上线开关和删除都已经过 `captureAndAlertRequestErrorHoc`，错误提示按错误码文案插值 `data`，失败时开关状态不变。待 119 手动确认。
- T32：`pnpm typecheck` 的 platform 部分通过；client 与 `file-viewers` 的报错来自 worktree 软链到主检出的 `node_modules`，与本功能无关。platform `pnpm lint` 的剩余错误都在本功能未触及的文件中。platform vitest 失败的 16 个用例在改动前的基线上同样失败。
