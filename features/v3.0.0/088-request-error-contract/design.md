# Design: 前端请求错误完整透传

**关联**：[spec.md](./spec.md) · [tasks.md](./tasks.md) · [migration-inventory.md](./migration-inventory.md)
**版本**：v3.0.0 / F088
**最后更新**：2026-10-22
**状态**：spec/design 已确认，产品实现已落地，正在最终回归与独立复核。§4.1保留实施前基线作为对照，§4.2起与末尾实施同步描述当前实现；验收结论见tasks与verification-report。

## 1. 目标与非目标

请求失败始终向调用方传递可辨认的完整原因；统一提示和业务恢复各自履责，失败不能触发成功后的动作。两端使用相同错误模型，保留各自的成功结果和既有全局处理。

不调整后端协议、授权规则、请求库版本、查询库版本、状态管理或提示样式，不扩展 SSE/WebSocket/fetch 通道。允许已有明确业务恢复，禁止通用吞错伪装成功。

## 2. 关键约束与最新基线

- 遵循 [constitution.md](../../../docs/constitution.md) 和版本契约 [release-contract.md](../release-contract.md) 的 V3-INV-6；本次无后端或数据库变更，无新错误码。
- 原生隔离工作区从发版线快进至 `bc6ca25ba`，已包含 React Query 升级 `219bb0e8a`。两端使用 catalog 固定的 `@tanstack/react-query` **4.44.0**；platform 原 v3 描述不得继续作为实施依据。
- 保留 platform 新建的 `createPlatformQueryClient()`、数组 queryKey、`offlineFirst`、queries 默认 `retry: 0`、禁止窗口聚焦和挂载自动刷新，以及既有重连刷新行为。不重新创建 provider 或查询缓存。
- client 当前查询默认未覆盖重试次数；必须考虑新暴露的 HTTP 200 业务失败会进入查询重试。既有网络/HTTP 重试预算保持原值，不新增业务错误自动重试。
- UI 使用现有通知、表单和状态展示，遵循当前共享组件规范；此特性不重新选择 Toast/Notification 的外观或全面迁移提示组件。
- `silent`、`skip403Redirect`、`skipMaintenance` 先保留各自已有特殊行为，再迁移普通提示语义；不能借统一错误处理扩大免认证或免权限处理范围。

## 3. 方案对比与选定

### 决策 1：共同错误模型，两端保留请求适配器

- **备选**：A. 完全合并两端 Axios 与成功结果；B. 各端复制一份错误模型；C. 一个内部错误模型包，两端独立处理本端响应与界面。
- **选定**：C。新增无 UI、无状态库、无网络调用的 `@bisheng/api-client` 内部包，只承载错误类型、规范化与失败分类；两端自行翻译和提示。
- **原因**：platform 成功返回业务 data，client 的普通包装方法返回响应 body，完整响应方法还用于 headers。合并成功结构会破坏大量无关调用；复制模型则无法保证 AC-04 的长期一致。
- **重新考虑条件**：两端成功协议与登录路由真正统一，或该包只有单端使用；届时再评估合并请求适配器或内联。

### 决策 2：完整错误与提示状态独立

- **备选**：A. 提示后 reject null；B. 业务自己解析并提示所有错误；C. 始终 reject 同一规范化错误，记录是否已展示。
- **选定**：C。取消、静默和已全局处理仍传递失败；提示辅助函数在同一错误对象上保证不重复展示。表单专用处理关闭普通提示并标记已在表单展示。
- **原因**：当前 platform HTTP 失败丢失异常，旧包装层再把失败变为 false/undefined；Dashboard mutation 的本地 onError 与拦截器会重复提示。记录“已提示”只控制展示，绝不把失败变成成功。
- **重新考虑条件**：将来需要多个不同视图同时展示同一失败；届时可扩展展示作用域，而非恢复吞错。

### 决策 3：分批迁移，最终取消业务包装层吞错

