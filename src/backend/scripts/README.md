# Script Directory

This directory contains manual maintenance and migration scripts for the backend.

## Knowledge Space Scripts

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

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --concurrency 4
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --space-id 10 --folder-id 20
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --file-id 101 --file-id 102
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --space-level public
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --space-level department --status failed --status waiting --status violation

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

### `move_knowledge_space_files.py`

扫描一个或多个来源知识空间的 `SUCCESS` 真实文件，可按来源文件夹、门户一级分类 code、
门户二级分类 code 缩小范围。默认按分类 `label` 自动匹配公共知识空间及其根目录
直属文件夹；也可显式指定目标知识库和目标文件夹。版本链作为一个迁移单元整体处理。

脚本默认为 dry-run；只有显式传入 `--apply` 才会写入目标并删除来源。每次运行都会在
`--report-dir` 下生成 JSON 运行报告；apply 模式另外生成可用于手工还原的 JSONL 回溯记录。

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
```

参数：

- `--source-space-id`：必填、可重复；多个 ID 取并集，且必须属于同一租户。
- `--source-folder-id`：可重复；每个文件夹都递归包含所有子孙文件，多个 ID 取并集。文件夹必须
  存在于本次来源空间中。
- `--source-category-code`：可重复；按门户一级分类 code 过滤，多值取并集，code 不区分大小写。
- `--source-subcategory-code`：可重复；按门户二级分类 code 过滤，多值取并集，code 不区分大小写。
  同时指定一级分类时，二级分类必须属于所选一级分类。
- `--target-space-id` 与 `--target-folder-id`：必须同时传入或同时省略。传入后，所有选中迁移单元
  都进入该文件夹；目标可为公共或部门空间，文件夹可为任意层级，但必须属于目标空间且与来源
  处于同一租户。团队和个人空间不允许作为显式目标。
- `--report-dir`：JSON 运行报告目录，默认为 `migration_reports/knowledge_file_move/`。
- `--rollback-record-file`：apply 模式的 JSONL 回溯文件。省略时在 `--report-dir` 下按 `run_id` 自动命名。
  文件以 `0600` 权限排他创建，如已存在则预检失败，不会覆盖或追加到旧记录。
- `--batch-size`：每完成多少个迁移单元后 `flush + fsync` 一次 JSONL，必须为正整数，默认 `10`。
  单个文件算一个单元，整条版本链也只算一个单元。
- `--apply`：执行真实移动；省略时只生成 dry-run 计划与报告，不创建 JSONL 回溯文件。

筛选组合：

- 同一维度重复参数之间为 OR：多个来源空间 OR、多个来源文件夹 OR、多个一级分类 OR、
  多个二级分类 OR。
- 不同维度之间为 AND：`来源空间 AND 来源文件夹 AND 一级分类 AND 二级分类`。未传入的可选维度
  不参与过滤。
- 版本链中的每个版本都必须命中全部已启用的过滤条件，否则整条版本链跳过；一、二级分类也必须
  在整条版本链中一致。
- 显式目标只替代自动路由，不取消分类校验或源过滤。

路由、回溯记录与安全性：

- 仅处理 `file_type = FILE` 且 `status = SUCCESS` 的文档。
- 一级分类 code 从 `file_encoding` 解析，二级分类 code 来自 `file_subcategory_code`；两级都必须
  能在门户配置中解析出 `label`，否则跳过。
- 一级分类 `label` 必须唯一精确匹配 `level = public` 的知识空间名称；二级分类 `label` 必须
  唯一精确匹配该空间根目录下的直属文件夹名称。匹配前会去除普通首尾空白、`U+200B`
  零宽空格和 `U+FEFF` BOM；脚本不会递归匹配、模糊匹配或自动创建目标。
- 移动后文件所有者改为目标知识空间所有者；OpenFGA 只重建目标 owner/parent 必要关系，
  不复制来源访问权限。
- 已通过和待审核标签以复制前保存的来源快照为唯一依据，精确替换到新目标文件；若校验仍不一致，
  报错会列出来源和目标双方的标签 ID，并在删除来源前清理目标残留。
- 目标文件夹存在同名文件、目标空间任意位置存在相同 MD5，或来源/目标向量模型不一致时，
  跳过文件且保留来源。多个来源文件互相冲突时按来源空间 ID、文件 ID 稳定选择第一个。
- 版本链作为整体迁移：所有版本必须位于本次来源范围、均为 `SUCCESS`、分类完整、目标一致、
  模型兼容且无目标冲突；否则整条链跳过。成功后使用新文件 ID 重建版本号、主版本和逻辑文档关系。
- 每个文件按“复制 → 校验 → 删除来源”执行。失败时保留或恢复来源，并尽力清理目标残留；
  版本链按整链 Saga 执行。任一迁移单元失败时立即停止后续单元并返回非零退出码，业务跳过不计为失败。
- JSONL 按顺序记录 `run_started`、`unit_started`、`unit_succeeded` / `unit_failed`、
  `run_completed` / `run_failed` / `run_interrupted`；成功单元包含来源与目标文件、空间、文件夹、
  分类、标签、权限、存储对象、索引统计和版本图元数据。当前脚本不提供自动回滚命令；保留目标数据时，
  可依据该记录手工还原。
- 首次 `Ctrl-C` 不会在单元内强行中断；脚本完成当前单元、强制落盘 JSONL 后以退出码 `130` 结束。
  普通异常也会尝试写入终止事件并落盘。`kill -9`、进程崩溃或断电无法保证当前未落盘批次的记录完整。
- JSONL 写入失败时，脚本停止迁移，并尝试补偿当前尚未持久化的批次；之前已落盘的批次保持已迁移状态。
- `--apply` 会删除来源文件并生成新的目标文件 ID。收藏、分享链接及其他保存旧文件 ID 的引用不会迁移，
  执行前必须先审核 dry-run 报告并确认这些引用中断的影响。

## Export Scripts

### `get_knowledge_file_chunks.py`

按 `knowledge_file_id` 查询一个知识文件在 Elasticsearch 中的全部 chunk，并将文本和元数据以 JSON 输出到标准输出。脚本只读，不会修改数据库或索引。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/get_knowledge_file_chunks.py --knowledge-file-id 123
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
