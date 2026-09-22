# Script Directory

This directory contains manual maintenance and migration scripts for the backend.

## General Database Scripts

### `move_personal_files_to_clinic.py`

扫描指定租户的全部有效个人知识库，将指定完整目录路径（含子目录）中的文件，按上传人的主组织迁入最近科室绑定的科室库。独立单文件脚本，运行依赖当前后端环境。

```bash
# 在 src/backend 下执行；默认只读预览并输出 JSON 报告。
.venv/bin/python scripts/move_personal_files_to_clinic.py \
  --tenant-id 1 --folder-path '一级目录/二级目录'

# 核对预览后执行；123 替换为实际全局超级管理员 ID。
.venv/bin/python scripts/move_personal_files_to_clinic.py \
  --tenant-id 1 --folder-path '一级目录/二级目录' --operator-id 123 --apply

# 目标库所有者不存在或禁用时，显式允许使用操作人作为迁移文件的权限所有者。
.venv/bin/python scripts/move_personal_files_to_clinic.py \
  --tenant-id 1 --folder-path '精益项目' --operator-id 123 --apply --use-operator-as-file-owner

# 省略 --folder-path 或传 /：扫描全部个人库文件，包括根目录文件。
.venv/bin/python scripts/move_personal_files_to_clinic.py --tenant-id 1

# 修复中断的索引与权限；使用 recovery 子目录的文件，不同时传 --folder-path。
.venv/bin/python scripts/move_personal_files_to_clinic.py \
  --tenant-id 1 --operator-id 123 --apply --recover-report migration_reports/personal_to_clinic/recovery/报告.json
```

- 目录名称精确匹配，保留相对个人库根目录的完整路径。例如筛选 `A/B`，`A/B/C/文件.pdf` 迁入目标科室库的 `A/B/C/文件.pdf`。目标目录逐层复用或创建，源空目录保留。
- 优先 `original_uploader_id`，缺失时使用 `user_id`；原始上传人已记录但用户无效时不回退。仅使用唯一主组织，沿父级取最近的 `org_level=office`，不使用兼任组织，也不越过“未绑定科室库”的最近科室寻找更高层科室。
- 科室库必须有该科室的绑定，范围为 `team_ks` 或兼容旧版 `team`，且 `owner_type=user`；排除未发布库和收藏库。多个有效目标按知识库 ID 升序取第一个，不自动创建知识库。多租户部署必须指定 `--tenant-id`，只处理该租户。
- 原地迁移，保留文件、文档、版本 ID、原对象、上传人、分块及向量，不重新解析、不提交 Celery 解析任务；补齐缺失原始上传归属。其他发布/共享入口保留。文件权限调整为目标库所有者和目标目录（根文件为目标库）父关系，原文件上的其他直接授权被替换；未完成单元的原权限保留在独立恢复文件中。
- `--use-operator-as-file-owner` 默认关闭，仅在目标库所有者不存在或禁用时，用已校验的 `--operator-id` 接管迁移文件的权限 owner；有效库所有者仍优先使用。不会修改文件上传人或科室库所有者，其他校验不跳过，且与只修复索引的 `--force-rewrite` 独立。恢复自动沿用报告记录的权限所有者，无需再次传此开关，也不随本次 `--operator-id` 更换；原库所有者 ID 已变化或记录的权限所有者失效时拒绝恢复。
- 只支持共享存储且规范文档/完整版本链就绪的文件。没有上传人、主组织、科室或科室库，版本链不完整/目标不一致，未解析、投影未就绪、审批中等均不迁移并记录；同名或相同 MD5 的目标文件不覆盖。预览给出候选及筛选跳过原因；外部索引、权限、审批和即时冲突在正式执行逐文档复核。
- 报告默认写入 `migration_reports/personal_to_clinic/`，可用 `--report-dir` 指定。主 JSON 只列出“匹配目录但未完成迁移”的文件，每项仅包含 `file_id`（文件 ID）、`file_name`（文件名）、`source_space_id`（来源库）、`source_folder`（原目录）、`reason`（未迁移原因）。成功和未匹配文件不记录，无异常时为 `[]`；预览仅列筛选不通过项，不将仅预览的候选记为失败。无法确认属于指定路径的损坏目录不列入该路径的报告。
- `recovery/` 子目录仅保存尚未完成迁移的必要恢复状态；成功单元、完整计划和堆栈不落盘。用其文件执行 `--recover-report` 后会更新主报告；恢复到原库的文件仍记录“已恢复至原库，未迁移”，恢复后成功迁入的文件从主报告移除。兼容读取此前的完整恢复报告。主报告和恢复文件权限均为 `0600`。
- 数据库、ES、Milvus、OpenFGA 不能一起原子回滚。恢复根据数据库当前归属（源库或目标库）修复中断项，不撤销成功迁移；失败可能留下已创建的空目录。单文件/文档失败后继续后续文件，报告无法落盘时立即停止。
- 执行必须使用维护窗口，停止相关文件上传、移动、解析、发布/共享及索引对账写入；脚本不自动停止服务或获得全局维护锁。需要改写历史索引归属漂移时显式加 `--force-rewrite`，以数据库有效入口重写并读回校验，最多额外重试两次，不放过内容或向量变化。
- 退出码：`0` 正常结束（可能包含跳过项）、`2` 存在逐项执行失败或参数错误、`1` 全局初始化/扫描失败、`130` 人工中断。需要恢复时终端打印待恢复数量和恢复文件路径。

### `export_portal_qa_statistics.py`

只读统计智能问答和单文档问答的**现存提问记录**，输出一张两行五列的
`智能问答与单文档问答统计.csv`：问答类型、提问总数（含失败）、AI回复成功次数、成功比例、回复点赞数。
不修改问答流程、不补写失败记录、不增加依赖。由数据库 `chatmessage` 和 `message_session` 配对统计；
ES 门户问答事件/事实表只记录成功，不能用来筛选全部提问，因此此脚本不调用 ES。

从后端根目录执行：

```bash
python scripts/export_portal_qa_statistics.py \
  --all-tenants --start-date 2026-08-01 --end-date 2026-09-21 \
  --output-dir /app/portal-qa-statistics-0801-0921 --verbose

# 本地可用 .venv/bin/python；指定租户时将 --all-tenants 换成 --tenant-id 1。
# 不传日期表示全部现存历史；可用 --config config_3002.yaml 选择已有后端配置。
```

- 按提问 ID 计数：存在对应的最终 AI 回答记录即成功，无回答记失败，成功比例为成功提问数/提问总数。
  总数为 0 时比例输出 `0.00%`。这里只判断回答记录是否存在，不判断回答质量、正文是否为空或错误文案。
  同一提问多条回复只计一次成功；失败数内部计算为总数减成功数，不增加结果列。
- 只匹配 `answer` / `agent_answer` 的最终消息，排除用户消息、流片段、思考过程和工具消息。
  先使用 `extra.parentMessageId`，没有该字段时按同一租户、用户、会话、应用内的
  `(create_time, id)` 顺序关联最近的前置提问，不让一个回答抵扣多条提问。
  已有但无效或无法找到的关联 ID 不回退到其他提问；终端报告未匹配数量。关联 JSON 损坏时终止导出。
  历史无关联 ID 的并发提问、跨轮重新生成无法可靠还原，只能按上述顺序推断。
- 点赞是这些提问对应回复的**当前** `liked=1` 消息数，按回复 ID 去重；取消点赞和点踩不计入。
  多条回复分别被点赞可使点赞数大于成功提问数；不是点赞按钮历史点击次数，也不是截止日期当时的点赞快照。
- 日期按北京时间筛选**提问时间**，包含首尾日期；回答查询到本次运行时刻，允许统计区间之后到达的回答，
  避免最后一天的跨午夜回复被误判为失败。数据库无时区字段默认北京时间，实际存 UTC 时传 `--db-timezone UTC`。
  固定运行时间和消息 ID 上界，查询按会话分页，`--batch-size` 默认为 100，范围 1—500。
- 范围按底层会话类型识别：`WORKSTATION=15` 为智能问答；`KNOLEDGE_SPACE=30` 且
  `flow_id=space_<空间ID>_file_<文件ID>` 为单文档问答。排除文件夹问答、工作流、助手和专家问答。
  **历史消息没有完整门户入口标记，可能包含工作台、我的知识等同类入口，不能声称仅来自门户页面。**
  不按成功 ES 事件过滤会话，避免排除全部失败、从未产生成功埋点的会话。
- **单文档问答生成失败时，提问也可能没有保存。结果仅代表现存记录，不能反映完整失败数或真实请求成功率。**
  智能问答在保存提问之前失败同样不可追溯；当前仍在生成但尚无回答的提问按无回答计入，建议生成结束后重跑。
  物理删除的提问、回复不可恢复；会话被标记删除但消息仍存在的记录继续统计。
  孤立消息或消息与会话的用户/租户/应用归属不一致，不参与统计。查询期间的点赞变化等仍受数据库读取时点影响。
- `--all-tenants` 查询全部租户；`--tenant-id` 使用项目严格租户上下文，不按人员当前组织归属重算。
  输出 UTF-8 BOM，不含用户信息和问答内容；口径、限制及查询截止时间只打印在终端。
  必须使用新输出目录；写入临时目录并完成刷盘后发布，失败退出非零、不输出半份结果、不覆盖既有报告。

### `export_user_daily_activity.py`

只读统计平台每日有效操作人数、日活比例及平均使用时长，合并数据库审计、ES 用户操作、
用户聊天消息、专家提问/回答/评论追问、资讯首次阅读记录，另附截至运行时的平台用户汇总。
无新增依赖，不修改业务数据。
从后端根目录执行，8 月 1 日至 9 月 21 日含首尾共 52 天：

```bash
python scripts/export_user_daily_activity.py \
  --all-tenants --start-date 2026-08-01 --end-date 2026-09-21 \
  --output-dir /app/user-daily-activity-0801-0921 --verbose

# 本地使用 .venv/bin/python；只统计指定租户时，将 --all-tenants 换成 --tenant-id 1。
# 可加 --config config_3002.yaml 指定已有配置。
```

- 日活：当天至少有一次有效操作的用户，跨数据库、ES、模块按全局用户 ID 去重。
  同一用户多次操作只计一人；不依赖登录记录，登录事件不计入日活、历史分母和时长。
  不排除管理员和当前停用用户，保留他们在统计日期实际发生的有效操作。
- 月活：所选日期范围内按北京时间自然月汇总有效操作用户，同一人同月跨天、跨来源只计一次。
  同一人在不同月份有操作，分别计入各月；不将每日人数相加，也不计算月日均人数。
  仅使用区间内操作，历史累计用户和结束日期之后的操作不计入月活；无操作的月份输出 0。
  每行标明统计开始时间及截止时间（不含），非整月只统计实际覆盖区间。
  例如 8 月 1 日至 9 月 21 日导出 8 月、9 月两行，9 月只覆盖 1—21 日；当天运行仍截至运行时刻。
- 分母：**截至每天累计曾有有效操作的去重人数**，每行展示为“截至当日累计有效操作人数”。
  所有操作来源均查询截至运行时的全部历史首次操作，包含 8 月以前的记录。
  历史与当日使用相同的有效操作筛选条件；区间内新增用户自首次操作当天进入分母，后续日期用户不提前计入。
  不是当前注册人数，也不是整个区间固定分母。分母为零输出 `0.00%`。
- 平均时长改用**首末操作跨度**：每个用户当日最后操作减首次操作，求和后除以当日有操作的去重人数，单位分钟。
  跨审计、ES、聊天、专家问答、资讯记录取最早/最晚时间，乱序和重复记录不重复计人。
  没有当日登录但有操作的用户也进入平均时长；只有登录而没有操作的用户不进入时长分母。
  仅一次操作时跨度为 0；当天无人操作时平均值为 0。登录事件不当作操作起点或终点。
  不跨日、不扣除中间闲置，不推测最后一次操作后的阅读时间；这是操作跨度估算，不是连续在线时长。
  平均时长的分母就是日活人数，统一认证或沿用登录态的用户只要有操作就正常计入。
- ES 包含搜索、预览、下载、收藏、问答、消息反馈、会话和应用/知识管理等用户操作。
  不用模型调用、工具调用、文件解析完成、应用处理完成或心跳推长时长。
  审计包含已定义传统操作及显式列出的审批人工操作，不包含审批自动处理/同步作业。
  业务表只读明确操作者的创建时间，不采用可能由他人或后台更新的 `update_time`。
- 全平台 `--all-tenants` 包含所有租户及无租户历史记录，跨租户按全局用户 ID 去重。
  `--tenant-id` 使用严格租户过滤，只统计记录本身归属该租户的数据，不按当前人员组织反推历史归属。
  未标租户的旧操作审计不会进入租户报表；需要整个平台人数时使用 `--all-tenants`。
- 自然日为北京时间。数据库审计/聊天/资讯无时区时间默认也按北京时间解释，
  如实际存的是 UTC，传 `--db-timezone UTC`；专家问答模型固定写北京时间，独立处理。
  操作 ES 按 epoch 秒筛选，按北京时间分日；操作用户精确 composite 分页，不使用近似 cardinality 或 Top N 截断。
- ES 使用 `get_telemetry_conf()`：优先 `telemetry_elasticsearch`，未配置则回退 `vector_stores.elasticsearch`。
  默认索引 `base_telemetry_events`，可通过 `--es-index` 指定实际原始日志别名。
  看板日汇总没有每次操作的精确时间，不能替代本脚本原始日志查询。
  `--verbose` 显示数据库各来源数量、实际 ES 主机端口、每页请求前后日志，不显示凭据或操作内容。
- 平台总用户数：从数据库读取 `mid_user_increment` 数据集的实际索引与 `total_user_count` 指标配置，
  使用看板 ES（`get_search_conf()`）及看板无时间分组时相同的 `user_id` cardinality 聚合，保留指标过滤条件和默认精度。
  不以用户表计数代替，不自行添加启用状态或 `metric_source` 过滤；数据集缺失或指标口径改变时明确报错。
  限定时间上界为本次运行时刻；`--tenant-id` 时所有表均限定该租户，汇总表会标明范围。
  对比看板时需使用相同截止时间、租户及筛选条件；看板同步延迟和 cardinality 估算仍可能影响数字。
- **输出三张 CSV，不输出用户明细或诊断文件：**
  `每日用户活跃统计.csv` 五列：日期、日活数量、截至当日累计有效操作人数、日活比例、每日用户平均使用时间(分钟)。
  `平台用户汇总.csv` 一行：统计截止时间、统计范围、平台总用户数（看板口径）、截至当前累计有效操作人数。
  `每月用户活跃统计.csv` 每月一行：月份、统计开始时间、统计截止时间（不含）、月活人数。
  “截至当前”固定为脚本启动时刻，不受 `--end-date` 限制；区间之后首次操作的用户只进入当前汇总，不进入之前日期的分母。
  CSV 为 UTF-8 BOM，可在 Excel 打开；不再导出用户明细、来源诊断和统计口径 JSON。
  计算口径、截止时间及数据留存限制在控制台显示；`--verbose` 额外显示各天活跃人数和总跨度。
  内部保留跨源去重和核对，不导出用户 ID、姓名、聊天内容或问答内容。
- 输出目录必须不存在，权限 0700；失败退出非零。索引缺失、表缺失、查询失败、ES 部分返回不会当作零数据。
  三张表均写入临时目录，全部成功后才发布结果目录；任一查询或写入失败均不发布半份结果，不覆盖已有目录。
- **限制**：只能统计现存历史记录；未采集、已清理、物理删除、延迟写入或缺失用户 ID 的记录无法还原。
  分母是“可追溯历史累计操作用户”，不是平台全部历史用户；日志不完整仍会影响人数和比例。
  资讯表仅保留用户对同一文章的首次阅读；匿名专家问答仍按内部用户 ID 计入，不输出匿名内容或姓名。
  全部来源必须可查询，旧环境缺业务表时会报错，不静默缩小数据范围。
  查询开始时固定时间上界，但数据库与 ES 无统一快照；推荐低峰运行。
  **9 月 21 日当天运行时只有截至运行时的数据**，控制台明确提示最后一天未满一天；完整结果需次日重跑。

### `export_expert_qa.py`