- **备选**：A. 一次改变旧包装层返回值；B. 永久保留 false/undefined 作为失败；C. 先让底层保留错误，逐批迁移调用方，再清理包装层。
- **选定**：C。底层标准化后，旧包装层只作为临时兼容入口；新/已迁移代码直接消费 reject。所有调用方完成迁移后删除或改成仅用于提示且继续 reject 的入口，最终不能再返回失败哨兵值。
- **原因**：基线有 111 个非测试源文件引用该包装层（含定义文件），既有 `.then(...)`、未 await 的点击处理及按 false 判断等多种消费方式。全局翻转会产生未处理 rejection 和失败后的成功动作。
- **重新考虑条件**：迁移清单证实剩余入口全部不可达，可删除死代码及引用；不能为死路径重新接线。

### 迁移切换协议（独立审查修订）

迁移采用“先兼容消费方、后原子切换入口”的 expand/contract 顺序，不在调用方尚未准备好时全局改变错误字段或 client resolve/reject。

1. 共同模型先独立落地、测试，不改变旧入口。消费方先兼容完整错误，客户端 API 的命名恢复同时兼容旧返回体与新 reject；现有全局流程保持原顺序。
2. 必须与入口切换同批：登录 10601 数字 code→status_code；技能 11053 未导入恢复、11055 重名检查/覆盖、详情缺包与文件错误；二进制导出/下载的错误解析；QueryCache 的 response.status 消费。入口切换前，这些链路用旧和新两种失败输入均通过。
3. platform 旧包装层先适配完整错误的 message/presentation，保持旧调用方可用；逐个消费链改为直接请求与明确失败分支。最终切换时无业务依赖失败哨兵值，旧包装层不再吞错。
4. 本地批次只在特性分支推进；允许单测驱动的中间提交，不允许发布尚未完成调用迁移的入口切换提交。交付单位是入口、上述强耦合链及完整迁移清单的同一完整特性；最终不留下按请求选择是否传递失败的开关。
5. 每批验收包含失败后不成功跳转、不覆盖输入、不增加提示与恢复次数；最终扫描旧错误字段、特殊异常 instanceof 及 false/null 哨兵判断，逐项确认死路径或业务恢复，不按纯文本机械替换。

### 决策 4：保留升级后的查询行为，只修复错误消费

- **备选**：A. 查询失败统一返回 null 以避免 v4 的 undefined 限制；B. 在 QueryCache 再加一层全局 Toast；C. queryFn 保持真实失败，在实际消费点恢复页面并由唯一归属提示。
- **选定**：C。queryFn/mutationFn 不使用吞错包装层。已有合法空配置默认值只用于成功响应。对于顺序依赖的手工刷新，使用 `refetch({ throwOnError: true })` 或明确检查返回结果的 `isError`；不可假定 await refetch 会抛错。
- **原因**：升级新增的配置测试明确断言“请求失败 → null 缓存 → isSuccess=true”。安装版 4.44.0 的最小实验证实 reject 会保留原错误，而 catch 返回 null 会变成 success；默认 refetch 会 resolve 含 isError 的结果。见 §7 的验证记录。
- **重新考虑条件**：某业务明确把特定失败当作有效空值并写入 AC，例如许可证状态不可用时隐藏；只有此类命名恢复才允许返回有效业务值。

### 决策 5：沿用已有重试预算，避免新业务失败自动重试及重复提示

- **备选**：A. 两端全部关闭重试；B. 拦截器每次失败都弹窗；C. 保留网络/HTTP 的已配置预算，对新暴露的业务失败停止自动重试，重试查询在最终失败时提示。
- **选定**：C。共享 `shouldRetryApiError(error)` 对 business、canceled、invalid-response 及已触发全局接管的错误返回 false；其他错误交由原调用方预算决定。platform queries 默认仍为 0；Workbench 显式 retry:1 等逐处组合；client 默认预算仍为 3，显式 false/次数/函数逐处保留语义。
- **原因**：client 当前有业务失败 resolve；直接统一 reject 会激活原本不会发生的重试。不能因此增加失败请求和 Toast 次数，也不应取消已有网络恢复机会。
- **重新考虑条件**：产品明确要求某业务错误可重试，另以业务 AC 和幂等性证据制定例外；此特性不新增此类恢复。

## 4. 数据流与当前实现

### 4.1 实施前已核实基线

