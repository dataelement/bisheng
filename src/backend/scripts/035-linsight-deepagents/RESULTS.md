# F035 POC Spike 结论（Wave 0）

执行环境：本机 macOS + config.yaml 中间件（MySQL/Redis 可用）；Python 3.11.13；deepagents≥0.6.3 / langgraph 1.2.2 / langgraph-checkpoint-redis。执行日期 2026-06-11。

| # | 门槛 | 结论 | 摘要 |
| - | ---- | ---- | ---- |
| P1 | 自定义 FilesystemBackend 注入 | ✅ GREEN | `create_deep_agent(backend=...)` 接受自定义 backend；内核可驱动任意存储层 |
| P2 | subgraphs=True 子图冒泡 + 并行不串流 | ✅ GREEN | 子图事件以 `(namespace, chunk)` 冒泡，namespace=`nodename:uuid`；并行子图各自独立、不交叉 |
| P3 | park-and-release + 跨重启续跑保真 | ✅ 机制 GREEN / 传输 GREEN（自研） | interrupt/resume 续跑机制保真；`langgraph-checkpoint-redis` 依赖 Redis Stack（已弃用），改为自研 `PlainRedisCheckpointer`（Wave 0 已交付） |
| P4 | call_reason 遵从率 + Skill 命中率≥95% | ⛔ BLOCKED(env) | 无可用中文模型（DB 模型凭证全失效）；评测脚本就绪 |
| P5 | required_files 声明遵从率 + 修复率 | ⛔ BLOCKED(env) | 无可用模型 + config 无 E2B；评测脚本就绪 |

## P1 — backend 注入（GREEN）

- `create_deep_agent` 含 `backend` 参数，注入自定义 `FilesystemBackend` 子类成功装配，无需 model。
- **关键发现（影响 C2 契约 → Track C）**：deepagents 真实 backend 协议是 `BackendProtocol`，方法签名与返回类型与契约 C2 的「简化 4 方法」不同：
  - `read(file_path, offset=0, limit=2000) -> ReadResult`（按行，默认 2000 行）
  - `write(file_path, content) -> WriteResult`
  - `ls(path) -> LsResult`
  - `edit(file_path, old_string, new_string, replace_all=False) -> EditResult`
  - 另有 `glob/grep/upload_files/download_files`（含 `a*` 异步版）。
- **行动项**：C2 的 `WorkspaceBackend` 须**继承 `deepagents.backends.filesystem.FilesystemBackend` 并实现 `BackendProtocol`**（返回 `*Result`），而非契约里写的 `bytes/str`。`test/linsight/fixtures/fake_workspace_backend.py` 是给 H/B 的**概念级**内存 stub（简化签名），Track C 的真实实现须按协议对齐；建议 C2 小节补一句「以 deepagents BackendProtocol 为准」。

## P2 — 子图事件流（GREEN）

- `astream(stream_mode="updates", subgraphs=True)` 时，子图内部节点更新以非空 namespace 冒泡到父流。
- namespace 形如 `('sub1:b11ef08c-...',)`，即 `节点名:run_uuid`。**C1 的 `ExecStep.namespace` 归并可直接用该前缀做层级渲染**。
- 两个并行子图的事件 namespace 互不混淆（无交叉串流）。

## P3 — checkpointer park-and-release（机制 GREEN / 传输 BLOCKED）★ 需决策

- **机制 GREEN**：图在 `interrupt()` 暂停（`next=('ask_human',)`），`Command(resume=...)` 后日志连续保真、resume 注入值生效。证明 deepagents/langgraph 的 HITL 续跑语义成立（Track B 的 park-and-release 模型可行）。
- **传输 BLOCKED**：`langgraph-checkpoint-redis`（AsyncRedisSaver/AsyncShallowRedisSaver）经 redisvl 依赖 **RediSearch 模块**（`FT.CREATE`/`FT._LIST`）。现网/配置 Redis `MODULE LIST` 为空（plain Redis），`asetup()` 即抛 `unknown command 'FT._LIST'`。
- **影响 C5**：契约 C5「Redis checkpointer 复用 RedisManager（plain Redis）」**不成立**。需在三选一中决策：
  1. **部署 Redis Stack**（RediSearch+RedisJSON），灵思 checkpointer 用独立 Redis Stack 实例/库；
  2. **自研 plain-Redis checkpointer**（把 checkpoint 序列化进普通 string/hash key，不用 FT 查询）；
  3. 换持久化（如 DM8 表 checkpointer——但 design §2.3 选 Redis 正是为绕开 DM8）。
- **建议**：方案 1（部署 Redis Stack）改动最小、最贴合 design；方案 2 工作量落在 Track B。**这是一个待用户/团队拍板的设计项**（已在 tasks.md §8 记录待补）。

## P4 / P5 — 模型遵从率（BLOCKED on env，脚本就绪）

- 现象：DB 中 online 的 llm 模型在本机调用全部失败（401 鉴权失效 / 404 / invalid proxy URL `admin` / subscription key 失效）——本机无可用中文模型端点；config 亦未配置 E2B key。
- 这两项本质是 **Wave 3 验收门槛**（命中率≥95% 需评测集 + 多次采样 + Track A 真实装配的内核），Wave 0 仅要求「有结论」。
- 交付：`poc_p4_*.py` / `poc_p5_*.py` 为**可运行评测骨架**（含模型探测、call_reason/skill 命中、required_files 声明/修复统计），配置基线模型（+E2B）后即可跑；directional 验证下放 Wave 1（Track A/D/C），定量门槛在 Wave 3。