只读导出指定租户的专家问答，生成 `问题汇总.csv`（每题一行）和
`回答明细.csv`（每个有效回答一行，未回答问题保留一行）。使用 UTF-8 BOM，
可用 Excel 打开；自动处理逗号、引号、换行和公式文本。脚本不修改数据库，
不调用会增加浏览数的问题详情接口，不覆盖已有输出目录。

在后端根目录执行（租户 ID 以实际环境为准）：

```bash
.venv/bin/python scripts/export_expert_qa.py \
  --tenant-id 1 --output-dir /tmp/expert-qa-export

# 按提问日期筛选，起止日期均包含当天；省略日期则导出全部现存问题
.venv/bin/python scripts/export_expert_qa.py \
  --tenant-id 1 --config config_3002.yaml \
  --start-date 2026-09-01 --end-date 2026-09-30 \
  --people-csv /tmp/people.csv --output-dir /tmp/expert-qa-september
```

账号、部门、科室和专家岗位自动查询数据库，无需先填写模板。
可选的人员补充表仅填补缺失岗位，不覆盖已有岗位；使用 UTF-8 CSV，
按统一认证账号 `external_id` 精确匹配，格式如下：

```csv
external_id,岗位
employee001,技术员
```

- 部门、科室从用户唯一主组织沿父链查询最近的 `org_level=dept`、`org_level=office` 节点。
  专家无主组织时使用专家档案的所属组织；多个主组织时不任意选择。
  当前或中间组织未打标时继续向上查找至根节点；找不到的部门、科室分别留空。
  不按名称、树深度猜测。旧补充表仍可使用，但其中部门、科室列不再读取。
  普通提问人无岗位字段，岗位仍可补充。
  组织路径另列供核对。输出附带可选的 `人员补充模板.csv`，重复或空账号会报错。
- 专家岗位、职务、职位族、职位类来自当前专家档案及字典，停用专家的历史回答也保留。
  业务域保留数据库原值。姓名和组织资料不是提问或回答时的历史快照。
- 有效回答是未软删除回答；评论、追问不计入。首个有效回答时间取当前有效回答的最早时间。
  采纳数按有效回答计算；回答有用数取 `qa_answer.vote_count`，浏览数取问题累计计数。
  明细中问题统计值会重复，合计时使用问题汇总文件。
- 筛选依据是**提问日期**；回答与统计值截至导出时，不按结束日期截断回答，不能用于重建历史时点报表。
- 新时间列追加在原有列之后，无对应记录留空：
  - 问题汇总的“其它用户首次追问时间”：该问题 `qa_comment.is_follow_up=true` 的最早时间，排除原提问人，不含普通评论。
  - 回答明细的“其它用户首次点赞时间”：该回答最早的 `qa_answer_vote.vote_type=helpful` 时间，排除回答作者。
    作者优先取回答的 `user_id`，历史回答回退专家档案的用户 ID；仍无法确认作者则留空。
  - 两份表的“首次有用点击时间”：包含所有用户（含回答作者）；明细取本回答最早时间，汇总取该问题所有有效回答中的最早时间。
  - 当前后端回答点赞与有用是同一种操作；历史 `support` 类型不混入有用统计。
    只根据现存记录计算，取消或删除的历史事件无法恢复；计数存在但缺少事件记录时不推算时间。
- 问题首次采纳时间取 `resolved_at`，每条回答的采纳时间取 `qa_answer_adopt.created_at`。
  历史迁移可能用回答创建时间补填采纳时间，输出列及 `导出口径.txt` 均有提示。
- 默认遵循匿名及转公开展示标志，匿名人员的姓名、账号、组织和岗位等字段隐藏。
  本脚本面向有数据库访问权限的运维人员，导出指定租户公开与定向问题，不模拟某个页面用户的可见范围。
- 需要已有最新问答与字典表结构；不自动迁移。按 400 个问题分批读取，输出目录权限为 0700。
  导出期间尽量避免数据变更；跨批次一致性取决于数据库事务隔离级别。
- 成功退出码为 0。失败时返回非零，若目录内有 `未完成.txt`，则不能使用其中的部分文件。
  Excel 对账号列可能自动转为数字，带前导零的账号请通过“从文本/CSV”导入并指定文本类型。

### `unset_admin.py`

指定已有用户 ID, 撤销平台超级管理员: 删除 `AdminRole=1` 和 OpenFGA
`system:global#super_admin` 关系, 保留其他业务角色、部门/租户管理员权限, 缺少时补充
`DefaultRole=2`。不修改账号禁用状态、密码、部门归属或资源所有权。

从后端根目录执行, 默认只读预览, 输出 JSON 审计行:

```bash
.venv/bin/python scripts/unset_admin.py 123
.venv/bin/python scripts/unset_admin.py 123 --apply
# 指定配置文件, 参数含义与 execute_sql.py 相同
.venv/bin/python scripts/unset_admin.py 123 --config config_3002.yaml
```

- `--apply` 才写入。正式执行前需保留至少一个其他未禁用的数据库超级管理员。
- OpenFGA、Redis 必须可用。脚本只使用已有的存储和模型, 不自动创建; 存储名重复时需配置
  `openfga.store_id`。OpenFGA 关闭时会拒绝执行, 避免遗漏残留关系。
- 使用权限补偿 Worker 的 Redis 锁并续期; 锁占用时直接退出。请在维护窗口运行,
  停止对目标账号的并发授权和手工队列重放。既有 Worker 锁租期为 60 秒, 若发现超时仍在执行的
  旧补偿任务, 应先停止该任务再运行脚本; 不要强行删除正在使用的锁。
- 仅将目标超级管理员关系的待处理 `write` 补偿记录标记为 `dead`, 保留审计记录,
  并在角色变更同一事务中保存 `delete` 补偿。其他用户和其他关系不受影响。
- 数据库与 OpenFGA 不具有跨系统事务。出现 `database_committed` 后失败, 说明数据库变更已提交,
  OpenFGA 或缓存可能尚未处理完; 脚本返回非零, 不自动恢复超级管理员, 可用同一命令重试。
  不要手动复活本脚本取消的授权重试记录。
- 成功以退出码 0 且出现 `phase=verified` 为准; 默认预览退出 0 不代表已撤权。
  撤权会提升 `token_version` 并清除该用户所有租户的权限缓存, 用户需要重新登录。
  已经开始执行的请求不会被中途终止。
- 如需恢复超级管理员, 必须另行明确授权并同时恢复数据库角色和 OpenFGA 关系。

### `clear_user_points.py`

清空指定用户在指定租户下的积分, 默认账号 `wenruli`、租户 `1`。默认只读预览;
`--apply` 会将待删除的完整记录保存至 `./points-backups/*.json` (权限 0600),
再在同一事务内删除积分同步记录、补扣记录、排行榜快照、流水及积分账户。
账号按 `user_name / external_id / external_code` 精确匹配, 无匹配或不唯一时中止。
增加 `--all-users` 可清空指定租户下全部用户积分, 并同时清空该租户的收藏奖励档位。
`--all-users` 与 `--account` 互斥; 所有模式都保留其他租户数据。

```bash
# 在 src/backend 目录执行
.venv/bin/python scripts/clear_user_points.py
.venv/bin/python scripts/clear_user_points.py --apply
# 预览 / 清空租户 1 的全部用户积分
.venv/bin/python scripts/clear_user_points.py --tenant-id 1 --all-users
.venv/bin/python scripts/clear_user_points.py --tenant-id 1 --all-users --apply
# 指定其他配置; 配置加载方式与 execute_sql.py 一致
.venv/bin/python scripts/clear_user_points.py --config config_3002.yaml --apply
```

执行前暂停相关积分写入、发奖、补扣、同步和刷榜任务; 本脚本不清理 Celery 队列。
保留登录账号、积分规则、文案和站内信; 文件收藏奖励档位仅在单账号模式下保留。
流水删除会移除对应幂等记录, 重放历史任务可能重新发分; 榜单其他用户名次待刷新重算,
管理概览缓存最长 300 秒。备份是删除前快照, 不代表删除已提交; 提交后恢复需用备份单独处理。
以退出码 0 且 JSON 中 `status` 为 `已提交` 或 `无需清理` 判断写入命令成功。
不要把备份提交到 Git。

### `execute_sql.py`

连接 BiSheng 当前配置文件中的关系数据库并执行一条 SQL。脚本复用项目的
`database_url` 加载、密码解密和 MySQL/DM8/SQLite 引擎配置。查询结果默认以表格输出，
也支持 JSON、JSONL 和 CSV；默认最多输出 1000 行。

只读语句可直接执行。写入、DDL、存储过程调用以及无法可靠判定为只读的语句必须显式添加
`--apply`，成功后才会提交。可使用 `--config` 选择其他配置文件，使用 `--param` 绑定参数。

```bash
# 查询当前环境数据库
PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
  --sql "SELECT user_id, user_name FROM user LIMIT 10"

# 参数化查询并输出 JSON
PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
  --sql "SELECT * FROM user WHERE user_id = :user_id" \
  --param user_id=1 --format json

# 从文件或标准输入读取 SQL
PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
  --file /tmp/query.sql --format csv
printf 'SHOW TABLES' | \
  PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py

# 写入或 DDL 必须明确确认
PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
  --sql "UPDATE user SET update_time = CURRENT_TIMESTAMP WHERE user_id = :user_id" \
  --param user_id=1 --apply

# 使用其他配置文件；0 表示输出全部结果
PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
  --config config_3002.yaml --sql "SELECT * FROM user" --max-rows 0
```

### `sql/fill_mysql_table_column_comments.sql`

一次性 MySQL 脚本，给 COMMENT 为空的表和字段补中文备注。已有备注不覆盖，表或字段不存在则跳过，可重复执行。字段通过 `MODIFY COLUMN` 写 COMMENT，会保留原类型、默认值和自增。

必须用 mysql 客户端执行（含 `DELIMITER`，不能走 `execute_sql.py`）。请先备份，并在低峰执行：

```bash
mysql -u USER -p DATABASE < src/backend/scripts/sql/fill_mysql_table_column_comments.sql
```

文案来自 `scripts/_gen_fill_mysql_comments.py`。ORM 变更后如需重生成：

```bash
cd src/backend
PYTHONPATH=./ uv run python scripts/_gen_fill_mysql_comments.py
```

### `backfill_department_short_names.py`

根据直接父部门全称回填历史活动部门的简称。脚本扫描所有租户和所有部门来源，只处理
`short_name` 为 `NULL`、空字符串或纯空白的部门；当子部门全称以同租户直接父部门全称为
完整前缀时，截掉该前缀并将去除首尾空白后的 1～64 字符结果写入简称。

根部门、归档部门、已有有效简称、父部门缺失或跨租户、父名称不是前缀、截取结果为空或
超过 64 字符的部门均跳过并分类报告。脚本不会遍历祖先链，不会从同步载荷读取简称，也不会
覆盖人工维护值。

默认模式严格只读，只输出 JSON 审计结果：

```bash
cd src/backend
PYTHONPATH=./ .venv/bin/python scripts/backfill_department_short_names.py \
  > /tmp/department-short-name-dry-run.json
```

只有审核完整 dry-run 输出、完成数据库备份并取得独立执行确认后，才能显式写入：

```bash
PYTHONPATH=./ .venv/bin/python scripts/backfill_department_short_names.py \
  --batch-size 200 --sample-limit 100 --apply \
  > /tmp/department-short-name-apply.json
```

执行后必须再次运行 dry-run。正常情况下 `would_update` 应为 `0`，或只剩已审核确认的异常
跳过项；应分别抽样不同租户、`sg` 和其他 `source`，确认简称只来自直接父部门名称前缀。

脚本按部门 ID 进行 keyset 分批，并在写入前重新校验名称、父级、租户、状态和现有简称。
扫描后发生变化的行按 `changed_before_update` 跳过。数据库或事务错误会使当前批次回滚并以
非零状态退出；已提交批次可通过幂等重跑继续处理。脚本不提供自动回滚，误填恢复必须依赖
执行前数据库备份或经过审核的更新记录，禁止盲目批量清空简称。

## Knowledge Space Scripts

### `report_portal_knowledge_counts.py`

只读统计指定租户下全部门户知识空间, 按公共库、部门库、团队库、科室库、个人库分组导出 JSON。
个人库合并为一个组, 其他库逐库列出 ID、名称、首页获取标记、总数及两套独立的一级分类/业务域统计。

在 `src/backend` 目录执行:

```bash
.venv/bin/python scripts/report_portal_knowledge_counts.py \
  --output /tmp/portal_knowledge_counts.json

# 可指定配置和租户; 多租户模式必须明确指定租户, 每次只统计一个租户
.venv/bin/python scripts/report_portal_knowledge_counts.py \
  --config config.yaml --tenant-id 1 --page-size 500 \
  --output /tmp/portal_knowledge_counts_tenant1.json
```

- 使用现有数据库配置和租户过滤, 只初始化数据库连接。无需启动应用、ES、OpenFGA 或首页缓存,
  不创建表、不提交事务、不写业务数据。没有 `--apply` 参数。
- 输出目录必须存在, 目标文件必须不存在; 完整生成后再落地, 不覆盖已有文件。
- 范围为 `Knowledge.type=SPACE` 且未退役的全部库, 包括未开启首页获取的库和个人收藏库。
  这是一份租户库存报表, 不受某个登录用户的库访问权限限制。
- 只统计 `SUCCESS` 状态的有效文件入口。排除文件夹、回收站、历史版本、失效入口、失效逻辑文档。
  发布和共享入口保留, 按其**当前所在库**计数, 不按原始上传库归属。
- 库内按逻辑文档去重。优先使用 `reference_document_id`, 无引用时使用当前版本归属的文档 ID;
  二者冲突时排除并记录异常。旧文件没有文档关系时使用独立的文件 ID 身份, 不按文件名或 MD5 合并。
- 一级分类及业务域优先取 `split_rule` 内的结构化编码, 缺失时解析 `file_encoding`。
  `by_category`、`by_business_domain` 是两个独立维度, 不是交叉分组。
- 两个维度的每个统计项同时输出 `code` 和 `name`, 覆盖全局、大类及单库。
  分类名称优先取当前租户门户的文件分类字典, 其次是分类卡片、系统文件编码配置、内置字典;
  业务域名称优先取当前租户门户业务域配置, 其次是内置字典。停用项仍可用于历史知识的名称映射。
  未知编码显示 `未知分类 (CODE)` 或 `未知业务域 (CODE)`, 不丢失原编码和数量。
- 科室库兼容 `team_ks` 以及绑定部门的旧版用户所有 `team` 库。缺失空间分类进入 `unassigned`,
  无效部门绑定进入异常记录, 不因此隐藏库或丢弃其有效知识。空库仍列出。
- `portal_discovery_enabled` 是数据库原始开关; `portal_discovery_only` 表示按空间类型、有效部门绑定和
  开关共同判断后是否纳入首页获取范围。该字段用于标记, 不用于缩小本次统计范围。

JSON 结构:

| 字段 | 含义 |
| --- | --- |
| `schema_version` / `tenant_id` | 报表格式版本、统计租户 |
| `started_at` / `generated_at` | 开始和结束时间, 含时区 |
| `counting_rules` | 数据源、去重、分类和一致性说明 |
| `summary.space_count` / `summary.counts` | 全部库数量、全局知识汇总 |
| `groups[].counts` | 当前大类汇总 |
| `groups[].spaces[]` | 单库明细; 个人库组固定为空数组, 不展开个人信息 |
| `groups[].space_count` | 该大类实际库数量, 包括合并前的个人库数量 |
| `portal_enabled_space_count` / `portal_discovery_space_count` | 大类内开关开启库数、实际纳入首页的库数 |
| `counts.summed_count` | 各库内部去重后相加, 同一文档在两个库各计一次 |
| `counts.distinct_count` | 当前组内跨库去重后的文档数量 |
| `counts.by_category` / `counts.by_business_domain` | 每项包含 `code`、`name`、`summed_count` 和 `distinct_count` |
| `anomalies` | 异常原因、数量及最多 20 个样本 ID, 不是全部排除文件的逐条清单 |

例如同一逻辑文档分别在公共库、部门库中出现, 两库各计 1, 全局结果为:

```json
{
  "summed_count": 2,
  "distinct_count": 1,
  "by_category": [{"kind": "value", "code": "POL", "name": "政策制度", "summed_count": 2, "distinct_count": 1}],
  "by_business_domain": [{"kind": "value", "code": "PP", "name": "生产", "summed_count": 2, "distinct_count": 1}]
}
```