| 模块 | 当前职责与行为 | 边界 |
|---|---|---|
| `platform/src/controllers/request.ts` | 解包业务成功、翻译错误、处理会话/权限/许可证；普通业务失败通常 reject 字符串，HTTP 失败通常提示后 reject null | `preserveError`、`silent` 只是局部绕开；不能保证完整透传 |
| 同文件旧包装层 | 提示并 catch，返回 false/undefined 或取消标记 | 会掩盖失败，不适合 queryFn 或需要依赖失败分支的流程 |
| `platform/src/queryClient.ts` | 新升级后统一创建 provider 使用的 QueryClient | 本次复用其配置，不回到 v3 或混用两个缓存 |
| `platform/.../WorkbenchModel.tsx` | 配置查询先经过旧包装层再 `env ?? null`，成功 select 提供默认配置；保存后手工 refetch | 失败会成为成功缓存；保存失败后仍可能刷新并覆盖输入 |
| `platform/.../useSystemConfigEnvelope.ts` | 4 个配置页的 effect 查询，finally 结束 loading | 当前没有错误出口，迁移需记录错误并阻止未加载配置的误保存 |
| `platform/.../Dashboard/hook.ts` 与 `EditorHeader.tsx` | mutation 的 onSuccess 更新缓存/提示；onError 提示；mutateAsync 串联保存和发布 | 拦截器已有提示时会重复；链路需要在事件终点处理 rejection |
| `platform/.../charts/ChartContainer.tsx` | 手工 disabled 查询使用 isInitialLoading；刷新后显示图表 | 当前错误和无数据共用占位，需使失败可辨认，保留升级修正的 loading 语义 |
| `client/src/api/request.ts` | 保留响应 body；部分业务失败仅按 showError 提示后继续 resolve；另一些路径 reject 含业务码的 Error | showError/skip403Redirect 不应再决定失败与否 |
| `client/src/App.jsx` | QueryCache.onError 将 HTTP 401 交给现有错误上下文；默认未覆盖查询 retry | 必须保留 `.response.status` 证据，不额外增加全局 Toast 层 |

### 4.2 当前主线

请求响应或 transport 异常 → 本端识别响应形态、必要时解码错误 body → 本端翻译消息 → 共同模型标准化 → 保留既有全局处理/普通提示归属 → reject 同一错误 → API 不吞错 → Query/Mutation 或业务 catch 恢复状态 → 事件终点明确结束失败流程。

成功主线不变：platform 仍返回既有解包结果；client 普通方法仍返回 body，完整响应方法仍保留 headers。合法无 status_code 响应不当作失败。未知格式只在已有协议需要明确 envelope 时作为 invalid-response；不得把所有非 envelope 结果一律改为失败。

### 4.3 共同错误契约

包名 `@bisheng/api-client`；入口 `src/frontend/packages/api-client/src/index.ts`。无 React、i18next、Axios 运行时或 Toast 依赖；对原始响应采用结构类型，不复制或 JSON 序列化证据。

| 字段 | 类型 | 含义 |
|---|---|---|
| `name` / `message` | `ApiError` / string | 标准 Error；message 是本端翻译后可读消息 |
| `kind` | business / http / network / timeout / canceled / invalid-response | HTTP 200 业务失败为 business；HTTP 错误为 http，同时保留 body 中业务码 |
| `httpStatus` | number 或 undefined | 实际 HTTP 状态，绝不用业务码填充 |
| `status_code` | number 或 undefined | 服务端真实业务错误码，作为两端业务分支唯一规范字段 |
| `status_message` | unknown | 服务端原始消息，数组/对象不能被强制丢弃 |
| `data` | unknown | 服务端附加错误信息 |
| `response` | `{ status: number; data: unknown }` 的原始结构对象或 undefined | 保留原响应引用及其额外字段，兼容已有 `.response.status/data` 消费 |
| `code` | string 或 undefined | 原 transport 标识，例如 ERR_CANCELED；不放密码过期等数字业务码 |
| `cause` | unknown | 原始异常或失败证据引用，不自动写日志 |
| `presentation` | none / toast / inline / global | 是否已展示或被全局处理接管；不改变 kind 或 reject 行为 |

接口：`normalizeApiError(cause: unknown, options: { message: string; response?: ApiErrorResponse; envelope?: unknown }): ApiError`；输入已是 ApiError 时原样返回，保持对象身份。`isApiError(value: unknown): value is ApiError`；`shouldRetryApiError(error: unknown): boolean` 只决定错误种类是否允许使用原有重试预算，不决定次数。

