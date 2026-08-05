# 看板数据集指标统计口径

> 更新时间：2026-08-05  
> 适用范围：`DASHBOARD_DATASET` 当前注册的全部数据集  
> 统计结果：14 个数据集、47 个指标

## 1. 文档目的

本文档说明看板中每个数据集及指标的端到端统计口径，包括：

- 原始业务表或埋点事件来源；
- 中间表的记录生成粒度；
- 指标固定过滤条件；
- Elasticsearch 聚合方式；
- 最终计算公式；
- 时间范围和时间粒度；
- 指标去重口径。

指标定义来自 [init_dataset.py](../src/backend/bisheng/telemetry_search/domain/init_dataset.py#L15)，查询执行逻辑位于 [component.py](../src/backend/bisheng/telemetry_search/domain/services/component.py#L155)。

## 2. 统一计算规则

| 规则 | 说明 |
|---|---|
| `cardinality(field)` | 按字段近似去重计数。 |
| `value_count(field)` | 统计字段非空的文档数量，不额外去重。 |
| 虚拟指标 | 聚合方式由后端数据集配置固定，看板组件中的聚合选项不改变其计算方式。 |
| 实体指标 | 默认使用 `sum`；看板编辑器允许改为平均、计数、最大、最小或去重计数。 |
| 比率指标 | 返回原始比值，例如 `0.25`；是否显示为 `25%` 由组件数字格式决定。分母为 `0` 时返回 `0`。 |
| 指标过滤 | 指标固定过滤条件与组件过滤、联动过滤、服务端权限过滤、时间过滤按 AND 合并。 |
| 累计总量，有时间维度 | 先按所选时间粒度计算每个时间桶的新增量，再执行 `cumulative_sum`。 |
| 累计总量，无时间维度 | 移除查询开始时间，保留结束时间，直接统计截至结束时间的总量。 |

累计指标分支实现见 [component.py](../src/backend/bisheng/telemetry_search/domain/services/component.py#L260)，ES 查询构造见 [search_engine_service.py](../src/backend/bisheng/telemetry_search/domain/services/search_engine_service.py#L338)。

## 3. 数据集数据来源与记录粒度

| 数据集 | 原始数据来源 | 中间表一条记录代表什么 | 时间字段口径 | 生成逻辑 |
|---|---|---|---|---|
| 用户行为指标表 `mid_user_increment` | MySQL `user` 表 | 一个用户；ES ID 为 `user_{user_id}` | 用户 `create_time` | [mid_table.py](../src/backend/bisheng/worker/telemetry/mid_table.py#L90) |
| 活跃用户表 `mid_active_user` | `base_telemetry_events` 中登录、会话、应用、知识库和文件操作事件 | 中国时区下“自然日＋用户”一条记录，取当天该用户最新事件中的用户信息 | 最新一次活跃事件时间 | [derived_events.py](../src/backend/bisheng/telemetry/domain/mid_table/derived_events.py#L187) |
| 应用数量表 `mid_app_increment` | MySQL 应用/工作流数据 | 一个应用；ES ID 为 `app_{app_id}` | 应用 `create_time` | [mid_table.py](../src/backend/bisheng/worker/telemetry/mid_table.py#L866) |
| 会话数量表 `mid_sessions_increment` | `new_message_session` 埋点 | 一次新会话事件 | 埋点发生时间 | [derived_events.py](../src/backend/bisheng/telemetry/domain/mid_table/derived_events.py#L319) |
| 会话运行时长表 `mid_session_run_dtl` | `application_alive`、`application_process` 埋点 | 有运行时长的事件保存一条明细；时长为 0 的在线事件按覆盖的每一分钟展开一条记录 | 会话开始时间；并发使用 `minute_ts` | [derived_events.py](../src/backend/bisheng/telemetry/domain/mid_table/derived_events.py#L481) |
| 工具调用时长表 `mid_tool_call_dtl` | `tool_invoke` 埋点 | 一次工具调用事件 | 埋点发生时间 | [derived_events.py](../src/backend/bisheng/telemetry/domain/mid_table/derived_events.py#L359) |
| 知识库存量表 `mid_knowledge_increment` | MySQL `knowledge` 表 | 一个知识库；ES ID 为 `knowledge_{knowledge_id}` | 知识库 `create_time` | [mid_table.py](../src/backend/bisheng/worker/telemetry/mid_table.py#L931) |
| 知识库文件存量表 `mid_knowledge_file_increment` | MySQL `knowledgefile`、`qaknowledge` | 一个文档文件或一条 QA 数据；ES ID 分别为 `file-{id}`、`qa-{id}` | 文件或 QA 的 `create_time` | [knowledge_file_increment.py](../src/backend/bisheng/telemetry/domain/mid_table/knowledge_file_increment.py#L56) |
| 知识空间内容统计 `mid_knowledge_space_content_stat` | 当前成功、未删除、主版本的知识空间文件；文件预览事件 | 文件是一条当前快照；预览是“文件＋中国自然日”一条累计记录 | 文件创建时间；预览日零点 | [mid_table.py](../src/backend/bisheng/worker/telemetry/mid_table.py#L372)、[knowledge_space_content.py](../src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py#L680) |
| 文件解析事件表 `mid_doc_parse_dtl` | `file_parse` 埋点 | 一次文件解析事件 | 埋点发生时间 | [derived_events.py](../src/backend/bisheng/telemetry/domain/mid_table/derived_events.py#L287) |
| 模型调用事件表 `mid_model_call_dtl` | `model_invoke` 埋点 | 一次模型调用按开始至结束覆盖的每一分钟展开；没有完整起止时间时只生成一条 | 埋点时间；并发使用 `minute_ts` | [derived_events.py](../src/backend/bisheng/telemetry/domain/mid_table/derived_events.py#L399) |
| 用户反馈指标表 `mid_user_interact_dtl` | `message_feedback` 埋点 | 一次点赞、点踩或复制操作 | 埋点发生时间 | [mid_table.py](../src/backend/bisheng/worker/telemetry/mid_table.py#L993) |
| 实时问答统计 `mid_realtime_qa_question_fact` | 专家问答 `Question`；门户 `portal_qa` 埋点 | “租户＋问答类型＋问题”一条记录 | 问题创建时间或问答成功时间 | [realtime_qa_question.py](../src/backend/bisheng/telemetry/domain/mid_table/realtime_qa_question.py#L91)、[realtime_dashboard.py](../src/backend/bisheng/worker/telemetry/realtime_dashboard.py#L119) |
| 全员每日参与度 `mid_user_daily_participation` | 当前有效员工名册＋`user_login` 登录埋点 | “租户＋中国自然日＋用户”一条可更新记录 | 中国自然日零点；登录时间另存 | [daily_participation.py](../src/backend/bisheng/telemetry/domain/mid_table/daily_participation.py#L188)、[mid_table.py](../src/backend/bisheng/worker/telemetry/mid_table.py#L136) |

## 4. 每个数据集下的指标计算

| 数据集 | 指标名称 | 指标字段 | 固定过滤条件 | ES 聚合方式 | 最终计算公式 | 时间口径 | 去重口径 |
|---|---|---|---|---|---|---|---|
| 用户行为指标表 | 总用户数 | `total_user_count` | 无 | 有时间维度：每桶 `cardinality(user_id)` 后累计；无时间维度：`cardinality(user_id)` | 截至当前时间桶的累计用户数 | 用户创建时间；支持年/月/周/日 | 按 `user_id` 去重 |
| 用户行为指标表 | 新增用户数 | `new_user_count` | 无 | `cardinality(user_id)` | 查询周期或时间桶内新增用户数 | 用户创建时间；支持年/月/周/日 | 按 `user_id` 去重 |
| 活跃用户表 | 活跃用户数 | `active_user_count` | 仅同步登录、会话、应用、知识库、知识文件相关活跃事件 | `cardinality(user_id)` | 查询周期或时间桶内至少产生一次活跃事件的用户数 | 活跃事件时间；支持年/月/周/日 | 按 `user_id` 去重；中间表已按日＋用户合并 |
| 应用数量表 | 总应用数 | `total_app_count` | 无 | 有时间维度：每桶 `cardinality(app_id)` 后累计；无时间维度：`cardinality(app_id)` | 截至当前时间桶的累计应用数 | 应用创建时间；支持年/月/周/日 | 按 `app_id` 去重 |
| 应用数量表 | 新增应用数 | `new_app_count` | 无 | `cardinality(app_id)` | 查询周期或时间桶内新增应用数 | 应用创建时间；支持年/月/周/日 | 按 `app_id` 去重 |
| 会话数量表 | 会话次数 | `session_count` | 仅 `new_message_session` 事件 | `cardinality(session_id)` | 查询范围内不同会话的数量 | 会话创建事件时间；支持年/月/周/日 | 按 `session_id` 去重 |
| 会话数量表 | 使用人数 | `platform_user_count` | `source = platform` | `cardinality(user_id)` | 平台页面产生会话的不同用户数 | 会话创建事件时间；支持年/月/周/日 | 按 `user_id` 去重 |
| 会话数量表 | API 调用次数 | `api_call_count` | `source = api` | `cardinality(session_id)` | API 来源产生的不同会话数量 | 会话创建事件时间；支持年/月/周/日 | 按 `session_id` 去重 |
| 会话运行时长表 | 会话运行时长 | `duration_seconds` | `duration_seconds != 0` | 实体字段；默认 `sum(duration_seconds)`，可在组件中修改 | 默认等于符合条件记录的运行秒数之和 | 会话开始时间；支持年/月/周/日/小时 | 不去重，按运行事件明细求和 |
| 会话运行时长表 | 最大同时在线会话数 | `max_concurrent_sessions` | `duration_seconds = 0` | 按 `minute_ts` 创建 1 分钟桶；桶内 `cardinality(event_id)`；再执行 `max_bucket` | `max(每分钟不同在线事件数)` | 开始到结束覆盖的每一分钟，首尾分钟均包含 | 每分钟按 `event_id` 去重 |
| 工具调用时长表 | 工具调用次数 | `tool_call_count` | 无 | `value_count(event_id)` | 工具调用事件文档数 | 调用事件时间；支持年/月/周/日 | 不额外去重 |
| 工具调用时长表 | 工具调用成功次数 | `tool_call_success_count` | `status = success` | `value_count(event_id)` | 成功工具调用事件文档数 | 调用事件时间；支持年/月/周/日 | 不额外去重 |
| 工具调用时长表 | 工具调用成功率 | `tool_call_success_rate` | 分子：`status = success`；分母：全部事件 | 分子、分母分别执行 `value_count(event_id)` | 成功调用次数 ÷ 全部调用次数 | 调用事件时间；支持年/月/周/日 | 不额外去重 |
| 知识库存量表 | 总文档知识库数 | `total_document_knowledge_base_count` | `knowledge_type = 0` | 有时间维度：每桶 `cardinality(knowledge_id)` 后累计；无时间维度：直接去重统计 | 截至当前时间桶的文档知识库总量 | 知识库创建时间；支持年/月/周/日 | 按 `knowledge_id` 去重 |
| 知识库存量表 | 总 QA 知识库数 | `total_qa_knowledge_base_count` | `knowledge_type = 1` | 有时间维度：每桶去重后累计；无时间维度：直接去重统计 | 截至当前时间桶的 QA 知识库总量 | 知识库创建时间；支持年/月/周/日 | 按 `knowledge_id` 去重 |
| 知识库存量表 | 新增文档知识库数 | `new_document_knowledge_base_count` | `knowledge_type = 0` | `cardinality(knowledge_id)` | 查询周期或时间桶内新增文档知识库数 | 知识库创建时间；支持年/月/周/日 | 按 `knowledge_id` 去重 |
| 知识库存量表 | 新增 QA 知识库数 | `new_qa_knowledge_base_count` | `knowledge_type = 1` | `cardinality(knowledge_id)` | 查询周期或时间桶内新增 QA 知识库数 | 知识库创建时间；支持年/月/周/日 | 按 `knowledge_id` 去重 |
| 知识库文件存量表 | 总文件数 | `total_file_count` | `knowledge_base_type = 文档知识库` | 有时间维度：每桶 `value_count(file_id)` 后累计；无时间维度：`cardinality(file_id)` | 截至当前时间桶的文档文件总量 | 文件上传时间；支持年/月/周/日 | 无时间维度时按 `file_id` 去重 |
| 知识库文件存量表 | 总 QA 对数 | `total_qa_count` | `knowledge_base_type = QA知识库` | 有时间维度：每桶 `value_count(file_id)` 后累计；无时间维度：`cardinality(file_id)` | 截至当前时间桶的 QA 数据总量 | QA 创建时间；支持年/月/周/日 | 无时间维度时按 `file_id` 去重 |
| 知识库文件存量表 | 文件大小 | `file_size` | `knowledge_base_type = 文档知识库` | 实体字段；默认 `sum(file_size)`，可配置其他聚合 | 默认等于文档文件大小之和 | 文件上传时间；支持年/月/周/日 | 不去重，一条文件记录参与一次 |
| 知识空间内容统计 | 总文件数 | `total_file_count` | `record_type=file`、`file_type=1`、`space_level` 为 `public`、`department`、`team` 或 `team_ks` | 有时间维度：每桶 `value_count(file_id)` 后累计；无时间维度：直接 `value_count(file_id)` | 当前有效文件快照按创建时间形成的累计数量 | 文件创建时间；支持年/月/周/日 | 当前每个文件只有一条快照 |
| 知识空间内容统计 | 新增文件数 | `new_file_count` | 与“总文件数”相同 | `value_count(file_id)` | 查询周期或时间桶内创建、且当前仍有效的文件数量 | 文件创建时间；支持年/月/周/日 | 当前每个文件一条快照 |
| 知识空间内容统计 | 内容贡献人数 | `contributor_count` | `record_type=file`、空间级别在允许集合内 | `cardinality(uploader_user_id)` | 上传过当前有效内容的不同用户数 | 文件创建时间；支持年/月/周/日 | 按上传人 ID 去重 |
| 知识空间内容统计 | 预览次数 | `preview_count` | `record_type = preview_daily` | `sum(preview_count)` | 各“文件＋自然日”记录中的预览计数之和 | 中国自然日零点；支持年/月/周/日 | 不按用户去重，每次成功预览均加 1 |
| 文件解析事件表 | 文档上传次数 | `doc_parse_count` | 无 | `value_count(event_id)` | 全部文件解析事件数量 | 解析事件时间；支持年/月/周/日 | 不额外去重 |
| 文件解析事件表 | 文档入库成功次数 | `doc_parse_success_count` | `status = success` | `value_count(event_id)` | 解析成功事件数量 | 解析事件时间；支持年/月/周/日 | 不额外去重 |
| 文件解析事件表 | 文档入库成功率 | `doc_parse_success_rate` | 分子：`status=success`；分母：全部解析事件 | 两次 `value_count(event_id)` | 解析成功次数 ÷ 全部解析次数 | 解析事件时间；支持年/月/周/日 | 不额外去重 |
| 文件解析事件表 | ETL 处理次数 | `etl_parse_count` | `parse_type = etl4lm` | `value_count(event_id)` | ETL 类型解析事件数量 | 解析事件时间；支持年/月/周/日 | 不额外去重 |
| 文件解析事件表 | ETL 处理成功次数 | `etl_parse_success_count` | `parse_type=etl4lm AND status=success` | `value_count(event_id)` | 成功的 ETL 解析事件数量 | 解析事件时间；支持年/月/周/日 | 不额外去重 |
| 文件解析事件表 | ETL 处理成功率 | `etl_parse_success_rate` | 分子：`parse_type=etl4lm AND status=success`；分母：`parse_type=etl4lm` | 两次 `value_count(event_id)` | ETL 成功次数 ÷ ETL 总次数 | 解析事件时间；支持年/月/周/日 | 不额外去重 |
| 模型调用事件表 | Token 消耗量 | `total_token` | 无 | 实体字段；默认 `sum(total_token)`，可配置其他聚合 | 默认等于命中文档中 `total_token` 之和 | 模型调用事件时间；支持年/月/周/日/小时 | 不去重；模型调用跨分钟时中间表会复制该字段 |
| 模型调用事件表 | 模型调用次数 | `model_call_count` | 无 | `cardinality(event_id)` | 不同模型调用事件数量 | 模型调用事件时间；支持年/月/周/日/小时 | 按 `event_id` 去重，消除分钟展开产生的重复 |
| 模型调用事件表 | 模型调用成功率 | `model_call_success_rate` | 分子：`status=success`；分母：全部模型调用 | 分子、分母分别 `cardinality(event_id)` | 成功模型调用数 ÷ 全部模型调用数 | 模型调用事件时间；支持年/月/周/日/小时 | 按 `event_id` 去重 |
| 模型调用事件表 | 最大 LLM 并发数 | `max_concurrent_llm_sessions` | 无 | 按 `minute_ts` 创建 1 分钟桶；桶内 `cardinality(event_id)`；再执行 `max_bucket` | `max(每分钟不同模型调用事件数)` | 调用开始至结束覆盖的每一分钟，首尾分钟均包含 | 每分钟按 `event_id` 去重 |
| 模型调用事件表 | 平均首 Token 响应延迟 | `avg_first_token_cost_time` | 无 | `avg(first_token_cost_time)` | 命中文档首 Token 延迟的算术平均值，单位毫秒 | 模型调用事件时间；支持年/月/周/日/小时 | 不按事件去重；按中间表文档计算平均 |
| 用户反馈指标表 | 点赞次数 | `like_count` | `interact_type = like` | `value_count(event_id)` | 点赞反馈事件数量 | 反馈事件时间；支持年/月/周/日 | 不额外去重 |
| 用户反馈指标表 | 点踩次数 | `dislike_count` | `interact_type = dislike` | `value_count(event_id)` | 点踩反馈事件数量 | 反馈事件时间；支持年/月/周/日 | 不额外去重 |
| 用户反馈指标表 | 复制次数 | `copy_count` | `interact_type = copy` | `value_count(event_id)` | 复制反馈事件数量 | 反馈事件时间；支持年/月/周/日 | 不额外去重 |
| 实时问答统计 | 问答总数 | `total_qa_count` | 无 | `value_count(question_id)` | 专家、智能、文档内 AI 问答记录总数 | 问题创建或成功时间；支持年/月/周/日/小时 | 中间表按租户＋类型＋问题 ID 保留一条 |
| 实时问答统计 | 专家问答数 | `expert_qa_count` | `qa_type = expert` | `value_count(question_id)` | 专家问答记录数 | 专家问题创建时间 | 每个专家问题一条记录 |
| 实时问答统计 | 智能问答数 | `smart_qa_count` | `qa_type = smart` | `value_count(question_id)` | 门户智能问答成功记录数 | 问答成功事件时间 | 每个问题一条记录 |
| 实时问答统计 | 文档内 AI 对话数 | `document_qa_count` | `qa_type = document` | `value_count(question_id)` | 文档场景问答成功记录数 | 问答成功事件时间 | 每个问题一条记录 |
| 实时问答统计 | 提问人数 | `qa_user_count` | 无 | `cardinality(user_id)` | 查询范围内至少产生一次问答的用户数 | 问题创建或成功时间；支持年/月/周/日/小时 | 按 `user_id` 去重 |
| 全员每日参与度 | 全员参与占比 | `participation_rate` | 分子：`logged_in=true`；分母：当天范围内全部名册记录 | 分子、分母分别 `value_count(user_id)` | 当天实际登录人数 ÷ 当天名册人数 | 中国自然日；默认查询当天 | 每天每租户每用户只有一条记录 |
| 全员每日参与度 | 实际登录人数 | `logged_in_employee_count` | `logged_in = true` | `value_count(user_id)` | 当天至少成功登录一次的员工数 | 中国自然日；默认查询当天 | 每天每个用户一条记录 |
| 全员每日参与度 | 全员总数 | `active_employee_count` | `active_employee = 1` | `value_count(user_id)` | 当天有效员工名册数量 | 中国自然日；默认查询当天 | 每天每个有效员工一条记录 |
| 全员每日参与度 | 实际登录次数 | `login_count` | 无 | 实体字段；默认 `sum(login_count)`，可配置其他聚合 | 成功登录事件的累计次数 | 中国自然日；默认查询当天 | 不按用户去重；同一用户每次成功登录均加 1 |

## 5. 查询时间规则

| 场景 | 实际行为 |
|---|---|
| 普通数据集没有配置时间过滤 | 查询索引内全部数据。 |
| 实时问答、每日参与度没有配置时间过滤 | 自动使用当天 `00:00:00` 至 `23:59:59`。 |
| 同时存在组件时间过滤和联动时间过滤 | 取所有时间范围的交集。 |
| 使用时间维度 | 按看板选择的年、月、周、日或小时创建 `date_histogram`。 |
| 累计总量＋时间维度 | 每个时间桶先统计新增量，再累计。 |
| 累计总量但没有时间维度 | 移除查询开始时间，只保留结束时间，统计截至结束时间的总量。 |

时间过滤实现见 [component.py](../src/backend/bisheng/telemetry_search/domain/services/component.py#L464)。

## 6. 完整性校验

通过静态加载当前 `DASHBOARD_DATASET` 配置进行校验：

```text
dataset_count=14
metric_count=47
unique_metric_keys=47
```

本文档描述的是当前代码定义的统计计算逻辑，未连接实际数据库或 Elasticsearch 核验运行时数据。