维度中 `kind=value` 表示正常编码, `unclassified` 表示未分类, `conflict` 表示同一文档在当前组内的
入口维度不一致, 包括一处有编码而另一处缺失。冲突文档在该组统一归入冲突项, 并附最多 20 个
`document_samples`。同一维度的两种计数分别与组内总数相等; 跨库去重数不能直接累加子组。
有分类冲突时, 父组会将对应分类转入冲突项, 所以父子组的同名分类数也不一定直接相加。

报表是数据库库存口径, 不保证等于依赖 ES 索引和缓存的首页数字。查询使用单个只读会话事务及
数据库默认隔离级别; 扫描期间的并发修改可能影响结果。文件分批读取, 去重集合仍占用与有效
文档/库组合数量成比例的内存。MySQL/DM8 使用相同 ORM 查询, DM8 实机验证需在 Linux 环境完成。

### `rebuild_knowledge_space_content_stat.py`

重建数据看板的知识空间内容统计索引 `mid_knowledge_space_content_stat`。默认模式严格只读，
报告 MySQL 当前有效文件数、ES 文件快照/预览日汇总数量、索引 `refresh_interval`，以及新旧
Redis 队列状态。默认命令不会创建、删除或更新索引，也不会修改 Redis。

```bash
# 只读预检；部署后必须先执行并保存输出
PYTHONPATH=./ uv run python scripts/rebuild_knowledge_space_content_stat.py

# 不可逆的正式重建；必须在独立最终确认后，逐字确认唯一目标索引
PYTHONPATH=./ uv run python scripts/rebuild_knowledge_space_content_stat.py \
  --apply \
  --confirm-index mid_knowledge_space_content_stat
```

正式执行前提：

- 所有 API、Celery worker 与 beat 都已部署同一新版本，旧进程已停止，避免重建后写回旧文档结构。
- MySQL、Redis、Celery 与统计 Elasticsearch 均健康；预检中的目标索引必须正好是
  `mid_knowledge_space_content_stat`。
- 已审核预检中的有效文件数、文件快照数、预览日汇总数、旧/新队列状态和当前刷新间隔。
- 已安排维护窗口并接受看板短暂为空或只显示部分文件数据；重建期间 30 秒文件可见性和
  5 秒预览可见性 SLO 均视为降级，不适用。
- 已取得运行时预检后的单独最终确认。实现或测试阶段不得运行 `--apply`。

风险与回退：正式模式会直接删除原索引，不迁移历史预览数据，历史预览次数会永久清零，
无法通过脚本回滚。文件快照可以再次从 MySQL 全量重建；预览历史不能恢复，除非另有外部备份。
脚本使用与全量/增量消费者相同的 owner lock，回收遗留 processing，按新 mapping 创建索引并
显式设置 `refresh_interval=1s`，全量重建后清理精确旧队列键；释放锁后如仍有 pending，会立即
重新调度增量同步。锁繁忙、失锁或依赖异常会返回非零退出码并在 JSON 中标记 `degraded` 和
`failure_stage`。

运行后验证：

- 退出码为 `0`，结果中 `degraded=false`、`owner_lock_released=true`。
- `result.index.refresh_interval` 为 `1s`，`preview_daily_count` 为 `0`。
- `result.index.file_snapshot_count` 与 `preflight.source_file_count` 一致；若执行期间有业务变更，
  等 pending 消费完成后再次核对。
- 新建或更新一个文件，人工计时验证 30 秒内看板可查；预览一个已有快照的文件，人工计时验证
  5 秒内当日 `preview_count` 增加。异常或积压时记录为降级，不把该次计时作为 SLO 达标证据。

### `knowledge_document_distribution_preflight.py`

F059 单实体发布/分享上线前只读检查。校验三张核心表、文档 tenant 可唯一反推、
`knowledge_file_id` 唯一版本关系、单 manager/同空间单入口、逻辑入口无物理负载、
旧复制发布痕迹和 MinIO 图片路径不依赖知识库 ID。任一阻断项返回退出码 `2`，
可直接作为打开 `knowledge.distribution.writer_enabled` 前的发布门禁。

```bash
PYTHONPATH=./ .venv/bin/python \
  scripts/knowledge_document_distribution_preflight.py
```

### `backfill_knowledge_file_original_origin.py`

回填历史 `knowledgefile.original_uploader_id/original_knowledge_id`。脚本覆盖所有租户的
`SPACE + FILE` 业务行，包含软删除文件和 manager/publish/share 入口，排除
`file_source=favorite_reference` 的收藏快捷引用和 `projection_tombstone` 清理占位。默认是纯
dry-run；不会随 Alembic、应用启动或部署自动执行，只有显式传入 `--apply` 才写数据库。

来源规则：

- 普通文件使用自身 `user_id/knowledge_id`。
- 旧复制发布沿 `user_metadata.shougang_portal_publish.source_file_id` 追到根文件。
- F059 数据以同一 `KnowledgeDocument` 的所有 version 和 reference entry 为原子组；已有一致的
  非空原始事实优先，否则通过 publish 前驱根或首版本确定。
- 断链、循环、跨租户、缺少上传人、已有值冲突均失败关闭。历史目标版本合并与多版本后发布在旧字段上
  无法唯一辨别且没有可信已有值时，也整组跳过，不使用当前属性猜测。
- 任意已有非 `NULL` 字段都不会覆盖；apply 写入前会锁定并重新解析，只更新仍为 `NULL` 的字段。

```bash
# 1. 全量只读扫描，保存 JSON 输出供评审
PYTHONPATH=./ .venv/bin/python \
  scripts/backfill_knowledge_file_original_origin.py \
  > /tmp/original-origin-dry-run.json

# 2. 按租户、知识库或单文件收窄范围；单文件属于 canonical 时会扩展到整个组
PYTHONPATH=./ .venv/bin/python \
  scripts/backfill_knowledge_file_original_origin.py \
  --tenant-id 7 --knowledge-id 100 --limit 500 --batch-size 100

PYTHONPATH=./ .venv/bin/python \
  scripts/backfill_knowledge_file_original_origin.py --file-id 123

# 3. 审核 dry-run、完成数据库备份并取得独立执行授权后再写入
PYTHONPATH=./ .venv/bin/python \
  scripts/backfill_knowledge_file_original_origin.py \
  --tenant-id 7 --batch-size 100 --apply

# 4. 中断后使用上一份报告的 next_start_after_id 续跑
PYTHONPATH=./ .venv/bin/python \
  scripts/backfill_knowledge_file_original_origin.py \
  --tenant-id 7 --start-after-id 5000 --batch-size 100 --apply

# 5. 同一范围再次 dry-run；would_update 应为 0
PYTHONPATH=./ .venv/bin/python \
  scripts/backfill_knowledge_file_original_origin.py --tenant-id 7
```

过滤和报告约定：

- `--tenant-id/--knowledge-id/--file-id` 选择候选种子；命中 canonical 后，为保证一致性会锁定并处理
  整个同租户 canonical 组，因此组内行可能位于所选知识库之外。
- `--limit` 限制按 ID 稳定排序的候选种子行数，不限制 canonical 展开后的行数；`--batch-size`
  控制每批种子数量。
- `--start-after-id` 是排他游标。报告的 `next_start_after_id` 是本次最后扫描的种子 ID；若修复了先前
  跳过的数据，应使用 `--file-id` 或从更早游标重新 dry-run，不能直接越过它。
- `scanned` 是候选种子行数，`eligible` 是解析和写前复核后仍缺字段的目标行数，`would_update/updated`
  分别是 dry-run/apply 的目标行数；`skipped/conflict/broken_chain/reason_counts/samples` 用于审计失败关闭结果。
- apply 按批次提交，单个 canonical 组使用保存点避免部分写入；中断后安全重跑。正式执行前必须备份
  `knowledgefile`，保存全量 dry-run 报告并先做单文件、小批量灰度。脚本本身不提供错误来源值的回滚；
  回退依赖执行前数据库备份。

### `reconcile_knowledge_document_projection.py`

按 tenant 和 entry 检查或重新调度单个 F059 ES/Milvus 投影。默认只读，输出代次、状态、
重试次数、原错误、租约和恢复阻塞原因；传入 `--apply` 才向默认 `celery` 队列调度任务。
普通调度不会重置耗尽次数；重置失败入口必须同时传入 `--recover-failed --apply`、
执行人、修复说明和 JSONL 审计路径。支持失败的管理入口及待清理的发布、分享、tombstone 入口。

```bash
PYTHONPATH=./ .venv/bin/python \
  scripts/reconcile_knowledge_document_projection.py \
  --tenant-id 1 --entry-id 123

PYTHONPATH=./ .venv/bin/python \
  scripts/reconcile_knowledge_document_projection.py \
  --tenant-id 1 --entry-id 123 --apply

# 先只读核对；不会重置次数或派发任务
PYTHONPATH=./ .venv/bin/python \
  scripts/reconcile_knowledge_document_projection.py \
  --tenant-id 1 --entry-id 123 --recover-failed

# 仅在上游故障已修复、预览无阻塞且获准恢复数据后执行
# 审计文件父目录须已存在，建议使用持久卷
PYTHONPATH=./ .venv/bin/python \
  scripts/reconcile_knowledge_document_projection.py \
  --tenant-id 1 --entry-id 123 --recover-failed --apply \
  --operator '<执行人>' --reason '<上游故障修复说明>' \
  --audit-file /data/audit/projection-recovery.jsonl
```

恢复前会校验租户、失败状态、有效租约、主版本/物理文件元数据和目标管理入口是否已就绪。
这不代表已经验证 MinIO 对象、解析服务或 ES/Milvus/OpenFGA 的实时可用性，仍须先修复上游故障。
处理顺序是管理入口恢复并追平代次，再逐条恢复依赖它的清理入口。工具不改变入口归属、代次和文件内容。

原错误和次数先以 `prepared` 审计落盘；数据库提交后追加 `committed` 审计。若提交后审计或派发失败，
退出码为 3，并输出 `recovery_status=committed` 和 `recovery_id`。此时不可当作未执行：应先检查审计和入口，
周期扫描会继续处理已恢复的 pending 任务。若只有 prepared 且提交结果不明，应先核对数据库及 Worker 日志。
恢复后任务可能立即被 Worker 领取并写入外部存储，不支持仅回填原重试字段来撤销已执行的清理。

### `dedupe_department_space_documents.py`

删除部门知识空间中与公共知识空间重复的逻辑文档。脚本只比较两类空间当前主版本中
`file_type = FILE`、`status = SUCCESS` 且非空的精确 MD5；命中后以逻辑文档为单位删除部门侧
全部历史版本。没有版本关系的兼容数据以单个物理文件为删除单元。公共空间文档和目录始终保留。

默认 dry-run，只读取数据并在 `migration_reports/knowledge_file_dedup/` 生成 JSON 审计报告；
只有显式传入 `--apply` 才会依次清理部门侧 Milvus、Elasticsearch、MinIO、OpenFGA、数据库关系
和物理文件。脚本仅支持未启用多租户的部署。

用法：

```bash
# 全量只读扫描
PYTHONPATH=./ .venv/bin/python scripts/dedupe_department_space_documents.py

# 按部门空间或当前文件收窄 dry-run 范围；参数可重复
PYTHONPATH=./ .venv/bin/python scripts/dedupe_department_space_documents.py \
  --department-space-id 10 --file-id 201 --limit 20

# 审核 dry-run 报告并安排维护窗口后，重新扫描并执行真实删除
PYTHONPATH=./ .venv/bin/python scripts/dedupe_department_space_documents.py \
  --department-space-id 10 --limit 20 --apply

# 仅使用先前 apply 报告恢复未完成单元；不可同时指定范围参数
PYTHONPATH=./ .venv/bin/python scripts/dedupe_department_space_documents.py \
  --apply --resume-report migration_reports/knowledge_file_dedup/dedupe-RUN_ID.json
```

Safety and reports:

- `--department-space-id`、`--file-id` 可重复；`--limit` 在稳定排序后限制删除单元数。
- 每个删除单元在写入前都会重新读取并校验空间级别、当前版本、精确 MD5、公共见证和版本链指纹；
  数据漂移时跳过，不使用旧报告直接决定新的删除目标。
- JSON 报告记录目标版本链、公共见证、关联影响计数、分步状态和删除后核验结果，并通过原子替换写入。
- 标签、审核标签、分享、相似候选和门户推荐投影随部门文件关系清理；收藏引用与审计记录保留，报告中给出影响计数。
- 任一单元失败后停止后续删除并返回非零退出码。`--resume-report` 只接受先前的 apply 报告，校验报告结构和指纹后
  恢复失败或待处理单元；已完成或已安全跳过的单元不会重复处理。
- `--apply` 是跨 MySQL、Milvus、Elasticsearch、MinIO、OpenFGA 的不可逆数据删除，不能提供原子回滚。
  正式执行前必须完成备份、审核 dry-run 报告、单文件烟测和小批量灰度，并在维护窗口内运行。

Exit codes:

- `0`：dry-run 完成，或所有 apply 单元已完成/安全跳过。
- `2`：参数、单租户约束、目标范围或恢复报告预检失败。
- `3`：扫描或初始化失败。
- `4`：真实删除、分步核验或恢复执行失败。
- `5`：审计报告无法持久化；脚本不会在该状态下继续新的业务删除。

### `dedupe_knowledge_space_documents.py`

门户知识库**库内去重**：公共、部门、班组/科室、个人知识库分别比较，不同文件夹一起比较，
不同库之间不判重。以当前主版本非空 MD5 分组（忽略首尾空白和十六进制字母大小写），保留
当前主版本文件 `create_time` 最新的文档；时间相同时保留主版本文件 ID 较大的，若多个
分发入口引用同一主版本，再按入口 ID 较大者保留。历史版本不作为独立候选。

```bash
# 从 src/backend 执行；默认只预览，不需要操作用户，不触发删除或异步任务
.venv/bin/python scripts/dedupe_knowledge_space_documents.py

# 收窄到指定知识库，可重复指定 --space-id；报告路径必须是新文件
.venv/bin/python scripts/dedupe_knowledge_space_documents.py \
  --space-id 10 --space-id 20 --report-file /tmp/space-dedup-preview.jsonl

# 审核预览结果，在维护窗口执行；自动使用有效超级管理员
.venv/bin/python scripts/dedupe_knowledge_space_documents.py \
  --space-id 10 --apply

# 多租户部署必须显式选定租户，每次只处理一个租户
.venv/bin/python scripts/dedupe_knowledge_space_documents.py --tenant-id 2
```

- 不指定 `--space-id` 时扫描当前租户所有有门户层级、处于正常状态的知识空间。
- 跳过 MD5/上传时间缺失、解析未成功、历史版本正在处理、审批未结束、回收站、分发投影未就绪、
  版本链缺失或归属异常的数据，报告具体原因。文件夹不参与去重，也不删除文件夹。
- apply 自动查找系统中未禁用且身份验证通过的全局超级管理员，不需要指定操作用户。
  候选来自 OpenFGA 授权和兼容管理员角色，按用户 ID 从小到大选择有效账号；没有可用账号时终止。
  不创建账号或修改权限。选中的账号写入报告 `operator` 事件，文档查询仍限制在目标租户。
  继续使用现有业务删除入口和写入冻结检查。
  每次删除前重查当前知识库、当前主版本、历史版本链及相关引用；发现变化即停止，重新预览后再运行。
- 调用现有 `KnowledgeSpaceService.delete_file()`：普通文档按业务规则连同版本链进入回收站；
  脚本内装配所需服务和仓储，不依赖 `filelib_sync_factory` 中新增的工厂函数。
  发布/分享文档走现有分发生命周期，可能回退管理权或使其他库引用失效。不额外保留独有历史版本，
  也不绕过业务执行物理删除。回收站数据按现有回收站能力处理；分发生命周期可能不可恢复。
- 若预计业务级联会影响本轮任一重复组的保留项，在预览 `blocked` 中列出，并在 apply 中跳过。
  不自动改选较旧文档或重建引用。出现该情况返回 `6`，表示仍有重复项待处理。
