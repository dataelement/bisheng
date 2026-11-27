# 预测场景接入合同 v0.8.0

## 原生执行与业务工具分工

平台负责真实模型、Skill 装载、工具执行和任务状态；Skill 负责预测→历史→解释→提交；Python 服务负责范围冻结、接口适配、确定性统计、验证和同结果报告。历史适配器当前为 `mock_sql`，不能称已调用内置 NL2SQL 子 Agent。后续接入原生 NL2SQL 时，将其查询结果和来源证据转换为此历史合同，并补查真实子 Agent 调用记录。

`POST /api/runs` 输入 query/spec/customer/start_month/months，返回 run_id、临时 token、冻结 scope 和 agent_base_url；此调用不预测、不生成解释。模型及 Skill 从当前用户的原生目录选择，提交 task_mode=true，仅选择 procurement-forecast-fast、本场景专用 native_model_id 与绑定的原生预测 API 工具。

实际任务绑定已注册的原生 API 工具 `forecast_execute`（配置 `FORECAST_NATIVE_TOOL_KEY`），参数 `request_json` 为 JSON 字符串，包含 run_id/token/action；finalize 增加 Agent 撰写的 explanation。平台 API 工具调用服务 `/api/skill-execute`，服务包装器补入当前实际 Skill/辅助脚本的文件摘要，再执行同一分阶段合同。正常运行先 prepare（内部按序forecast/history，独立保留两动作回执），后finalize，共两次原生业务工具请求。摘要只标识工件，不宣称 CLI 已运行。动作顺序、重复提交、有效期和批次变化均校验；token 不进入审计、最终回答或报告。

保留 `/api/runs/{run_id}/forecast|history|finalize` 与 Bearer token 的辅助测试接口和 CLI；实际原生任务不使用代码执行器联网，因为当前执行沙箱网络隔离。正式报告只接受原生 API 工具输出的三动作证明，辅助 CLI 回执不能替代。

`GET /api/runs/{run_id}` 同样鉴权；核验前不返回正式 result。`POST .../verify` 仅接收 chat_id/session_version_id，由服务器使用当前会话 Cookie 只读获取平台记录，不接受客户端提交的“已完成”状态或工具 transcript。前端在原生任务创建后调用 `POST .../bind`，服务核对当前用户授权且任务包含本次临时运行凭证，再在后台核验所选 Skill、绑定API工具、模型与权限目录、真实正文读取和三个业务动作回执。证据齐全即可放行业务报告，记录核验时真实原生状态及 completion_gate；随后通过原生终止接口停止尾部生成，不声称该任务自然 completed。缺证据、失败或超时不放行报告。旧 verify 接口仍保持 completed 合同兼容。

## 预测 API

`FORECAST_API_BASE` 配置的服务接受 `GET /api/forecast?spec=...&customer=...&start_month=YYYY-MM&months=1..12`，带 X-Request-ID。

- 裸 JSON 数字 0：此物料不可预测。
- 结构化对象：spec/customer/start_month/months/unit=件/currency=CNY/model_version/dataset_sha/input_order_ids/monthly。
- 每条 monthly：month/spec/customer/quantity/unit_price/amount/prediction_id/model_version/is_synthetic；backtest_mape可选。数量、单价、金额必须有限且非负，金额必须等于数量乘单价保留两位；同月同客户不得重复，覆盖整个请求窗口。
- backtest_mape 为可选归一化比例：缺失或null表示未提供，不阻断已验证的月度量价，也不补0或模拟值；提供时必须是0—1范围内的有限数，拒绝布尔值、字符串和越界值。质量栏目显示“未提供”，不能据缺失指标声称模型已通过评测。
- 结构化合法 quantity=0 是有效预测，不走裸 0 分支。
- HTTP 错误、超时、错型号、缺月份、单位不符、数值异常都是服务失败，不冒充不可预测。

当前默认模拟严格检查本地数据批次。配置外部服务后允许其独立 dataset_sha 和明确的 is_synthetic，分别记录预测快照，跨源不一致显式提示；不会标成本地模拟批次。正式接口若非此形状，应在服务侧适配，不能让模型自行补月、改单位或拆年度量。

## 历史 / NL2SQL 适配 HTTP

设置 `FORECAST_HISTORY_URL` 后，`HttpHistoryAdapter` POST：

```json
{"request_id":"本次run_id","scope":{"specs":["规格"],"customer":"all或指定客户","window":{"start":"YYYY-MM-DD","end":"YYYY-MM-DD"}},"snapshot":{"dataset_sha":"本地参考快照","version":"批次","cutoff":"截止日期"}}
```

返回 JSON 必须包含 ok=true、原 request_id、精确 scope/window、自己的 dataset_sha、complete=true、records 数组及 source 对象。source 包含 mode=nl2sql、非空 query_id/label 和明确 is_synthetic 布尔值。该字段是接入服务的来源声明，尚不独立证明原生子 Agent 已执行。

records 每行：order_id/spec/material/customer/date/quantity/unit_price/supplier/expected_delivery_date/actual_delivery_date/source_id/unit/currency。日期 ISO，允许两种交付日期为 null；单位件／CNY，scope 外记录、重复订单或证据、负数／非有限数、交付早于订单、部分结果均拒绝。可带 amount，但必须匹配量价。服务重新计算月度、加权单价和交付统计，不信任外部聚合。

当前客户和物料目录、日期窗取本次本地运行配置；接正式库还需同步正式目录和业务日期口径，并完成权限、分页完整性与字段映射验收。历史快照允许独立 SHA，记录是否与预测参考批次对齐，跨源时明确限制。真实连接信息只在适配服务侧，不打包 sales-db 示例 secrets。

## 解释与报告

解释 schema 在 Skill 的 references/contracts.md，含 headline/body/factors/limitations/influences/suggestions。因素、影响和合同建议基于本次事实，引用有效证据 ID；建议完整覆盖可预测物料客户，数量、金额、期间由服务器直接填入，LLM 不修改。bare 0 未披露原因时，只能把稀疏性作为样本观察与建模限制，不声称已知服务拒绝原因。

HTML、Markdown、JSON 引用同一个 request_id、事实和结果；报告同时保留数据、预测、历史查询、解释模型和原生任务来源。模拟预排合同建议不构成采购指令。

## 原生工具回包大小

原生 API 回包首键 receipt 含完整动作身份，防止平台大结果预览截断回执。给模型的 facts 为解释所需的确定性摘要；monthly 按 monthly_columns 说明的顺序提供二维月度值。全部原始订单、逐客户预测与月度图表仍在冻结结果及同次正式报告中，不因模型回包精简而删减页面或报告。稀疏分支最多带20条实际订单明细，完整统计基于已验证的全量记录。

历史价格 previous/current 缺失时，解释不能断言环比为0。已对观察到的错误断言加拦截与回归；此校验只覆盖已知错误切片，不代替完整语义核对，真实模型解释仍需人工复核。

首 receipt 的共同 run_id/skill_sha256/cli_sha256 适用于两个精简 subactions；每个子动作有自身 action/action_sha256/ok。外层身份、两个子动作及顺序、SHA均独立核验，拒绝身份覆盖或多余子动作。月度历史、交付及时间维度可用列名+二维数组传输，解码后全量值不变，完整报告保留原结构。