二进制解析由本端异步适配器完成，`envelope` 专门接收已解析结果，不能改写 `response.data`。原 `cause`、原 `response` 和原二进制引用均保留；规范化字段提取优先级为显式 `envelope` → 原 response.data 中合法 envelope → cause 自身合法 envelope。只有明确的 envelope（有限数字 status_code）参与业务字段提取；undefined 表示没有解析结果，不用空对象覆盖有效原信息。HTTP 状态始终取原 response.status；消息始终使用本端已翻译的 message。已规范化错误原样返回，不能二次覆盖证据。

两端各导出 `showApiError(error: unknown): ApiError`：使用本端消息解析与既有提示 API，跳过 canceled、已提示和 global，真正展示后标记 toast。业务自行展示表单/业务消息时标记 inline/toast，不能通过返回 false 把失败吞掉。普通程序异常不冒充业务码。

### 4.4 文件与模块职责

| 文件/范围 | 做什么 | 不做什么 |
|---|---|---|
| `packages/api-client/package.json`、`src/apiError.ts`、`src/index.ts`、对应 Vitest/TS/ESLint 配置与测试 | 同一错误类型、规范化、展示状态与重试分类 | 不请求、不翻译、不依赖 UI/查询库 |
| 两端 `request.ts` 与拆出的 `apiError.ts`/消息解码模块 | 各端响应适配、消息翻译、提示和全局流程 | 不返回失败哨兵值、不改变成功结构 |
| `platform/src/types/global.d.ts` 与 client Axios 扩展声明 | 补齐 showError 及已有选项类型 | 不新增全局免认证选项 |
| 两端 package.json、lockfile、根 lint/typecheck 编排 | 接入一个 workspace 内部包及对应质量门禁 | 不修改 catalog 已锁版本、不引入新三方运行库 |
| API、hooks、事件处理器 | 透传失败、恢复 loading/乐观状态、阻止成功后续动作 | 不重复翻译同一错误、不把失败列表改为空成功 |

### 4.5 响应和全局处理矩阵

| 输入/选项 | 目标行为 |
|---|---|
| HTTP 成功 + status_code=200 | 原成功结构原样可用 |
| HTTP 成功 + 明确非 200 业务码 | 除已登记的特殊结果外，规范化 business 并 reject，与提示开关无关 |
| 无业务码的合法 JSON/二进制/第三方响应 | 按原接口协议成功，不强加统一 envelope |
| HTTP 非 2xx，包括合法 envelope body | kind=http，保留 HTTP 状态、业务码与完整 body；提示后仍 reject |
| 无响应的网络失败/超时 | 保留 cause 和 transport code；区分 timeout/network；不伪造响应 |
| 主动取消 | kind=canceled、保留 ERR_CANCELED；不 toast，不触发普通失败提示 |
| platform showError 未设置 | 普通失败由统一提示负责；已有包装层和本地通用提示同步去重 |
| client showError 未设置 | 迁移时显式固定各入口当前提示归属；不把所有查询新增为自动弹窗 |
| showError=false | 只关闭普通提示，不改变失败与全局处理；调用方仍取得 ApiError |
| platform silent=true | 作为已有兼容语义保留其现有分支顺序：HTTP 401 仍先处理，业务响应原有全局处理跳过行为不扩大；错误载体统一。已无特殊需求的调用迁到 showError=false；仍有特殊合同的调用保留并登记 |
| client skip403Redirect / skipMaintenance | 仅保留其对应既有全局处理例外；业务失败始终 reject。原 skip403Redirect 隐式 toast 的入口迁为明确 showError=true，不让跳转选项决定普通提示 |
| 登录失效/被踢/权限跳转/许可证/维护 | 沿用既有条件、排除 URL、确认顺序、节流与目标路由；执行后标记 global 并 reject，含 client 当前维护/403 resolve 分支 |
| 密码过期 10601 | 标准 status_code=10601；登录页继续进入重置流程，不再依赖数字 error.code |
| 11010 特殊结果 | 保留已有显式放行，暂不改变成错误；当前无活跃业务语义证据，绝不为其新增恢复路径；作为遗留兼容项独立测试 |
| Blob/ArrayBuffer 成功 | 保留下载、音频和 headers；不能消费或修改有效二进制 |
| Blob/ArrayBuffer 错误 | 有 HTTP 失败或可信 JSON 错误类型线索才解码；保留原 response/body 与业务证据。无效文本不伪装成功，不把 JSON 普通下载任意当错误 |