- 默认报告目录为 `migration_reports/knowledge_space_dedup/`。JSONL 依次记录 `run`、`operator`（仅 apply）、`plan`、
  `delete_started`、`delete_result`、`summary`，以及必要的 `skipped`、`stopped`、`failed` 或 `aborted`。
  `groups` 包含保留/删除项、MD5、库名、文件夹、主版本时间、历史文件 ID、关联入口 ID。
  报告文件独占创建且逐条落盘；落盘失败会停止，不继续删除。
  `failed.failure_stage = service_setup` 表示删除服务初始化失败，尚未调用业务删除；
  `delete_or_verify` 表示调用业务删除或核验期间失败，需要核对实际数据状态。
- `soft_deleted` 表示进入回收站，`removed` 表示入口已不存在，`pending_cleanup` 表示业务状态已转换，
  `rolled_back_pending_cleanup` 表示管理文档已退回上一发布库、原库清理仍在等待。
  **不代表 MinIO、Milvus、Elasticsearch、权限等异步清理已完成**；需保持对应 Worker/Beat 正常运行。
- 没有跨会话全局写锁，也没有跨存储原子回滚。维护窗口内暂停上传、版本修改、审批和分发操作，
  先备份并按知识库小范围执行。部分失败时先核对报告与业务状态；再次运行会重新计算，不重放旧报告。
- 首次扫描读取当前范围及其引用所需的元数据到内存；逐项复核只读取当前库及相关引用。
  大数据量时用 `--space-id` 分库运行。脚本不读取原文件内容来补算空 MD5。

退出码：`0` 为扫描完成或本轮删除请求及状态核验完成（异步清理可仍在等待）；`2` 为参数/预检失败；
`3` 为初始化、扫描或报告写入失败；`4` 为业务删除或删除后核验失败；`6` 为状态变化中止或保留项冲突，
需要核对后重新预览。

### `relink_duplicate_space_files_as_publish.py`

把多知识空间中的相同当前主版本转成 F059 软链接：最高级空间保留物理原文件（`manager`），
严格下级空间原地改成 `entry_type=publish`（保留 `file_id`，预览走原文件，默认禁止下载）。
同级多库（例如两个部门库同一 MD5）不互转。空 MD5 用 `文件名+大小` 兜底。下级独有历史版本
留在原空间，并写入报告供人工处理。仅支持未启用多租户的部署。

默认 dry-run，报告同时写 JSON 和 Markdown 到 `migration_reports/knowledge_file_relink/`
（`relink-{run_id}.json` / `relink-{run_id}.md`）；只有 `--apply` 才会改库、
删除下级副本的 Milvus/ES/MinIO，并入队投影。从已有 JSON 恢复时仍只认 `.json`。

用法：

```bash
# 全量只读扫描
PYTHONPATH=./ .venv/bin/python scripts/relink_duplicate_space_files_as_publish.py

# 按空间 / 文件 / MD5 收窄；参数可重复
PYTHONPATH=./ .venv/bin/python scripts/relink_duplicate_space_files_as_publish.py \
  --space-id 10 --file-id 201 --md5 same-md5 --limit 20

# 审核 dry-run 报告并安排维护窗口后执行
PYTHONPATH=./ .venv/bin/python scripts/relink_duplicate_space_files_as_publish.py --apply

# 从上次 apply 报告恢复未完成单元
PYTHONPATH=./ .venv/bin/python scripts/relink_duplicate_space_files_as_publish.py \
  --apply --resume-report migration_reports/knowledge_file_relink/relink-RUN_ID.json
```

Safety and reports:

- 库级从高到低：`public` > `department` > `team`/`team_ks` > `personal`。只转换严格下级。
- 部门库只把**本部门组织树下**的科室库/团队库改成软链；其他部门的科室/团队库不挂到该部门。
  公共库仍可对全租户下级做软链。未绑定组织节点的自由团队库不会挂到部门库。
- 每个单元在写入前重新扫描并校验 origin/source/匹配键；数据漂移时跳过。
- 下级已是带分发下游的 manager（例如已正式发布到科室并留下 publish/share）时跳过该条，不中止整轮。
- 报告同时写 JSON（机器可读，可 `--resume-report`）和 Markdown（中文汇总、库级分布、转换/跳过/历史版本明细，含文件名、库名、目录）。
- `--apply` 不可逆地清空下级物理载荷；公共/最高库原文件和 OpenFGA 本地权限保留。
  正式执行前必须备份、审核 dry-run、单文件烟测和小批量灰度。

Exit codes:

- `0`：dry-run 完成，或所有 apply 单元已完成/安全跳过。
- `2`：参数、单租户约束或恢复报告预检失败。
- `3`：扫描或初始化失败。
- `4`：转换、外部清理或核验失败。
- `5`：审计报告无法持久化。

### `strip_abstract_labels.py`

剥离历史 `knowledgefile.abstract` 中由旧摘要 prompt 写入的装饰标签（`【文档类型】` / `【摘要】`）。门户详情已有「文档摘要」标题，这些前缀会造成重复展示。默认 dry-run；传入 `--apply` 后写回 MySQL（不刷 ES）。清洗逻辑与入库 `AbstractTransformer` 共用。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py
PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py --apply
PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py --apply --file-id 123
PYTHONPATH=./ .venv/bin/python scripts/strip_abstract_labels.py --apply --limit 500
```

Scope:

- 仅 MySQL `knowledgefile.abstract`
- 候选条件：`abstract` 含 `【摘要】` 或 `【文档类型】`
- 不重跑 LLM、不重解析、不更新 ES `metadata.abstract`

### `backfill_file_similarity_candidates.py`

回填历史知识空间文件的相似候选缓存表 `knowledge_file_similarity_candidate`。默认 dry-run，只统计将刷新的文件；传入 `--apply` 后会逐个调用相似候选刷新逻辑，写入候选明细并同步更新 `knowledgefile.similar_status`。可通过 `--sleep-ms` 降低回填期间 CPU 压力。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply --knowledge-id 3516
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply --limit 200 --batch-size 20 --sleep-ms 100
```

Scope:

- 仅处理知识空间 `Knowledge.type = SPACE`
- 仅处理真实文件、解析成功、未处理完成的文件：`file_type = FILE`、`status = SUCCESS`、`similar_status != 2`
- 跳过没有有效 `simhash` 或没有有效前三段 `file_encoding` 的文件

### `repair_false_positive_simhash_duplicates.py`

修复跨文件 SimHash 撞号导致的"100% 相似文档"误报（根因未定位，见
`bisheng/knowledge/rag/pipeline/transformer/simhash.py` 里的 `[simhash.diag]`
诊断日志）。自动筛选同一个 `simhash` 下 `md5`（真实内容）互不相同的文件数
达到阈值（默认 3）的可疑分组，逐个重新读取文件内容并按解析管线同款逻辑
重算 SimHash；只写回 `knowledgefile.simhash` 一个字段，`status`、
`split_rule` 等其余数据不动。重算失败的文件把 SimHash 清成算法自身定义的
空文本零值（`"0"*16`，全仓库既有的"无有效 SimHash"占位），不留错误值。
不论重算成功与否，都会清掉该文件在 `knowledge_file_similarity_candidate`
里的候选记录（作为来源和作为候选两个方向都清），避免界面上继续挂着错误
的"相似文档"提示。默认 dry-run，`--apply` 才写库；严格串行，不做任何并发。

```bash
PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py
PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py --apply
PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py --apply --limit 50
PYTHONPATH=./ .venv/bin/python scripts/repair_false_positive_simhash_duplicates.py --apply --min-distinct-content 5

bash scripts/repair_false_positive_simhash_duplicates.sh --apply
```

说明：

- `--min-distinct-content`：判定"可疑"的最小 distinct md5 数，默认 3，跟排查时用的 SQL 阈值一致。
- `--limit`：最多处理多少个命中文件，用于先小批量验证。
- 每个文件重算前后都会打印一行 `file_id/outcome/old_simhash/new_simhash`，方便核对。
- 不重跑标签、分类、业务域、解析状态等任何其他字段，也不触发重新解析。

### `backfill_knowledge_fulltext.py`

将当前存量可索引文件提交给既有全文索引 Outbox/Worker 链路。脚本只扫描 MySQL 当前事实并创建
`file + sync_current` 请求；不读取 RAG Chunk、不拼接正文、不直接写全文 Elasticsearch，也不会
删除、重建或切换索引。默认是 dry-run，只有显式传入 `--apply` 才写 Outbox。

建议按以下顺序执行：

```bash
# 1. 全量只读预检并保存自动生成的 JSON 报告
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_fulltext.py

# 2. 单文件灰度；等待的成功条件为 applied_revision >= 本批 target_revision
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_fulltext.py \
  --file-id 1829 --apply --wait --verify-es

# 3. 单知识库灰度，并在每个已提交批次后限速
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_fulltext.py \
  --knowledge-id 198 --batch-size 50 --sleep-ms 500 --apply --wait --verify-es

# 4. 全量 apply 仅在另行取得生产运维确认后执行；默认提交完 Outbox 即退出
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_fulltext.py \
  --batch-size 200 --sleep-ms 500 --apply

# 5. 等待阶段中断后，从原 apply 报告恢复；不会生成新 revision
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_fulltext.py \
  --resume-report migration_reports/knowledge_fulltext_backfill/backfill-RUN_ID.json \
  --wait --verify-es

# 6. 扫描阶段中断后，使用报告中的排他游标继续，必要时限制总扫描量
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_fulltext.py \
  --start-after-id 5000 --limit 10000 --batch-size 200 --apply
```

报告位于 `migration_reports/knowledge_fulltext_backfill/`：JSON 摘要记录参数、候选/排除统计、
下一游标、有限脱敏失败样例和等待/校准结果；同名 `.targets.jsonl` 只记录已提交的
`file_id/outbox_id/target_revision`。报告采用原子摘要替换和已提交行计数，进程在数据库提交与报告
落盘之间退出时，可以从未推进的游标安全重跑；重复范围只会产生更高 revision，不会产生重复 ES `_id`。

运行约束与风险：

- 启动时只读校验单租户模式、Outbox 表、全文活动别名、Mapping 和 Analyzer；预检不会调用
  `ensure_index()`，因此不会创建或升级索引。
- `--limit` 限制扫描的文件 ID 数，`--batch-size` 范围为 1～1000，`--start-after-id` 为排他游标；
  已存在于全文 ES 的文档仍会重新同步。
- 不带 `--wait` 的 apply 只保证 Outbox 已提交，正文由默认 Celery Worker 异步构建；Beat 仅作为
  低频漏投补偿。`--wait` 超时不会取消 Outbox。
- `--verify-es` 是观察时点的只读 ID 对账；业务并发变化可能造成候选数与 ES 命中数短暂漂移，
  应结合 target revision 状态判断，不能直接视为数据丢失。
- 全量回写会让 Worker 读取每个候选文件的全部 RAG Chunk，并重建 1～20 字符 ngram。必须先保存
  全量 dry-run 报告，再做单文件和单知识库灰度，观察默认 Celery 队列、RAG ES、目标 ES CPU、磁盘、
  Segment Merge 和写入耗时；正式全量 `--apply` 需要独立运维确认。

退出码：`0` 成功；`2` 参数/单租户/数据库/索引预检失败；`3` 扫描、Outbox 或执行失败；
`4` target revision 失败或等待超时；`5` 报告初始化或持久化失败。

### `backfill_file_subcategories.py`

补全历史空间知识库文件的二级分类。默认 dry-run 只扫描全部租户中
`SPACE + FILE + SUCCESS + file_subcategory_code 为空` 的记录，不读取门户配置、
Elasticsearch，不调用 AI，也不写数据库。

传入 `--apply` 后，脚本使用文件所属租户的门户分类树：仅有一个合法子分类时
直接保存并标记 `fallback`；存在多个候选时，读取 Elasticsearch 正文开头 1500
字符，结合文件名和摘要调用工作台 LLM。AI 最多调用 3 次，全部失败后保持空值。

Usage:

```bash
# 先执行全库只读统计
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py

# 先对单个文件执行正式烟测
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py --apply --file-id 123

# 按租户或知识库灰度
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py --apply --tenant-id 2 --limit 100
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py --apply --knowledge-id 3516

# 分批限流后执行
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_subcategories.py --apply --limit 500 --batch-size 20 --sleep-ms 100
```

Operational notes:

- `--tenant-id`、`--knowledge-id`、`--file-id` 可收窄处理范围；`--limit`、`--batch-size`、`--sleep-ms`
  用于控制单次规模和 Elasticsearch/LLM 压力。
- `file_encoding` 无效、租户门户配置不可用、无合法子分类、ES 无正文、模型未配置或
  AI 三次失败均会保持数据不变，并在结束摘要和标准错误详情中说明原因。
- 写入前会再次原子检查分类仍为空，不覆盖人工或其他任务的并发填充；已成功记录不会在
  重跑时再次处理。
- `--apply` 会产生 Elasticsearch 读取压力和 AI 调用成本，并修改历史数据。脚本不提供自动回滚，
  正式全库执行前应依次完成 dry-run、单文件烟测和小批量灰度。

### `backfill_knowledge_space_auto_tags.py`

扫描知识空间文件，对**可见标签总数少于 3** 且解析成功的文件补跑 Link A / Link B AI 打标签流程；补打后单文件可见标签总数不超过 **6**。
内容优先从 Elasticsearch 分块读取，缺失时回退到 `abstract`。默认 dry-run，传入 `--apply` 后才会调用 LLM。

用法：

```bash
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_auto_tags.py
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_auto_tags.py --apply
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_auto_tags.py --apply --space-id 10
PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_auto_tags.py --apply --batch-size 20 --concurrency 2 --limit 100

bash scripts/backfill_knowledge_space_auto_tags.sh --apply --batch-size 20

# Docker 容器内（WORKDIR /app，使用系统 python，无 .venv）：
PYTHONPATH=./ python scripts/backfill_knowledge_space_auto_tags.py --apply --min-tags 3 --max-tags 6
bash scripts/backfill_knowledge_space_auto_tags.sh --apply --min-tags 3 --max-tags 6
```

说明：

- 只处理 `status=SUCCESS` 的真实文件；默认 `--min-tags 3`（少于 3 个才处理）、`--max-tags 6`（补打后总数上限）。
- 默认沿用线上 Link A/B 的 `_should_run` 门禁，可用 `--force` 绕过。
- `--scan-batch-size` 控制标签统计分批大小；`--batch-size` 控制实际打标签分批大小。
- Link B 是否执行仍受 `review_tag_visible`、空间 `auto_tag_enabled`、Link A 应用标签数上限，以及 `--max-tags` 剩余额度约束。

### `resync_tag_library_name_lists.py`

把标签库自己那份**名字清单**（`tags` / `ai_tags` / `tag_count`）对齐到 `tag` 表。标签管理页面早期版本的删除/添加/移动只改了 `tag` 表没同步清单，导致左侧标签库计数不准；更严重的是某个库被**删空**后清单还在，会被"自愈"逻辑误判成"迁移漏了这个库"，在有人打开该库详情时照着清单把标签重建出来 —— 表现为"删掉的标签又回来了"。

用法：

```bash
PYTHONPATH=./ .venv/bin/python scripts/resync_tag_library_name_lists.py
PYTHONPATH=./ .venv/bin/python scripts/resync_tag_library_name_lists.py --apply
PYTHONPATH=./ .venv/bin/python scripts/resync_tag_library_name_lists.py --apply --library 2 --library 7

# Docker 容器内（WORKDIR /app）：
python scripts/resync_tag_library_name_lists.py
```

说明：

- **有标签行、但清单对不上** → 自动对齐（标签行是权威数据）。
- **0 行标签、但清单非空** → **默认跳过**，必须 `--library <id>` 显式点名。这种状态有两种完全相反的来源，数据上无法区分：库被人为删空（清单该清），或该库当年没迁移过、标签只活在清单里（清空等于删光该库标签）。
- 只改标签库那三个字段，不新增或删除任何 `tag` 行。
- 需要带 `TagLibraryTagService.sync_library_name_lists` 的版本才能 `--apply`。

### 公共标签库合并到「通用标签库」

把其它**公共**标签库里的正式标签归属到「通用标签库」，并把全部知识空间绑定到该库。
**不改 `tag.id`**（文件关联 `taglink` 不用动），**不改待审核表**，也不删除源标签库。

必须按顺序跑三个脚本。工作目录均为 `src/backend`。脚本会绕过租户过滤器；连哪套库由当前 `config` 决定。备份是数据库内的 `*_bak` 表，不是文件。

