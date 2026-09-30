# F073 端到端验收记录

**日期**：2026-09-30　**分支**：`feat/v3.0.0-beta1/073-openapi-task-mode`
**环境**：本地 API（`127.0.0.1:7873`）+ 本地灵思 worker（worktree 代码），连 test 中间件（116：MySQL `langflow`、MinIO、ES、Milvus、OpenFGA）；**Redis 用本地临时容器**（116 的 Redis 16 个库都有他人在用，共用会让 test 的 worker 与本地 worker 互抢 `linsight:queue`）。
**数据库**：test 库直接 `ALTER TABLE linsight_session_version ADD COLUMN api_meta JSON NULL`，**未写 `alembic_version`**（test 跑 release 线，写入本分支的 revision 会让 release 下次部署找不到版本）；F073 合入 release 后迁移按 `column_exists` 跳过。
**测试主体**：服务账号 `f073-e2e`（id 17，资源归属人 = 用户 2），两把密钥：`chat:invoke`（自身身份）、`chat:invoke + delegate`（委托范围仅用户 2）；模型 900（租户任务模式默认模型）。

## 结果

| AC | 验证 | 结果 |
|---|---|---|
| AC-04、AC-05 | `config?run_mode=task` 两种身份：模型、默认模型 900、技能 26 个；工具按身份过滤（服务账号 0 个，用户 2 有代码执行器） | ✅ |
| AC-07 | `config/knowledge` library / space：用户 2 分别 3+（has_more）/ 2 条，服务账号 0 条 | ✅ |
| AC-08 | 自身身份提交 → `task_id`，状态 queued；调用方不再调任何接口，任务执行至 completed | ✅ |
| AC-09 | 缺 `execution` / `sync` → 26060；日常 × async → 26015；`run_mode=research` → 26017 | ✅ |
| AC-12 | 技能含 2 个不存在 → 26062，`data.unavailable` 列出二者 | ✅ |
| AC-13 | 任务模式模型 id=1 → 26066；日常模式同 → 26066 | ✅ |
| AC-14 | 服务账号提交用户 2 能用、服务账号无权的知识库 368 → 403 / 19000；知识空间 3404 → 403 / 18040；未授权工具 → 26067 | ✅ |
| AC-16 | 他人分区的附件引用 → 404 | ✅ |
| AC-17 | 传 `conversationId` → 26061 | ✅ |
| AC-19 | 代表他人提交 `bisheng-docx`：worker 日志 `materialized ['bisheng-docx'] failed []` | ✅（缺失即失败的分支由单测覆盖，未做线上停用时序） |
| AC-21 | 两个任务全程无 `ask_user`（worker 日志 0 次）；代表他人任务答复末尾单列「所做假设」 | ✅ |
| AC-23 | 执行中终止 → terminated、无 result，worker 日志「Task was actively terminated」；再次终止 → 26064；已完成任务终止 → 26064 | ✅ |
| AC-24、AC-25 | 轮询：running 时 `progress` 0/4 → 3/4 → 4/4 单调；排队位置为空（本地 worker 立即取走） | ✅（排队位置非空的情形由单测覆盖） |
| AC-28 | 同一服务账号换 `X-End-User: emp-2` 查询、下载 → 404 | ✅ |
| AC-29、AC-30 | 答复无私有区标记、无 `[Sn]`；产物清单只有 file_id / 名称 / 类型 / 大小 / primary，无路径；`unavailable_deliverables` 为空 | ✅ |
| AC-31 | 下载 md 7882 字节，`Content-Disposition: filename*=UTF-8''…`，内容正确；无直链 | ✅ |
| AC-32 | 代表他人任务：会话 `api_subject_type` 为空、`user_id=2`，出现在用户 2 的工作台会话列表 | ✅（列表层；工作台界面打开渲染待人工，见下） |
| AC-33 | 自身身份任务：会话带 `service_account` / 17 / `emp-1` 标记，不在资源归属人（用户 2）列表中 | ✅ |
| AC-34 | `api_meta` 落库（channel / identity_mode / instructions）；会话名取任务描述首行 | ✅（审计行未逐条查库） |
| AC-35 | 最小表单流程：查配置 → 上传 → 提交 → 轮询 → 下载，自身身份、代表他人各一遍（后者带技能与代码执行器，产出 md + docx） | ✅ |

## 未在本轮覆盖（需人工或另择环境）

- **AC-24 后半 / AC-32 界面**：以用户 2 登录工作台，打开代表他人发起的任务，确认任务面板渲染、执行中查询不影响实时展示。本地未起前端、无 test 账号密码。
- **AC-20**：类型不支持的附件（上传接口本身有类型校验，需构造可上传但解析失败的文件）。
- **AC-38**：workflow 代码节点调用（代码节点默认关闭，需开启后在工作流里写调用代码）。
- **AC-01 / AC-03**：缺权限位、个人访问令牌被拒——端点集成测试已覆盖，线上未另测。
- **MySQL / DM8 迁移**：`f073_linsight_api_meta` 的 upgrade / downgrade 未在真实库执行（test 库只加了列）。

## 清理

- 本地 API、worker 进程与临时 Redis 容器已停止。
- 服务账号 `f073-e2e` 已删除（密钥随之失效）。
- 保留：test 库 `linsight_session_version.api_meta` 列（可空、release 代码不读）；三条测试任务的会话记录（一条在用户 2 工作台可见，标题「审阅附件中的合同……输出 Word 文档」）。