### 4.6 实际消费边界

- platform服务/API返回拒绝；UI事件/effect在终点消费，确认框接收原Promise以锁住重复提交，编辑器在成功后关闭。默认通知只由同一ApiError的presentation记录去重。
- client保留原认证/刷新响应阶段，先用解码视图执行原全局动作，再在末级统一拒绝；WeakMap按原response记录实际发生的toast/global，原response/data/cause不变。
- Blob成功下载原样返回；只有可信JSON类型或实际HTTP失败才解析错误，解析结果独立传入规范化，不覆盖原二进制。
- 列表与聊天历史有可辨认失败状态和重试入口。文件/文章/空间会话清空在服务端成功后更新本地；资源token、effect cleanup及会话身份检查阻止延迟结果覆盖新资源，清空pending期间锁住发送、重新生成和重复清空。
- Workbench写入与后续刷新分别处理：写入成功立即记下已接受配置，刷新失败保留输入/旧缓存并单独反馈，不再次写入。真实v4工厂回归见WorkbenchModel.commit.test.tsx。
- preview轮询HTTP仍沿用callback通道，失败事件携带原ApiError对象；任务自身的解析状态错误继续沿用原专业展示，不混作HTTP错误码。
- 审批场景的路由、流程及节点读取全部成功后统一提交；一半读取失败保留原场景、选择和未保存草稿。

## 5. 已知坑与处置

| 反直觉事实/证据 | 忽略的结果 | 处理位置 |
|---|---|---|
| v4 不能缓存 undefined，但可以缓存 null；null 并不代表 error。新增配置测试已断言失败被标为 success | 查询看起来完成，默认空配置可能覆盖已有输入 | WorkbenchModel queryFn、queryConfigMigration 测试 |
| v4 默认 refetch resolve 包含错误状态的结果；本地 4.44.0 最小脚本已验证 | 保存/刷新链 await 后继续走成功动作 | 依赖刷新结果的 hooks 与事件处理器，使用 throwOnError 或检查 result |
| mutate 使用回调消费错误；mutateAsync 仍返回拒绝的 Promise | 只写 onError 仍可出现未处理 rejection；后续发布/跳转链错误 | Dashboard EditorHeader、发布 hook、异步表单终点 |
| platform 新 QueryClient 离线模式是为内网保留的，disabled 查询 spinner 已改为 isInitialLoading | 统一处理时误改 provider 或 loading 会重新卡住内网/手工加载页 | queryClient.ts、ChartContainer 与已有迁移测试 |
| 同一 HTTP 失败可能先被拦截器提示，再被 mutation.onError 提示 | 用户连续收到两个 Toast/Notification | 统一 showApiError + presentation，清理相关 onError 直接提示 |
| 显式重试的 hook 会产生多个不同错误对象，单纯按错误对象去重不能跨尝试去重 | 多次失败提示，即使最终查询只失败一次 | 该 hook 的 API 请求关闭普通提示，最终 onError 才 showApiError；多个观察者对最终同一错误对象去重 |
| 保存已失败，旧包装层返回后仍执行 refetch；Workbench 现有代码可见该顺序 | 输入被服务端旧值覆盖，出现保存成功错觉 | Workbench submitConfig 直接 await reject；finally 只恢复 pending |
| 写入已成功但后续刷新失败是两个不同结果 | 把已成功写入误报为写入失败，并诱发重复提交 | 顺序操作分别处理写入与刷新；刷新失败保留编辑态/输入，不自动重写或伪造回滚 |
| 成功的空配置可有默认值；与请求失败不是同一种空 | 修复吞错时误删合法默认配置或继承 metadata | finetune envelope、useLinsightConfig select、配置页面 |
| 许可证状态获取已有命名恢复；权限惰性读取也有明确“无额外动作”语义 | 机械删除 catch 会扩大业务变更 | license.ts、Dashboard 权限 hooks，逐项保留并测试，不泛化为列表失败恢复 |