#### 1. `backup_tag_library_migration.py`

把三张表整表复制为 `原表名_bak`：`tag_bak`、`knowledge_tag_library_link_bak`、`knowledge_space_tag_library_bak`。默认 dry-run，`--apply` 才建表。备份表已存在时必须加 `--force` 才会先删后重建。

```bash
PYTHONPATH=./ .venv/bin/python scripts/backup_tag_library_migration.py
PYTHONPATH=./ .venv/bin/python scripts/backup_tag_library_migration.py --apply
PYTHONPATH=./ .venv/bin/python scripts/backup_tag_library_migration.py --apply --force
bash scripts/backup_tag_library_migration.sh --apply
```

#### 2. `rollback_tag_library_migration.py`

回滚时对每张表：现表改名为 `原表名_ori`，再把 `原表名_bak` 改回原名。默认 dry-run。若上次回滚留下了 `_ori`，加 `--force` 先删掉再改名。

```bash
PYTHONPATH=./ .venv/bin/python scripts/rollback_tag_library_migration.py
PYTHONPATH=./ .venv/bin/python scripts/rollback_tag_library_migration.py --apply
PYTHONPATH=./ .venv/bin/python scripts/rollback_tag_library_migration.py --apply --force
bash scripts/rollback_tag_library_migration.sh --apply
```

回滚后 `_bak` 不再存在（已改回原名），`_ori` 里是迁移后的那份数据，确认无误后可手工 `DROP TABLE`。回滚只能做一次，除非再次备份。

#### 3. `migrate_tags_to_general_library.py`

每个租户必须已有一座名为「通用标签库」的公共库。将其余公共库的 `tag.business_id` 改到通用库；给所有 `type=知识空间` 的库补上通用库绑定，并去掉其它公共库绑定。默认 dry-run。

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_tags_to_general_library.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_tags_to_general_library.py --tenant 1
PYTHONPATH=./ .venv/bin/python scripts/migrate_tags_to_general_library.py --apply
bash scripts/migrate_tags_to_general_library.sh --apply
```

说明：

- 先跑备份 `--apply`，再迁移 dry-run，确认输出后再迁移 `--apply`。
- 同名标签并入同一座库时**不会合并**（id 保持不变），dry-run 会打印警告。
- 并入后超过 999 行会拒绝执行。
- 私有库（`owner_knowledge_id` 非空）的标签和绑定不动。
- 源库留空壳，便于待审行继续指向原 `business_id`；待审清完后再手工删库。

### `merge_duplicate_approved_tags.py`

合并**审核通过时产生的重复标签行**。修复前，通过一个标签会写两次：一次把标签名注册进审核人选的标签库（提报者记成审核人、无审核留痕、无文件关联），一次把审核记录搬进 `tag` 但标签库取的是提出该标签的库。结果一次通过留下两行，落在两个不同的标签库里。

按 `(tenant_id, name)` 分组，组内**没有文件关联且创建时间更晚**的那行是审核人选的库（保留），**有文件关联且更早**的那行是数据来源（合入后删除）。默认 dry-run。

用法：

```bash
PYTHONPATH=./ .venv/bin/python scripts/merge_duplicate_approved_tags.py
PYTHONPATH=./ .venv/bin/python scripts/merge_duplicate_approved_tags.py --tenant 1
PYTHONPATH=./ .venv/bin/python scripts/merge_duplicate_approved_tags.py --apply

# Docker 容器内（WORKDIR /app）：
python scripts/merge_duplicate_approved_tags.py
```

说明：

- 只处理**刚好两行、且能明确区分保留行/数据行**的组。三行以上、两行文件关联情况相同、创建时间无法区分先后的，一律跳过并打印原因，交人工判断。
- 只碰 `business_type='tag_library'` 的行，应用标签 / 知识标签不受影响。
- 单次事务，失败整体回滚；`--apply` 才会写库。
- 仅适用于已经升级到带 `tag.reviewer_id` / `tag.review_time` 的环境；老版本库结构不会产生这种重复。

### `backfill_word_pdf_preview.py`

给**存量 Word 文件**补生成 PDF 预览。新上传的 Word 在解析时会把 .docx 预览转成 PDF 存到 `preview/{file_id}.pdf` 并记到 `user_metadata.pdf_preview_object_name`，前端优先用它（LibreOffice 排版更接近 Word，避免电子印章/图形错位）。此功能上线前解析的旧文件没有这个字段，预览会回退到 .docx —— 本脚本离线复刻同样的步骤给这些文件补齐。串行执行，幂等（`pdf_preview_source_md5` 已匹配当前 md5 的跳过）；默认 dry-run，传 `--apply` 才转换并写库。

用法：

```bash
PYTHONPATH=./ .venv/bin/python scripts/backfill_word_pdf_preview.py            # dry-run，仅列出待处理文件
PYTHONPATH=./ .venv/bin/python scripts/backfill_word_pdf_preview.py --apply
PYTHONPATH=./ .venv/bin/python scripts/backfill_word_pdf_preview.py --apply --space-id 202 --limit 50
bash scripts/backfill_word_pdf_preview.sh --apply --limit 50

# Docker 容器内（WORKDIR /app，使用系统 python，无 .venv；容器里已装 LibreOffice）：
PYTHONPATH=./ python scripts/backfill_word_pdf_preview.py --apply
```

说明：

- 只处理 `status=SUCCESS`、扩展名为 `doc/docx/wps` 的真实文件。
- 转换源优先取解析产出的 `preview/{id}.docx`，缺失时回退到原始 `.doc/.docx`。
- 每个文件转换失败只记日志并继续，不中断整批（预览是尽力而为）；`--timeout` 控制单文件 LibreOffice 超时（默认 120s）。
- `--force` 可对已有 PDF 的文件强制重转。

### `reparse_knowledge_space_files.py`

重新解析知识空间文件。默认 dry-run，只统计将处理的文件；传入 `--apply` 后会直接在脚本进程内执行解析，默认单并发，可通过 `--concurrency` 调整。每个文件重解析前只清理该文件在 Milvus 和 Elasticsearch 中的旧索引，不删除 MinIO 原文件或预览产物。

始终排除 `deleted_at` 非空的逻辑删除文件，显式指定 `--file-id` 或执行中状态参数也不会绕过；指定已删除目录时不展开其内容。每个文件执行前再次检查删除状态，已删除时不修改文件状态、不清理索引、不触发解析。该检查不替代停写要求，运行期间仍应避免并发删除文件。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --concurrency 4
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --concurrency 4 --report-file /var/log/bisheng/reparse.jsonl
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --space-id 10 --folder-id 20
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --file-id 101 --file-id 102
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --space-level public
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --space-level department --status failed --status waiting --status violation
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --retry-skipped

bash scripts/reparse_knowledge_space_files.sh
bash scripts/reparse_knowledge_space_files.sh --apply --concurrency 4
```

Scope:

- 不传范围参数：处理所有知识空间中的真实文件
- `--space-id`：包含指定知识空间下的所有真实文件，可重复传入
- `--folder-id`：递归包含指定文件夹下所有层级的真实文件，可重复传入
- `--file-id`：包含指定真实文件，可重复传入
- `--space-level`：按空间类型过滤，可选 `public` / `department` / `team` / `personal`。该条件与
  `--space-id` / `--folder-id` / `--file-id` 的并集取交集；未配置空间类型的知识空间不命中
- `--status`：按文档状态过滤，可重复传入，多值之间取并集。可选 `processing` / `success` /
  `failed` / `rebuilding` / `waiting` / `timeout` / `violation`
- 不传 `--status` 时，仅处理 `SUCCESS` / `FAILED` / `TIMEOUT` / `VIOLATION`；显式传入后会替换该默认集合
- `--status` 不可与兼容参数 `--include-inflight` / `--only-inflight` 同时使用
- `--include-inflight` 在默认状态集合上增加 `WAITING` / `PROCESSING` / `REBUILDING`；
  `--only-inflight` 仅处理这三种执行中状态

Progress and report:

- `--apply` 会实时输出每个文件的开始、成功/失败、`completed/total`、百分比、成功/失败计数和累计耗时
- 每次 apply 默认生成 `./reparse_reports/reparse-{run_id}.jsonl`；可用 `--report-file` 指定其他新路径
- JSONL 逐行记录 `run_started`、`selection_completed`、`processing_started`、`file_started`、
  `file_completed`、`run_completed`；文件事件包含开始时间、结束时间、用时、最终状态和错误
- 报告由独立线程通过共享队列串行写入并逐行刷新；运行期间可以直接读取已完成的 JSON 行
- 指定的报告文件已存在时脚本会拒绝覆盖；目录创建、序列化或写入失败会导致脚本非零退出
- 单文件普通 Python 异常会被独立记录，其他文件继续执行；原生崩溃、解释器退出和永久阻塞不在隔离范围内
- `--apply` 会把解析失败的文件和执行中崩溃的文件写入 `./reparse_reports/reparse-skip.json`（可用 `--skip-ledger` 改路径）。开始处理某个文件时先记为崩溃中，成功后删除，失败则改记为 failed。进程中途退出时该文件会留在 crashed 里。下次运行默认跳过这些 ID；需要重试时加 `--retry-skipped`，完全关闭该机制用 `--no-skip-ledger`
- 提高 `--concurrency` 会同时增加数据库、Milvus、Elasticsearch、MinIO 和解析服务压力，应按环境容量设置
- dry-run 不创建 JSONL 报告，也不会执行文件解析；仍会读取 skip ledger 并在候选结果里排除已失败/已崩溃文件

### `enqueue_reparse_knowledge_space_files.py`

复用 `reparse_knowledge_space_files.py` 的文件筛选规则，但不在脚本进程内解析。
默认 dry-run，仅输出候选统计；传入 `--apply` 后会将每个仍符合条件的文件更新为
`WAITING`，清空旧的解析备注和相似文件标记，并携带文件所属 `tenant_id` 把
`retry_knowledge_file_celery` 发布到 `knowledge_celery`。旧向量由 worker 的重试任务清理。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --apply
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py \
  --apply --space-id 10 --folder-id 20
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py \
  --apply --file-id 101 --file-id 102
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py \
  --space-level department --status failed --status timeout

bash scripts/enqueue_reparse_knowledge_space_files.sh
bash scripts/enqueue_reparse_knowledge_space_files.sh --apply --space-id 10
```

Scope 与状态筛选参数和上方本地重解析脚本一致，但不提供仅用于本地解析的 `--concurrency`。

Safety:

- 成功输出表示任务已被 broker 接受，不表示 worker 已经解析完成。
- 执行 `--apply` 前必须确认 broker 和 `knowledge_celery` worker 可用，并先保存 dry-run 输出。
- 单文件发布失败时脚本会尝试恢复其原始状态并继续；存在任何发布或恢复失败时最终返回非零退出码。
- `--include-inflight` / `--only-inflight` 可能与正在运行的任务重复解析，只能在明确需要时使用。
- 数据库状态提交与 Celery 发布不是原子事务；网络异常存在 broker 已接受但客户端未收到确认的不确定窗口。

### `retry_failed_knowledge_space_folder_files.py`

按知识空间名称和目录名称（支持多级路径）查找该目录及其子目录下状态为 `FAILED` 的文件，
默认 dry-run 只列出文件；传入 `--apply` 后复用 `enqueue_reparse_knowledge_space_files.py`
把重试任务发到 `knowledge_celery` worker。

Usage:

```bash
export config=/path/to/config.yaml
cd src/backend

# 先预览失败文件，不改数据
bash scripts/retry_failed_knowledge_space_folder_files.sh \
  --space-name "安全生产知识库" \
  --folder "安全生产/消防安全"

# 确认无误后再入队重解析
bash scripts/retry_failed_knowledge_space_folder_files.sh \
  --space-name "安全生产知识库" \
  --folder "安全生产/消防安全" \
  --apply

# 整个知识空间（含根目录和所有子目录）下的失败文件
bash scripts/retry_failed_knowledge_space_folder_files.sh \
  --space-name "admin的知识库" \
  --folder /

# 目录名在空间内唯一时可只写最后一级
bash scripts/retry_failed_knowledge_space_folder_files.sh \
  --space-name "安全生产知识库" \
  --folder "消防安全"

# 同名知识空间用租户 ID 区分；需要时连 TIMEOUT 一起重试
bash scripts/retry_failed_knowledge_space_folder_files.sh \
  --space-name "安全生产知识库" \
  --folder "安全生产/消防安全" \
  --tenant-id 1 \
  --include-timeout \
  --apply
```

`--folder` 支持 `/`、`>`、`->` 分隔多级目录。解析范围包含该目录及其所有子目录。
`--folder /`（或 `root`）表示整个知识空间，包括根目录下的文件。

Safety:

- 默认只选 `FAILED`。`--include-timeout` 才会加上 `TIMEOUT`。
- `--apply` 前必须先跑 dry-run，并确认 broker 与 knowledge worker 可用。
- 成功输出只表示任务已入队，不表示解析已经完成。

### `audit_api_sync_uploader_clinic_spaces.py`

按知识空间名称和目录名称（支持多级路径）列出该目录及其子目录下入库方式为「接口同步」
（`user_metadata.filelib_sync_endpoint` 或 `external_file_id`）的文件，再按上传人
（优先 `original_uploader_id`，否则 `user_id`）按主部门组织树上溯查找科室库绑定。只读；输出命中的
科室库、已有科室库的上传人、以及没有科室库的上传人。

判定：与 filelib_sync 责任人科室库相同——从上传人主部门沿组织树（自己→上级→根）查找第一个
科室库绑定（空间 level 为 team/team_ks 且 owner_type=user）。不看 org_level。班组人员可以命中
上级科室的库。无上传人、用户不存在、没有部门、整条链都没有科室库才会进入缺失名单。

Usage:

```bash
export config=/path/to/config.yaml
cd src/backend

bash scripts/audit_api_sync_uploader_clinic_spaces.sh \
  --space-name "安全生产知识库" \
  --folder "安全生产/消防安全"

# 整个知识空间
bash scripts/audit_api_sync_uploader_clinic_spaces.sh \
  --space-name "安全生产知识库" \
  --folder /

# JSON 输出；同名空间用租户 ID 区分
bash scripts/audit_api_sync_uploader_clinic_spaces.sh \
  --space-name "安全生产知识库" \
  --folder "消防安全" \
  --tenant-id 1 \
  --format json
```

`--folder` 规则与 `retry_failed_knowledge_space_folder_files.py` 相同。脚本不写库。

### `move_api_sync_files_to_uploader_clinic_spaces.py`

按知识空间名称和目录路径选出入库方式为「接口同步」的文件，解析每位上传人的科室库
（规则与 `audit_api_sync_uploader_clinic_spaces.py` / filelib_sync 责任人科室库相同），
再把文件迁到对应科室库。目标目录就是输入的目录路径；不存在则按段创建。
来源子目录下的文件会平铺到该目标目录。默认为 dry-run；`--apply` 才会建目录并迁移。

Usage:

```bash
export config=/path/to/config.yaml
cd src/backend

# 仅预检
bash scripts/move_api_sync_files_to_uploader_clinic_spaces.sh \
  --space-name "安全生产知识库" \
  --folder "安全生产/消防安全"

# 执行迁移
bash scripts/move_api_sync_files_to_uploader_clinic_spaces.sh \
  --space-name "安全生产知识库" \
  --folder "安全生产/消防安全" \
  --apply
```

没有科室库、解析未成功、目标重名、嵌入模型不一致的文件会跳过并打出原因。
输出每行包含迁移文件、科室库名称、上传人和科室名称。

### `merge_personal_knowledge_spaces.py`

合并同一用户重复创建的默认个人知识库，只扫描 `personal` 作用域下名为
`用户名的知识库` 的空间，排除收藏库、自建其他名称的个人库和其他类型知识库。
保留 ID 最小的库，将其余库的根目录文件、子目录及空目录合并进去。

在 `src/backend/` 执行：

```bash
# 默认只读预览，报告列出用户、目标库、待清理旧库及迁移/覆盖计划
.venv/bin/python scripts/merge_personal_knowledge_spaces.py --all-users

# 先核对单个用户
.venv/bin/python scripts/merge_personal_knowledge_spaces.py --user-id 7

# 执行该用户的合并、同名覆盖和空旧库清理
.venv/bin/python scripts/merge_personal_knowledge_spaces.py --user-id 7 --apply

# 全部用户；多租户开启时必须显式指定当前要处理的一个租户
.venv/bin/python scripts/merge_personal_knowledge_spaces.py --all-users --tenant-id 2 --apply
```

- 按来源库 ID、文件 ID 升序迁移，保留 ID 最小的个人库，保持目录层级。同一目标目录内同名时，后迁入文档覆盖前面的及目标原有文档，数据库中的旧文件与完整旧版本链删除；不同目录的同名文件分别保留。
- 默认采用原记录迁移：保留文件 ID、文档 ID、版本 ID、版本号、主版本及原文件对象地址，事务内调整文件/文档的知识库、目录和所有者。不会复制再删除来源原文件。为避免误删复用对象，被覆盖文件的 MinIO 对象也暂留，JSONL 的 `overwritten_objects_retained` 列出后续回收清单。
- 优先读取 Milvus；无数据或读取失败时尝试 ES。可读分段尽量写入目标索引，两种索引独立处理。ES 通常不包含向量：可保留全文内容，但缺少向量会标记解析失败，不调用模型临时补算。
- 两边都没有数据、索引读写失败、模型不一致、原文件已解析失败/超时、权限或附属资源清理异常：文件记录仍迁入，状态设为 `3`（解析失败），原因写入 `remark`、`user_metadata.personal_space_merge` 与 JSONL；以后可按需重新解析。索引失败不再通过计数一致性门禁阻断合库。
- 仍保护正在解析/重建/排队的文件、违规内容、活动审批、发布/分享及被引用内容、损坏版本图、目录冲突、频道同步绑定或空间审批。这些结构/业务保护项会跳过并保留对应旧库。数据库提交、记录变化和审计失败仍停止，不能靠修改解析状态伪报成功。
- 来源文件和文档全部迁出、目录映射及目标记录复查通过后删除空旧库。业务清理入口异常时，重新确认来源无文件/文档后事务删除空库记录及作用域；外部索引、权限等残留写入 `source_space_cleanup_pending`，并将受影响文件标记解析失败。重新解析只重建文件内容，权限和旧索引/对象残留仍需按清单单独处理。
- 每次生成 `migration_reports/merge_personal_spaces/merge-<run_id>.json`；`--apply` 另生成同名 JSONL，可用 `--report-dir` 更改位置。报告列出 `reparse_file_ids`。`completed_with_reparse` 表示合库完成但有文件需要重新解析或附属资源待处理；`completed_with_skips` 表示仍有跳过或旧库保留。
- 先扫描元数据，再分重复用户加载文件；逐单元只复查相关文件、版本链、目标目录及冲突项。Milvus 批次 500、ES 写入批次 100，写入请求上限 60 秒，ES 禁止自动重试。原记录迁移省去原文件复制、来源删除及失败回迁。
- JSON 报告每 20 个单元或间隔 10 秒保存，来源结束及异常退出时也保存；JSONL 关键步骤立即落盘。进程强制中断后先检查 `record_merge_committed`，不能把来源库已无该文件理解成原文件丢失。
- 退出码：`0` 预览或完成（可能有待解析/跳过），`2` 参数/入口失败，`3` 执行失败，`130` 中断。`--stop-on-error` 保留兼容，索引降级属于已迁入而非单元失败。Ctrl+C 在当前单元结束后停止。
- 必须停写、串行执行并事先备份。同名覆盖的旧数据库记录无法由重新解析恢复；JSONL 提供核查线索，不能替代备份。仅需部署本脚本一份文件，不依赖其他 `scripts` 模块。

### `move_department_files_to_personal.py`

将部门知识库指定根目录下的文件，按当前 `KnowledgeFile.user_id` 迁入上传人的默认个人库，保留根目录和所有下级目录。脚本可单文件部署，不依赖其他 `scripts` 模块，不删除部门库或来源目录。

```bash
# 默认只读预览
python scripts/move_department_files_to_personal.py --folder-name 待整理

# 核对报告后执行；多租户开启时增加 --tenant-id <租户ID>
python scripts/move_department_files_to_personal.py --folder-name 待整理 --apply
```

- 保留原文件 ID、文档/版本 ID、版本号、主版本及对象地址，通过数据库事务调整文件和文档的知识库、目录及所有者，不再复制后删除来源原文件。
- 目标默认个人库不存在时调用业务创建入口；存在多个同名个人库时固定取 ID 最小者。新建个人库/目录在后续失败时保留并记录，重跑复用。
- 按来源库 ID、文件 ID 顺序逐个迁移，同一用户、同一路径、同名时后迁入覆盖前面的及目标原有完整版本链。数据库中的旧文件/版本链删除与来源归属调整在同一事务内；事务失败回滚。旧目标 MinIO 对象暂留，JSONL 的 `overwritten_objects_retained` 列出回收线索，避免复用对象误删。不同目录同名分别保留，不按 MD5 扩大覆盖。
- Milvus 无可读数据时读取 ES；可用内容尽量写入目标索引。两边均不可读、索引写入/清理失败、源状态为解析失败/超时、模型不一致时，记录仍迁入并设 `status=3`，原因写入 `remark` 与 `user_metadata.department_to_personal`。ES 通常无向量，只能保留全文，需重新解析才能补齐向量。
- 部门转个人涉及访问范围变化：文件权限先切换并确认，再提交数据库。权限切换失败时保持来源归属并尝试恢复原权限；恢复失败记录 `permission_restore_failed` 后停止。数据库提交结果不明时先查询归属，不能把已迁入个人库的文件重新授权给旧部门。索引失败降级不适用于权限、数据库和审计失败。
- 保留用户/租户有效性、目录结构、完整版本链、审批、发布/分享及外部引用保护。正在解析/重建/排队或违规文件跳过；源/目标记录在运行期间变化则拒绝覆盖。跳过项不会伪报成功。
- 扫描先发现部门库，再按库读取命中目录的子树和相关上传人个人库；执行期间只复查当前文件、目录、版本链及相关目标记录。跨库引用采用单独定向查询，不为查引用反复加载全租户文件。报告每 20 个单元或间隔 10 秒保存，异常和退出也保存，JSONL 关键步骤立即落盘。
- 报告默认在 `migration_reports/department_to_personal/move-<run_id>.json`，apply 另有 JSONL。`reparse_file_ids` 列出最终仍存在的待解析文件 ID；`completed_with_reparse` 表示有迁入内容需要重新解析，`completed_with_skips` 表示有跳过项。权限、旧索引或对象残留需按审计单独处理，重新解析不能替代权限恢复或旧对象回收。
- 退出码 `0`：预览或处理完成（可有待解析/跳过）；`2`：入口失败；`3`：执行失败；`130`：中断。Ctrl+C 等当前单元结束后停止；重跑重新扫描已剩余内容。
- 必须停写、串行执行并事先备份。事务只覆盖关系数据库，跨系统没有全局事务；强杀后检查 `record_merge_committed` 和权限审计，不能直接假定回滚成功。被覆盖的旧版本链无法靠重新解析或普通重跑恢复。

### `diagnose_department_to_personal_impact.py`

只读核对门户首页文档数口径，并归类 `move_department_files_to_personal.py` 标成「迁移完成，需重新解析」的原因。不写业务数据。对比三项：MySQL 里首页可计入的成功文件、统计 ES `mid_knowledge_space_content_stat` 的首页聚合、以及 remark 带迁后失败标记的文件。

```bash
PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_to_personal_impact.py
PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_to_personal_impact.py \
  --output /tmp/diagnose-department-to-personal.json
PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_to_personal_impact.py --skip-es
```

- `conclusion.likely_causes` 用中文写判断：迁后解析失败、ES 快照落后、或 `space_level=unknown`。
- `migration_marks.by_primary_reason` 区分模型不一致、源索引读不到、ES 无向量、读写超时、源库清理、覆盖清理、统计刷新等。
- `--sample-limit` 控制每种原因保留的文件 ID 数量，默认 20，最大 200。
- 统计 ES 不可用时加 `--skip-es`，仍输出 MySQL 与迁后失败归类。

### `repair_department_to_personal_es_write.py`

针对 `move_department_files_to_personal.py` 标成 `write_es_failed` 的文件：检查当前个人库 Milvus 是否已有向量，必要时从 Milvus 回写 ES，并把 `status` 恢复为成功。默认只读抽样，不重解析，不删 MinIO。

```bash
# 默认抽 20 个，只统计 Milvus / ES chunk 数
PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py

# 指定诊断里的样例 ID
PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py \
  --file-id 110858 --file-id 110883 --probe-error

# 抽样 20 个确认可修后再写入
PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py --sample 20 --apply

# 处理全部 write_es_failed
PYTHONPATH=./ .venv/bin/python scripts/repair_department_to_personal_es_write.py --all --apply
```

- `milvus_ready_es_missing` / `milvus_ready_es_partial` / `both_present`：Milvus 已有向量，`--apply` 会回写 ES 并恢复 `status=2`，然后入队首页统计刷新。
- `milvus_missing`：个人库没有向量，不能靠这个脚本恢复，应走 `reparse_knowledge_space_files.py`。
- `--probe-error` 会用清洗后的一条文档试写 ES，保留 mapper/BulkIndexError 原文，便于确认是向量字段污染还是 mapping 冲突。
- 个人库若还没有 ES 索引（新建后从未成功解析过），`--apply` 会按正常解析路径创建索引再写入，而不是报 `es index missing` 后跳过。
- 回写前会按 `document_id` 删除该文件在目标 ES 中的旧 chunk，避免半写入残留。

### `move_clinic_knowhow_to_public.py`

将指定租户所有科室库中的「技术诀窍」且「入库方式=接口同步」文件，按二级分类移入同租户公共「技术诀窍」库。
缺失二级目录自动创建，目标公共库必须已存在且唯一。科室库按 `team_ks` / 旧版 `team`、用户所有及有效组织绑定识别。
新增执行逻辑全部在本脚本内，直接引用后端已有存储和权限接口；**不使用跨库迁移引擎，不创建迁移批次，不派发 Celery**。

在 `src/backend/` 下运行：

```bash
# 默认仅生成候选报告，不写业务数据
.venv/bin/python scripts/move_clinic_knowhow_to_public.py --tenant-id 1

# 在相关文件停止写入的维护窗口执行，123 为真实全局超级管理员用户 ID
.venv/bin/python scripts/move_clinic_knowhow_to_public.py \
  --tenant-id 1 --operator-id 123 --apply

# 以数据库为准覆盖旧索引归属差异，写后校验不一致时额外重写最多 2 次
.venv/bin/python scripts/move_clinic_knowhow_to_public.py \
  --tenant-id 1 --operator-id 123 --apply --force-rewrite

# 按需恢复报告中未完成的文档（不回滚成功项，不作为新执行的前置要求）
.venv/bin/python scripts/move_clinic_knowhow_to_public.py \
  --tenant-id 1 --operator-id 123 --apply --recover-report migration_reports/clinic_knowhow/报告文件.json
```

- 筛选口径：`user_metadata.filelib_sync_endpoint` 或 `external_file_id` 至少一个为真值。
  排除回收站、发布/共享入口及未解析成功文件；一级编码从门户配置读取。整条版本链必须在来源范围内、
  满足接口同步条件且二级分类一致。缺少规范文档版本链的旧文件跳过；同名或同内容目标文件跳过，不覆盖。
- 原地修改文件、文档的 `knowledge_id`、目录与层级。文件 ID、文档 ID、版本 ID、原对象地址、解析结果、
  `content_generation` 保持不变；上传人不变，缺失的原始上传人/原始库字段在移动前补齐。
  来源科室库不保留管理入口或软链，不删除原对象，不清理来源空目录。
- OpenFGA 权限改为目标库所有者及目标目录继承，移除原文件的旧直接授权；其他发布/共享入口保持原状。
  更新共享 ES/Milvus 的 `knowledge_ids` 和归属代次，并保留其他有效入口所属库。
  Milvus 使用已有向量重写元数据，向量行主键可能变化，**不重新解析、分块、生成摘要或计算向量**。
  同步刷新已有全文索引的目录元数据和推荐文件投影。
- 执行前及写入后核验两个共享存储的全部分块、文本、向量及内容标识。缺失索引、版本/分类变化、
  投影未就绪或有相关审批时记录该文档错误并继续后续文档，不自动重建内容；多租户部署须显式指定 `--tenant-id`。
- 需要现有数据库表、OpenFGA 及共享 ES/Milvus 可用。脚本不获取 Redis 全局迁移锁或租户共享对账锁，
  不等待或续租维护锁，不主动扫描或清理 Redis 权限缓存；已移除锁等待参数 `--timeout`，数据库事务行锁仍保留。
  后端初始化及复用的服务仍可能依赖 Redis；权限缓存按现有 TTL 到期，新权限可能延迟生效。
  应避免与旧迁移、共享存储对账任务重叠执行，并停止相关文件的上传、重解析、发布和分享写入。
  不查询、处理或删除旧迁移批次，也不扫描历史报告阻止新执行；旧批次状态和历史失败记录不再阻塞脚本。
- 默认报告目录 `migration_reports/clinic_knowhow/`，可用 `--report-dir` 指定；报告包含修改前记录、权限、
  内容指纹和执行阶段，权限为 `0600`，应持久保存。候选扫描不等于已通过逐文档执行校验。
- 首次扫描按多个科室库批量分页查询，目标库只读取根目录直属文件夹；逐目录复核仅查询本次候选文件，
  仍加载完整版本链进行一致性校验，避免每个目录重复全量扫描所有科室库。
- 各阶段输出带时间戳的开始、完成及耗时日志；异步等待期间每 10 秒输出当前阶段。
  报告的 `stage` 字段保存当前执行阶段，共享路由加载超时为 30 秒。
- 共享索引写入后校验失败时，日志显示存储侧、文档、分块、字段、预期值与实际值及类型。
  报告的 `index_verification` 保存不一致总数及最多 10 条样本，不记录正文或向量；校验失败仍保留恢复信息。
- `--force-rewrite` 在归属字段读回不一致时，仅对不一致的 ES/Milvus 侧额外重写最多 2 次，
  每次都重新读取两侧分块并核验归属、正文和向量。报告的 `rewrite_attempts`、`rewrite_history` 记录次数及差异。
  超限后记录该文档失败并继续下一项；内容变化、权限失败或写入接口报错不会被忽略或盲目重试。
  该参数也适用于 `--recover-report`，恢复方向仍以数据库实际归属为准。
  迁移前发现索引归属与数据库不一致时，该参数以数据库有效管理、发布和共享入口为准计算迁移后归属并覆盖索引，
  保留数据库中的其他有效归属，去除索引独有的错误归属；无需仅为此差异先执行对账或恢复。
  报告的 `initial_index_drift` 保存迁移前数据库归属、不一致分块数及最多 10 条旧索引归属样本。
  不加该参数时仍拒绝迁移前的归属差异；内容标识、分块、向量和权限校验均保留。
- 单个文档异常后保留文件 ID、文档 ID、执行阶段、错误及堆栈，继续处理后续文档；目录创建或复核失败则记录
  该目录及文件列表，继续下一个目录。结束时汇总成功、恢复、跳过、失败和待恢复数量，保留错误而不整批退出。
  初始化失败、报告无法保存或手动中断时仍停止。错误保存在本地 JSON 报告，不创建迁移批次或 Redis 任务记录。
- 数据库、ES、Milvus、OpenFGA 无法同事务提交。失败文档可能存在归属/权限不一致，修改前记录仍保存在报告中。
  `--recover-report` 以数据库实际归属为准：数据库未提交则恢复来源权限与索引；已提交则补齐目标状态。
  恢复模式也按文档记录错误并继续；如果内容或版本已变化则拒绝恢复该文档。恢复不回滚已完成文档，创建的空目录
  可能保留；需在维护窗口核查失败项后再开放写入。
- 退出码：`0` 为预览、迁移或恢复完成（可能有明确跳过），`2` 为已跑完但有单项失败，`1` 为整批失败，`130` 为手动中断。

### `move_knowledge_space_files.py`

扫描一个或多个来源知识空间的 `SUCCESS` 真实文件，可按来源文件夹、门户一级分类 code、
门户二级分类 code 缩小范围。默认按分类 `label` 自动匹配公共知识空间及其根目录
直属文件夹；也可显式指定目标知识库和目标文件夹。默认将文件平铺到路由后的目标文件夹，
可通过 `--preserve-folder-structure` 按需复制来源目录层级。版本链作为一个迁移单元整体处理。

脚本默认为 dry-run；只有显式传入 `--apply` 才会写入目标并删除来源。脚本会先对来源空间中的
`SUCCESS` 真实文件做轻量计数，再按来源文件夹和分类提前缩小分析范围。每次运行都会在
`--report-dir` 下生成 JSON 运行报告；apply 模式另外生成 JSONL 审计记录。普通移动在目标数据仍保留时
可依据记录手工还原；强制覆盖会永久删除旧目标内容，JSONL 只能用于审计和残留清理，不能恢复旧目标。

Usage:

```bash
# 扫描一个来源知识空间；仅预检，不写业务数据
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10