## 6. 对外契约与依赖

### 6.1 提供给调用方

- 共同 ApiError 与两端 showApiError，接口见 §4.3；统一 HTTP 入口的失败一律 reject。业务数字码使用 status_code，原 transport code 保留 string。
- 两端原 HTTP 成功协议、完整响应和文件能力不变。没有新增 HTTP 或 Python API。
- 旧包装层是迁移期入口，不是最终业务失败协议；最终完成要求以全调用清单而非入口开关为准。
- 受影响的消费方：API 二次 catch/解包、Query/Mutation、直接表单/事件、上传 onFail、DSH 错误判断、登录密码过期、错误日志和下载 body 解析。风险为旧字符串比较、数字 code、null 哨兵值或重复提示继续遗留。

### 6.2 外部与内部依赖

| 依赖 | 合同与风险 |
|---|---|
| Axios 现有包装 | response、transport code 与 cancel signal 须保留；规范化不能销毁 response.headers 或把取消转为业务失败 |
| 后端 envelope 与非 envelope 接口 | 分清 HTTP 状态、status_code 和业务 data；嵌套的配置 envelope 不能二次误解包 |
| React Query 4.44.0 | 抛错才进入 error；refetch 与 mutateAsync 的拒绝语义不同；升级大版本需复验，当前不套用 v5 的 loading/callback 规则 |
| platform queryClient 工厂 | 保留 offlineFirst、retry:0、重连行为和数组 key；不要新建第二个上下文 |
| client QueryCache 401 监听 | `.response.status` 与同一错误对象须保留；不重复添加登录跳转或默认错误 Toast |
| i18n 与既有提示实例 | 各端命名空间不同；共同包不依赖翻译与 UI。新文案同批补三语言，生成物按既有脚本产出 |
| 原会话/权限/许可证/维护流程 | 任何控制顺序改变可能劫持被踢确认或覆盖页面；按矩阵测试并发和排除 URL |

## 7. 测试与可观测

### 7.1 已执行的基线核实

- 基线 `bc6ca25ba` 的依赖与源码核实两端均 4.44.0；隔离分支已快进到此提交，未拷贝旧工作区未提交文件。
- 在已安装依赖的主检出运行只读行为回归：从 `src/frontend/platform/` 执行 `pnpm exec vitest run src/queryClient.test.ts src/pages/ModelPage/manage/queryModelMigration.test.tsx src/pages/ModelPage/manage/tabs/queryConfigMigration.test.tsx src/pages/Dashboard/components/charts/ChartContainer.test.tsx --maxWorkers=1 --minWorkers=1`。结果 **4 文件 / 8 测试通过**；这是升级基线，不是 F088 实现验证。
- 对实际安装的 `@tanstack/react-query` 4.44.0 运行 Node 最小断言：fetchQuery reject 保留同一错误且 state=error；catch 返回 null 则 state=success；默认 observer.refetch resolve 且 isError=true；throwOnError:true 才 reject 同一错误。全部断言通过。未向仓库添加原型代码。

### 7.2 实施验证策略

- 共同包单测覆盖普通/非标准错误、消息安全、幂等规范化、原始证据引用、取消和重试分类。
- 两端拦截器用真实 Axios adapter 或等价受控响应验证 HTTP 200 业务失败、HTTP 错误、非 envelope、下载及会话全局矩阵；不只 mock 掉请求层后证明页面 mock 行为。
- React Query 集成使用生产 QueryClient 工厂验证 error/isSuccess、缓存保留、多个观察者最终提示次数、显式重试预算、离线/disabled/reconnect、mutateAsync 链与 refetch 失败。
- 页面测试验证输入保留、finally 复位、错误不触发 onSuccess 缓存更新/发布/跳转，且不因背景刷新覆盖用户正在编辑的字段。图表区分失败与成功空结果，复用现有样式与状态组件。
- 更改 queryConfigMigration 中“失败也 isSuccess”的断言，替换为真实错误状态；保留成功 envelope 的继承 metadata 测试。queryClient、queryModelMigration 和 ChartContainer 的升级回归继续通过。
- 每批在 migration-inventory/tasks 记录实际活跃入口、API→hook→页面链、测试和保留的命名恢复；全量消费关系完成才满足 AC-21。
- 最终运行前端 lint/typecheck/check-i18n、受影响 Vitest/Jest、`/e2e-test` 与 `/sdd-code-review`。实现已落地；各项实际结果与未完成验证见verification-report.md，不将本策略列表作为通过证据。