# 一次扫描多个来源空间
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --source-space-id 11

# 只选择文件夹 100/101 的递归子孙，且一级分类为 A/B，且二级分类为 A01/B01
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --source-folder-id 100 \
  --source-folder-id 101 \
  --source-category-code A \
  --source-category-code B \
  --source-subcategory-code A01 \
  --source-subcategory-code B01

# 将筛选结果全部移入指定目标文件夹，每 10 个迁移单元落盘一次回溯记录
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --target-space-id 20 \
  --target-folder-id 200 \
  --rollback-record-file migration_reports/move-10-to-20.jsonl \
  --batch-size 10 \
  --apply

# 保留来源文件夹 100 本身及其子目录：目标/来源文件夹 100/.../文件
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --source-folder-id 100 \
  --preserve-folder-structure \
  --folder-root-mode include

# 仅保留文件夹 100 下方的层级，并迁入显式目标：目标/.../文件
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --source-folder-id 100 \
  --preserve-folder-structure \
  --folder-root-mode contents \
  --target-space-id 20 \
  --target-folder-id 200 \
  --apply

# 预览强制覆盖：不会写数据，报告会列出待删除的目标逻辑文档、版本和文件 ID
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --source-folder-id 100 \
  --target-space-id 20 \
  --target-folder-id 200 \
  --force-overwrite

# 审核 dry-run 报告后执行不可恢复的强制覆盖
PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
  --source-space-id 10 \
  --source-folder-id 100 \
  --target-space-id 20 \
  --target-folder-id 200 \
  --force-overwrite \
  --apply
```

参数：

- `--source-space-id`：必填、可重复；多个 ID 取并集，且必须属于同一租户。
- `--source-folder-id`：可重复；每个文件夹都递归包含所有子孙文件，多个 ID 取并集。文件夹必须
  存在于本次来源空间中。
- `--source-category-code`：可重复；按门户一级分类 code 过滤，多值取并集，code 不区分大小写。
- `--source-subcategory-code`：可重复；按门户二级分类 code 过滤，多值取并集，code 不区分大小写。
  同时指定一级分类时，二级分类必须属于所选一级分类。
- `--preserve-folder-structure`：可选开关。开启后，在自动路由或显式目标文件夹之下保留来源目录层级；
  未开启时保持原有平铺行为。
- `--folder-root-mode`：仅能与 `--preserve-folder-structure` 一起使用，可选 `include` / `contents`，
  默认 `include`。`include` 保留命中的最外层 `--source-folder-id` 本身；`contents` 从该目录下一层
  开始保留。未指定来源文件夹时，两种模式都从来源知识空间根目录下开始保留。
- `--target-space-id` 与 `--target-folder-id`：必须同时传入或同时省略。传入后，所有选中迁移单元
  都进入该文件夹；目标可为公共或部门空间，文件夹可为任意层级，但必须属于目标空间且与来源
  处于同一租户。团队和个人空间不允许作为显式目标。
- `--force-overwrite`：默认关闭。只能与显式的 `--target-space-id`、`--target-folder-id` 一起使用，
  且目标空间不能同时出现在 `--source-space-id` 中。开启后，唯一命中的旧目标逻辑文档会被永久删除；
  省略 `--apply` 时只预览覆盖计划。
- `--report-dir`：JSON 运行报告目录，默认为 `migration_reports/knowledge_file_move/`。
- `--rollback-record-file`：apply 模式的 JSONL 回溯文件。省略时在 `--report-dir` 下按 `run_id` 自动命名。
  文件以 `0600` 权限排他创建，如已存在则预检失败，不会覆盖或追加到旧记录。
- `--batch-size`：每完成多少个迁移单元后 `flush + fsync` 一次普通 JSONL 成功记录，必须为正整数，默认 `10`。
  单个文件算一个单元，整条版本链也只算一个单元。强制覆盖的 `overwrite_started` 和清理结果始终立即
  `flush + fsync`，不受批大小延迟。
- `--apply`：执行真实移动；省略时只生成 dry-run 计划与报告，不创建 JSONL 回溯文件。

筛选组合：

- 同一维度重复参数之间为 OR：多个来源空间 OR、多个来源文件夹 OR、多个一级分类 OR、
  多个二级分类 OR。
- 不同维度之间为 AND：`来源空间 AND 来源文件夹 AND 一级分类 AND 二级分类`。未传入的可选维度
  不参与过滤。
- 版本链中的每个版本都必须命中全部已启用的过滤条件，否则整条版本链跳过；一、二级分类也必须
  在整条版本链中一致。
- 显式目标只替代自动路由，不取消分类校验或源过滤。
- 目录保留可与来源文件夹、一/二级分类过滤、自动路由、显式目标、dry-run 和 apply 任意组合；
  `--folder-root-mode` 单独使用会直接报参数错误。
- `--force-overwrite` 可与来源过滤、目录保留、dry-run 和 apply 组合，但不能用于自动分类路由。

JSON 报告：

- dry-run 的 `results` 只包含通过全部预检、最终可迁移的文件，每条的 `status` 为 `ready`。
- apply 的 `results` 只包含实际尝试迁移的 `success` / `failed` 文件。
- 来源范围外文件不进入 `results` 或 `skipped`；来源命中但未通过预检的文件只在
  `summary.skipped` 和 `summary.skip_reasons` 中汇总，不输出逐文件明细。
- `summary` 不再输出容易误解的 `total`，字段含义如下：

```json
{
  "scanned": 754,
  "source_selected": 55,
  "ready_to_move": 50,
  "skipped": 5,
  "success": 0,
  "failed": 0,
  "overwrite_units": 2,
  "overwrite_documents": 2,
  "overwrite_files": 4,
  "overwrite_cleanup_failed": 0,
  "skip_reasons": {
    "target_name_conflict": 3,
    "version_chain_filter_mismatch": 2
  }
}
```

其中 `scanned` 是来源空间内的 `SUCCESS` 真实文件数，`source_selected` 是命中所有来源过滤的文件数，
`ready_to_move` 是通过预检的文件数。预检结束时始终满足
`source_selected = ready_to_move + skipped`。`success` / `failed` 只统计 apply 期间实际执行结果。
开启强制覆盖后，顶层 `overwrites` 按迁移单元列出命中原因、旧目标逻辑文档、版本、物理文件、对象、
索引和逐步骤清理结果；summary 的四个 `overwrite_*` 字段提供覆盖与残留统计。

路由、回溯记录与安全性：

- 仅处理 `file_type = FILE` 且 `status = SUCCESS` 的文档。
- 一级分类 code 从 `file_encoding` 解析，二级分类 code 来自 `file_subcategory_code`；两级都必须
  能在门户配置中解析出 `label`，否则跳过。
- 一级分类 `label` 必须唯一精确匹配 `level = public` 的知识空间名称；二级分类 `label` 必须
  唯一精确匹配该空间根目录下的直属文件夹名称。匹配前会去除普通首尾空白、`U+200B`
  零宽空格和 `U+FEFF` BOM；自动路由不做递归或模糊匹配。
- 开启目录保留时，脚本按父目录和规范化名称复用已有目录，仅为成功选中的文件懒创建必要祖先，
  不复制空目录、来源目录权限或其他目录元数据。新目录的 owner 为目标知识空间 owner，parent 为目标父目录。
- 多个来源空间的同名同层级目录会合并到同一目标目录。目标结果深度超过 10 层时，影响的文件或版本链会跳过。
- 移动后文件所有者改为目标知识空间所有者；OpenFGA 只重建目标 owner/parent 必要关系，
  不复制来源访问权限。
- 已通过和待审核标签以复制前保存的来源快照为唯一依据，精确替换到新目标文件；若校验仍不一致，
  报错会列出来源和目标双方的标签 ID，并在删除来源前清理目标残留。
- 默认情况下，目标文件夹存在同名文件、目标空间任意位置存在相同 MD5，或来源/目标向量模型不一致时，
  跳过文件且保留来源。多个来源文件互相冲突时按来源空间 ID、文件 ID 稳定选择第一个。
- 开启 `--force-overwrite` 后，同名冲突和目标空间任意目录中的同 MD5 冲突都会解析到目标逻辑文档。
  所有命中归属于同一个逻辑文档时纳入覆盖计划；命中多个逻辑文档时以
  `target_overwrite_ambiguous` 跳过。若两个来源单元命中同一旧目标逻辑文档，只保留排序后的第一个，
  后续单元以 `batch_overwrite_conflict` 跳过。
- 旧目标属于版本链时整条链都会删除，最终版本图完全复制来源，不合并两边历史。复制并校验新目标后，
  脚本会重新读取旧目标文件和版本图；与预检快照不一致时停止该迁移单元，不执行旧目标删除。
- 版本链作为整体迁移：所有版本必须位于本次来源范围、均为 `SUCCESS`、分类完整、目标一致、
  模型兼容且无目标冲突；开启目录保留时，各版本还必须处于同一来源目录。任一条件不满足则整条链跳过。
  范围外的链上版本仍参与完整性检查，但不计入 `source_selected` 或 `skipped`。成功后使用新文件 ID
  重建版本号、主版本和逻辑文档关系。
- 普通文件按“复制 → 校验 → 删除来源”执行；强制覆盖按“复制 → 校验 → 落盘覆盖快照 → 删除旧目标
  → 落盘清理结果 → 删除来源”执行。失败时保留或恢复来源，并尽力清理新目标残留；
  版本链按整链 Saga 执行。任一迁移单元失败时立即停止后续单元并返回非零退出码，业务跳过不计为失败。
- JSONL 按顺序记录 `run_started`、`unit_started`、可选的 `overwrite_started` / `overwrite_finished`、
  `unit_succeeded` / `unit_failed`、`run_completed` / `run_completed_with_warnings` / `run_failed` /
  `run_interrupted`；成功单元包含来源与目标文件、空间、文件夹、
  分类、标签、权限、存储对象、索引统计和版本图元数据。目录保留还会记录完整来源目录链，以及每一级目标目录的
  ID、路径和 `created` / `reused` 动作。当前脚本不提供自动回滚命令；被强制覆盖的旧目标数据库、
  MinIO 对象和向量会彻底删除，审计记录无法恢复其内容。
- 首次 `Ctrl-C` 不会在单元内强行中断；脚本完成当前单元、强制落盘 JSONL 后以退出码 `130` 结束。
  普通异常也会尝试写入终止事件并落盘。`kill -9`、进程崩溃或断电无法保证当前未落盘批次的记录完整。
- JSONL 写入失败时，脚本停止迁移，并尝试补偿当前尚未持久化的批次；只删除本单元新建且仍为空的目标目录，
  复用目录、已有内容的目录和前序成功批次的目录不会被删除。之前已落盘的批次保持已迁移状态。
- 旧目标的向量、对象、标签、权限、关联记录、版本图或数据库记录只清理一部分时，脚本记录
  `overwrite_cleanup_failed`，继续完成来源迁移，运行状态为 `completed_with_warnings` 并返回退出码 `4`。
  旧目标不会自动恢复，需要根据 JSONL 人工清理残留。
- `--apply` 会删除来源文件并生成新的目标文件 ID。收藏、分享链接及其他保存旧文件 ID 的引用不会迁移，
  执行前必须先审核 dry-run 报告并确认这些引用中断的影响。

## Telemetry / Dashboard Scripts

### `migrate_user_engagement_indices.py`

F058 后续改造：`用户规模统计`(mid_user_increment) / `活跃用户规模统计`(mid_active_user) /
`全员每日参与度`(mid_user_daily_participation_fact) 三个原本独立的 ES 索引，写入侧已经
改成共写一个新的合并索引（`mid_user_engagement_stat`，见
`bisheng/telemetry/domain/mid_table/user_engagement_shared.py`）。这个脚本把三个旧索引里
**历史**数据搬进新索引，让合并后的看板还能看到切换之前的数据。旧的三个索引本身不改、不删，
脚本只读它们。每条记录按来源打 `metric_source` 标记，`_id` 按来源加前缀（`increment_`/
`active_`，`participation` 本来就带前缀不用改），跟线上写入逻辑用的是同一套前缀规则，
重复跑这个脚本是幂等的（同一条历史记录每次都会覆盖成同样的内容，不会重复插入）。
默认 dry-run，`--apply` 才写库。

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply
PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply --source increment
PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply --batch-size 2000
PYTHONPATH=./ .venv/bin/python scripts/migrate_user_engagement_indices.py --apply --limit 500  # 先小批量验证

bash scripts/migrate_user_engagement_indices.sh --apply
```

说明：

- `--source`：只迁移一个来源(`increment`/`active_user`/`participation`)，默认三个都迁。
- `--limit`：每个来源最多扫描多少条，用于先小批量验证。
- `--apply` 时脚本会先复用线上写入代码本身的建表逻辑（`UserIncrement`/`DailyParticipationFact`/
  `MidActiveUserJob` 各自的 `ensure_index_exists`）把目标索引的 mapping 建/补齐，不在脚本里
  另外维护一份 mapping 定义。

## OpenAPI Verification Scripts

### `verify_filelib_sync.py`

使用 Developer Token 调用 ``POST /api/v2/filelib/file/sync``，上传文件并附带 JSON ``params``，
用于联调 filelib 同步接口。成功时退出码 ``0``，HTTP 或业务失败时退出码 ``1``。

``params`` 示例见 ``scripts/examples/filelib_sync_params.example.json``。

```bash
cd src/backend

PYTHONPATH=./ .venv/bin/python scripts/verify_filelib_sync.py \
  --token bst_xxx \
  --file /path/to/report.pdf \
  --params /path/to/sync_params.json

# 可选：指定网关或服务地址
FILELIB_SYNC_BASE_URL=http://10.0.0.1:7860 \
  bash scripts/verify_filelib_sync.sh \
  --token bst_xxx \
  --file /path/to/report.pdf \
  --params scripts/examples/filelib_sync_params.example.json
```

注意：Token 需已配置文件同步规则，且路由白名单允许 ``POST /api/v2/filelib/file/sync``。

## Export Scripts

### `get_knowledge_file_chunks.py`

按 `knowledge_file_id` 查询一个知识文件在 Elasticsearch 中的全部 chunk，并将文本和元数据以 JSON 输出到标准输出。脚本只读，不会修改数据库或索引。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/get_knowledge_file_chunks.py --knowledge-file-id 123
```

### `set_file_preview_count.py`

按 `file_id` 将知识文件预览量（ES 中的 `portal_document_read` 与
`mid_knowledge_space_content_stat` preview 记录）重置为指定值，默认 1000。
默认 dry-run；传入 `--apply` 才会删除旧记录并写入新数据。

Usage:

```bash
export config=config.yaml
PYTHONPATH=./ .venv/bin/python scripts/set_file_preview_count.py --file-id 1294
PYTHONPATH=./ .venv/bin/python scripts/set_file_preview_count.py --file-id 1294 --target 1000 --apply
```

Repo root wrapper:

```bash
export config=config.yaml
./set_file_preview_count.sh --file-id 1294 --target 1000 --apply
```

### `export_daily_chat_messages.py`

Export 日常模式（`flow_type = 15`）对话内容，默认导出最近 30 天消息并按会话聚合为 JSON。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --days 7
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --format csv
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --tenant-id 3
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --full-session
```

Options:

- `--config`: 指定配置文件，默认取环境变量 `config`，否则使用 `config.yaml`
- `--days`: 最近多少天，默认 `30`
- `--format`: `json` 或 `csv`
- `--tenant-id`: 仅导出指定租户
- `--user-id`: 仅导出指定用户
- `--chat-id`: 仅导出指定会话
- `--include-deleted`: 包含已删除会话
- `--full-session`: 只要会话在时间窗口内活跃，就导出该会话的全部消息

## Expert QA Scripts

### `delete_qa_expert_question.py`

按专家问答问题 ID 删除 `qa_question` 及关联的回答、评论 / 追问、问题投票、回答投票、评论投票和通知。

默认 dry-run，只输出影响范围；执行写入必须显式传入 `--apply`。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/delete_qa_expert_question.py 123
PYTHONPATH=./ .venv/bin/python scripts/delete_qa_expert_question.py 123 --apply

bash scripts/delete_qa_expert_question.sh 123
bash scripts/delete_qa_expert_question.sh 123 --apply
```

Scope:

- `qa_question`
- `qa_answer`
- `qa_comment`
- `qa_question_vote`
- `qa_answer_vote`
- `qa_comment_vote`
- `qa_notification`

## Permission Scripts

### `reconcile_department_member_tuples.py`

根据业务库 `user_department` 全量核对 OpenFGA 的
`user:<id> member department:<id>` 关系，并补齐缺失 tuple。默认 dry-run，
不会写入数据库、Redis 或 OpenFGA；仅传入 `--apply` 时才向 OpenFGA 新增缺失
tuple。脚本不会删除已有业务关系或 OpenFGA tuple。

Usage:

```bash
# 全量预检，只输出缺失统计和样例
bash scripts/reconcile_department_member_tuples.sh

# 先在指定部门验证
bash scripts/reconcile_department_member_tuples.sh --department-id 190

# 确认预检结果后，全量补齐缺失关系
bash scripts/reconcile_department_member_tuples.sh --apply
```

Options:

- `--apply`：执行写入；不传时为只读预检。
- `--department-id <ID>`：可重复传入，仅处理指定部门。
- `--batch-size <N>`：每页读取的 `user_department` 记录数，默认 `500`。
- `--sample-limit <N>`：JSON 中保留的缺失样例数，默认 `20`。

### `diagnose_department_space_access.py`

只读诊断“用户通过部门授权后无法在门户首页看到知识空间”的权限链路。输出 JSON，包含业务数据库中的用户部门归属、目标空间绑定/成员信息、OpenFGA 资源授权 tuple、用户部门 `member` tuple、`check` 与 `list_objects` 结果，以及自动判定的断点。不会写入数据库、Redis 或 OpenFGA。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_space_access.py \
  --user-id 123 --space-id 3569

bash scripts/diagnose_department_space_access.sh \
  --user-id 123 --space-id 3569
```

Exit codes:

- `0`：诊断完成；输出中的 `findings` 可能仍包含权限缺失结论。
- `2`：用户或知识空间不存在，或参数无效。
- `3`：OpenFGA 未启用、缺少只读连接所需的 store/model 配置，或查询失败。

### `migrate_workstation_models_to_workbench.py`

One-off migration for moving the legacy daily-workbench model list from the
global `config.key = "workstation"` row into the default tenant's
`tenant_system_model_config.key = "linsight_llm"` row.

Behavior:

- reads `workstation.models` from `config`
- writes only to default tenant `tenant_id = 1`
- if Root already has `linsight_llm`, merges by updating only `models`
- if Root does not have `linsight_llm`, creates a new row
- preserves legacy `workstation.models`; later UI save flows can handle cleanup/overwrite

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_workstation_models_to_workbench.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_workstation_models_to_workbench.py --apply

bash scripts/migrate_workstation_models_to_workbench.sh
bash scripts/migrate_workstation_models_to_workbench.sh apply
```

Options:

- `--apply`: perform writes; default is dry-run

### `permission_migration.sh`

Manual runner for the F006 historical permission migration from RBAC to ReBAC.

Usage:

```bash
bash bisheng/script/permission_migration.sh
bash bisheng/script/permission_migration.sh dry_run
bash bisheng/script/permission_migration.sh verify
bash bisheng/script/permission_migration.sh replay
bash bisheng/script/permission_migration.sh replay 3
```

Modes:

- `execute`: run migration normally
- `dry_run`: preview migration statistics only
- `verify`: compare old RBAC and new ReBAC permission results
- `replay`: force replay from the specified step, ignoring previous completion state and clearing checkpoint
- `force`: same behavior as `replay`, kept for compatibility

Step map:

- `1`: Super Admin
- `2`: User Group Membership
- `3`: Role Access Expansion
- `4`: Space/Channel Members
- `5`: Resource Owners
- `6`: Folder Hierarchy
- `7`: Department Membership
- `8`: Group Resources

### `reconcile_permission_migration_db.py`

Business-level database reconciliation for the F006 RBAC -> ReBAC migration.

This script does not replay the migration implementation. Instead, it rebuilds
expected tuples directly from business tables such as `userrole`,
`roleaccess`, `space_channel_member`, `knowledgefile`, `user_department`, and
`groupresource`, then compares them with rows in the OpenFGA datastore's
`tuple` table.

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reconcile_permission_migration_db.py \
  --tuple-db-url "mysql+pymysql://user:pass@host:3306/openfga" \
  --step 1

PYTHONPATH=./ .venv/bin/python scripts/reconcile_permission_migration_db.py \
  --tuple-db-url "mysql+pymysql://user:pass@host:3306/openfga" \
  --step 3 --apply
```

Options:

- `--tuple-db-url`: SQLAlchemy URL of the OpenFGA datastore
- `--store-id`: optional OpenFGA store id; auto-resolved when omitted
- `--step`: check exactly step `N` (`1` to `8`)
- `--apply`: apply writes/deletes through OpenFGA API after diffing
- `--sample-limit`: how many sample tuple diffs to print

### `reconcile_permission_migration_db.sh`

Shell wrapper for step-specific database-level reconciliation.

Usage:

```bash
bash scripts/reconcile_permission_migration_db.sh check 1 "mysql+pymysql://user:pass@host:3306/openfga"
bash scripts/reconcile_permission_migration_db.sh apply 3 "mysql+pymysql://user:pass@host:3306/openfga"
```

Arguments:

- arg1: `check` or `apply`
- arg2: step number (`1` to `8`)
- arg3: OpenFGA tuple DB URL

The 3rd argument can be omitted if one of these environment variables is set:

- `OPENFGA_TUPLE_DB_URL`
- `OPENFGA_DATASTORE_URL`
- `OPENFGA_DATASTORE_URI`

### `reset_admin_only_knowledge_permissions.py`

高风险权限重置脚本：校验唯一可用 `admin` 用户后，将非 admin 用户收敛为普通用户，撤销非 admin 的租户/部门/用户组/个人菜单管理授权；删除知识空间、文件夹、文件的非 admin 资源授权，并把创建者和 owner 权限重置到 admin。

默认 dry-run，只输出影响范围；执行写入必须显式传入 `--apply`。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py
PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py --json
PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py --apply

bash scripts/reset_admin_only_knowledge_permissions.sh
bash scripts/reset_admin_only_knowledge_permissions.sh --apply
```

Scope:

- 用户角色：非 admin 删除非普通角色，缺少普通角色时补 `DefaultRole`
- 管理授权：非 admin 的租户管理员、部门管理员、用户组管理员、个人菜单授权
- 知识空间资源：`knowledge_space`、`folder`、`knowledge_file` 的 OpenFGA 资源授权
- 知识空间数据：`knowledge.user_id`、`knowledgefile.user_id/updater_id`、空间成员
- 知识空间类型：保留 `knowledge_space_scope.level/owner_type/owner_id` 和 `department_knowledge_space` 绑定，不把团队、部门、公共知识库改成个人知识库
- 分享链接：失效所有 `knowledge_space_file` active 链接
- 重试队列：失效受影响资源和非 admin 管理授权相关的 pending `failed_tuple`

Failure handling:

- `--apply` 会先提交数据库收敛结果，并在同一事务中为本次 OpenFGA 操作预写 pending `failed_tuple`。
- 如果 OpenFGA 写入失败，脚本会以非 0 退出；此时数据库变更已经提交，预写的 `failed_tuple` 会保持 pending。运维必须先处理 retry 队列或重新执行 `--apply`，确认 OpenFGA 旧权限已清除后，才能认为重置完成。
- 如果脚本输出 OpenFGA 不可用，`--apply` 会在写数据库前中止。
- 如果 `permission_relation_model_bindings_v1` 配置不是合法 JSON list，脚本会中止，避免把损坏配置覆盖为空。

## Destructive Department Scripts

### `purge_department_subtree.py`

按业务 `dept_id` 物理删除指定部门及其全部子孙部门，并物理删除子树成员用户。脚本会将受支持的资源转移给指定管理员，清理 Linsight 用户记录和账号/部门权限关联；聊天、审计与渠道历史不主动删除。

默认是 dry-run，只输出部门、用户、资产和权限影响面。必须显式传入 `--apply` 才会执行不可逆写入。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
  --dept-id BS@example \
  --transfer-to-user-id 1

PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
  --dept-id BS@example \
  --transfer-to-user-id 1 \
  --apply

bash scripts/purge_department_subtree.sh \
  --dept-id BS@example \
  --transfer-to-user-id 1
```

Safety:

- `BS@guest`、租户挂载根节点和不合法的资产接收人会使整次操作在写入前中止。
- 外部同步账号可能在下一轮组织同步时被重新创建；脚本不会修改外部身份源或同步配置。
- OpenFGA 失败会由 `failed_tuple` 补偿机制重试；执行摘要只报告已提交的权限清理操作。
- `--apply` 不可恢复，务必先保存 dry-run 输出并在维护窗口执行。

## Organization Migration Scripts

### `import_filelib_department_mapping.py`

将 CSV 中的组织映射导入 ``filelib_department_mapping`` 表，供 ``filelib_sync`` 将上游
``department_id`` 解析为内部 ``department.external_id``。

CSV 必需列：``external_department_id``、``org_code``；可选列：``external_department_name``。
按 ``external_department_id`` 去重并 upsert。默认 dry-run，``--apply`` 才写入数据库。

```bash
PYTHONPATH=./ .venv/bin/python scripts/import_filelib_department_mapping.py \
  --csv /Users/binfeng/Downloads/ORG_ORGANIZATION_org_code_8digits.csv

PYTHONPATH=./ .venv/bin/python scripts/import_filelib_department_mapping.py \
  --csv /Users/binfeng/Downloads/ORG_ORGANIZATION_org_code_8digits.csv --apply

bash scripts/import_filelib_department_mapping.sh \
  --csv /Users/binfeng/Downloads/ORG_ORGANIZATION_org_code_8digits.csv --apply
```

### `migrate_root_departments_under_default_org.py`

把默认租户中除 `tenant.root_dept_id` 指向节点以外的其他数据库根部门，整体迁移到默认组织下。迁移会级联更新整个部门子树的 `path`，并为 active 根部门补充 OpenFGA `parent` 关系；部门 ID、成员、管理员和知识空间绑定均保持不变。

默认只输出 JSON 迁移计划，不写数据库或 OpenFGA。确认后必须显式传入 `--apply`：

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_root_departments_under_default_org.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_root_departments_under_default_org.py --apply
```

Safety:

- 默认组织通过 `tenant.root_dept_id` 识别，不依赖名称或查询顺序。
- 执行前会校验默认组织和所有待迁移根部门的物化路径；检测到异常即停止。
- `--apply` 会再次校验待迁移部门仍是根节点且路径未变化，避免使用过期 dry-run 计划。
- 数据库提交后通过 `DepartmentChangeHandler` 写入 OpenFGA，失败操作进入现有 `failed_tuple` 补偿机制。

### `migrate_admin_to_department.py`

将一个明确指定的 admin 账号迁移到指定部门。默认 dry-run；`--apply` 会修改主部门和叶子租户，但保留 admin 在原叶子租户中拥有的资源。

每次必须且只能提供一种账号定位方式，以及一种目标部门定位方式。

Usage:

```bash
# 默认预览，不写入
PYTHONPATH=./ .venv/bin/python scripts/migrate_admin_to_department.py \
  --username admin \
  --dept-id BS@example

# 显式执行
PYTHONPATH=./ .venv/bin/python scripts/migrate_admin_to_department.py \
  --user-id 10 \
  --department-id 42 \
  --apply

bash scripts/migrate_admin_to_department.sh \
  --username admin \
  --dept-id BS@example
```

Safety:

- `--user-id` / `--username` 与 `--department-id` / `--dept-id` 均为必须二选一的参数组；用户名采用精确匹配。
- 不接受 `--transfer-to-user-id`，也不会修改任何资源 owner 或资源内容。
- 跨租户迁移仅由该脚本绕过资源阻断；不会修改全局 `enforce_transfer_before_relocate` 配置。
- `--apply` 会改变主部门与叶子租户。脚本不会修改管理员角色、账号状态、密码或其他次级部门关系；OpenFGA 同步遵循现有 `FailedTuple` 补偿机制。

### `report_original_knowledge_file_counts.py`

按原始上传知识库统计各组织下五类知识库的当前业务文件数量，并输出 UTF-8 JSON。文件缺少有效的 `original_knowledge_id` 时回退到当前 `knowledge_id`。公共库归属唯一启用的公司组织；部门库和科室库按知识库绑定组织归属；团队库和个人库按库所有者的当前主部门归属。脚本只读取默认租户数据，不写数据库。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/report_original_knowledge_file_counts.py \
  --output ./knowledge_file_counts_by_original_organization.json

# 仅在确认可以覆盖已有文件时使用
PYTHONPATH=./ .venv/bin/python scripts/report_original_knowledge_file_counts.py \
  --output ./knowledge_file_counts_by_original_organization.json \
  --force
```

输出包含 `summary`、有文件的 `organizations` 和无法解析归属的 `unassigned`。脚本排除发布、分享、投影墓碑、收藏引用、历史非主版本和旧版发布复制记录；如启用了多租户模式则直接中止。

### `backfill_space_file_points.py` / `backfill_space_file_points.sh`

根据指定的目标知识库类型下所有有效主文件，给原始上传人批量增加指定积分。

特性与规则：
- 目标库类型：支持 `public` / `department` / `team` / `team_ks` 以及中文别名（如“公共知识库”、“部门库”、“科室库”）。
- 主文件判定：排除目录 (`file_type=0`)、回收站已删除文件 (`deleted_at is not null`)、跨库分享引用 (`entry_type='share'`) 以及多版本文档中的历史非主版本物理文件。
- 受让人判定：优先使用文件记录的原始上传人 `original_uploader_id`，若为空则回退到 `user_id`。
- 用户存在性：受让人 ID 在用户表中不存在时，演练统计和正式补分均跳过，并报告“不存在用户文件”数量。原始上传人 ID 非空但用户已不存在时，不转发给当前上传人；用户名为空或为数字不作为排除依据。已产生的历史积分不在本脚本中清理。
- 默认排除系统管理员，以及文件所在知识库的所有者和有效管理员；同一用户在其他库作为普通上传人时仍可得分。所有者取知识库创建人及有效 `creator` 成员，管理员取有效 `admin` 成员；不再仅凭部门管理员身份排除。
- 忽略账号：额外支持通过 `--ignore-accounts` 过滤指定账号（默认 `admin`），命中账号的文件不发放积分。
- 积分业务时间：按北京时间，早于 `2026-08-01 00:00:00` 上传的文件统一记录为该时刻；从该时刻起上传的文件保留上传时间。缺少上传时间时沿用当前时间兜底。该规则影响新流水的 `occurred_at` 和账户最近获分时间，不修改文件上传时间或已入账流水。
- 积分规则：显式绕过单日积分上限限制进行全额累加，并生成按文件 ID 强绑定的幂等键（`backfill:<level>:<file_id>`），保证重复执行不重复发分。
- 演练预览：`--dry-run` 保留全局汇总，并按积分记账年月（`YYYY-MM`）升序输出每月文件数、用户数、预计积分及用户明细。八月之前上传的文件归入 `2026-08`；同一用户跨月分别列出，总用户数仍按用户 ID 去重。不进行任何数据库写入，预计积分仍未扣除已补发流水。

Usage:

```bash
# 演练预览（推荐在正式发分前先行演练）
PYTHONPATH=./ .venv/bin/python scripts/backfill_space_file_points.py \
  --space-level public \
  --score-per-file 3 \
  --dry-run

# 使用配套 Shell 脚本正式执行
bash scripts/backfill_space_file_points.sh \
  --space-level department \
  --score-per-file 2 \
  --ignore-accounts "admin,system"
```