### 7.3 手动验证与观测

- 以有权限的现有测试账号本地启动 platform（`:3001`）与 client（`:4001/workspace`），client 登录入口沿用 `/__dev/login`；后端地址只用当前环境实际配置，不新建凭据或假定测试账号密码。
- 浏览器 Network override 或测试 adapter 注入一次 HTTP 200 业务错误、409 envelope、网络断开：在工作台模型配置、Dashboard 保存/发布、图表手工刷新和 client 的知识/个人令牌操作中核实错误状态、输入保留、请求次数和提示次数。
- 验证保存后刷新失败：写入只发生一次，刷新失败不会再次写入或将服务端已成功的写入伪称失败。
- Console 不出现未处理 Promise rejection；错误诊断只记录必要码和场景，不自动输出请求 headers、token、完整表单或 cause 全量内容。不新增持久监控服务。

官方语义依据（运行结论以本地锁定版本断言为准）：[v4 Query Functions](https://tanstack.com/query/v4/docs/framework/react/guides/query-functions)、[v4 Mutations](https://tanstack.com/query/v4/docs/framework/react/guides/mutations)、[v4 Query Retries](https://tanstack.com/query/v4/docs/framework/react/guides/query-retries)。

## 8. 后续改进与不做的事

- `11010` 只保留现有放行的兼容行为；没有活跃语义证据，不能补造页面流程。后续若能确认彻底废弃，单独删除。
- 不统一两端 QueryClient 的全部配置，内网与终端应用当前配置有各自用途；只对新暴露失败的重试和提示作必要衔接。
- 不全面改写 useSystemConfigEnvelope 为查询库或重构 client App 的 provider 组织；只处理本次受影响的错误出口和必要缓存生命周期问题。
- 不全面整改既有提示组件选择和外观。需要视觉改版时遵循设计师签核，另起范围。
- 设计确认后才建立完整可执行任务拆解及每批活跃调用链；候选引用清单不是已完成活跃性审计。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-22 | 初版设计草案；更新至 bc6ca25ba，纳入升级新增查询工厂、配置失败 null 缓存及新回归测试 | 用户确认 spec 并提醒关注刚升级的 React Query |

| 2026-10-22 | 补齐先适配消费方再原子切换协议；明确二进制独立 envelope 输入及证据优先级，用户授权修订后直接开发 | 独立审查两项 NEEDS_FIX |

## 实施同步（2026-10-22）

- client保留原认证/刷新响应阶段，在其后追加完整错误规范化阶段；前一阶段先取解码视图执行原全局动作，原response/data/cause不变。两个阶段用WeakMap按原响应记录实际发生的toast/global，而不是看到错误码就推断已处理。二进制500/403/11001及无MIME HTTP失败回归已覆盖。
- 二进制解码支持显式httpFailure上下文，仅HTTP失败允许无JSON MIME Blob解析；成功非JSON文件仍原样返回。模板参数由纯函数resolveErrorMessageTemplate补齐，无法补齐时使用本端fallback，避免暴露占位符。
- platform全部生产旧HOC调用已迁走，兼容导出只展示并继续reject。handleUiRequest仅作为明确UI终点消费失败，不用于queryFn/API层。
- AppChat旧resolved失败后读取已删除应用的分支在基线因skip403Redirect=true始终reject而不可达，已删除并提供真实失败/重试界面；不重新接通死业务。

- 2026-10-22 实施终审同步：补确认Promise、两类编辑器保留草稿、审批场景原子读取、preview原错误、聊天历史重试及清空归属锁；Workbench提交与刷新分离。原因与独立审查处置见review报告；未执行的浏览器验收保持未勾选。

- 最后附件计数修复：失败移除仅结算实际pending项，已移除/已完成项不重复扣计数；待全部上传完成后只发布具有效路径的附件，同批失败+延迟成功回归覆盖。既有基线与未执行真实E2E的验收状态见verification-report.md。
