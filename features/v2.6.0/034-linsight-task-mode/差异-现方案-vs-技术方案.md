# 差异文档：现方案 vs 《技术方案：灵思 Linsight 迁移 deepagents 适配层》

- 版本：v2.6.0 · Feature F034
- 状态：📝 决策记录（供评审 / 回标技术方案）
- 关联：[《技术方案》](../../技术方案-灵思%20deepagents%20适配层设计.md) · [F034 design.md](./design.md) · [PRD](../../任务模式!灵思%202.0/任务模式!灵思%202.0.md)

> **"现方案"** = 本轮评审收敛后的最终决策，由两部分组成：
> 1. **已并入技术方案 §10** 的修订（执行器/HITL/知识库/Skill 约束/模型选择/菜单权限）；
> 2. **尚未并入、本文档首次正式记录** 的工作区/文件模型重构（对原 §9 的结构性替换）。
>
> **权威性**：凡本文档与技术方案 §1–§9 正文冲突，以本文档 + 技术方案 §10 为准。早期的 [F034 design.md](./design.md) 中"执行器=Celery""Skill=MinIO"两条**已作废**（见 §尾"作废与待办"）。

---

## 0. 变更总览

| # | 维度 | 变更类型 | 一句话 |
|---|------|---------|--------|
| A | 执行器 / Worker | ✅ 保持 | 沿用 `worker.py` + Redis queue（F034 早期的 Celery 提案被否） |
| B | HITL 等待 | 🔄 取代 | hold-slot 轮询 → **park-and-release** |
| C | 知识库 RAG | ➕ 定案 | A/B 未定 → **定方案 B** |
| D | Skill 存储 | ⚠️ 加约束 | 沿用磁盘 → **显式部署前提（单机/共享卷）** |
| E | 模型选择 | ➕ 补缺 | 原缺 → **补 PRD §4.1.10** |
| F | 任务模式菜单权限 | ➕ 补缺 | 原缺 → **补 PRD §4.7.7** |
| **G** | **工作区 / 文件模型** | **🧱 重构** | **路径A本地file_dir+自研工具 → MinIO真相+写穿缓存+WorkspaceBackend收口（最大差异）** |
| H | 文档形态 / 门禁 | ➕ 补门禁 | 原无 → **补 Constitution Check + release-contract 登记** |

图例：✅保持 · 🔄取代 · ➕补缺/定案 · ⚠️加约束 · 🧱结构性重构

---

## A. 执行器 / Worker（✅ 保持）

| | 原《技术方案》 | 现方案 |
|---|---|---|
| 调度 | 保留 `worker.py`、`ScheduleCenterProcess`、`LinsightQueue`、`NodeManager`（§1/§4.6） | **一致：沿用** |

- F034 design.md 曾提"退役 worker.py → Celery `linsight_celery`"，**已否决**：用户选择沿用旧 worker 体系，迁移风险更低。执行器层与技术方案对齐，无差异。

---

## B. HITL 等待（🔄 取代 §4.5 / §4.6）

| | 原《技术方案》（§4.5/§4.6） | 现方案（已并入 §10.2） |
|---|---|---|
| 等待机制 | `_wait_for_input_completion` **1s 轮询** MySQL，Worker **原地占 slot** 存活 | `interrupt()` → **释放 semaphore + 退出任务循环**（park） |
| 续跑 | 同存活进程；仅崩溃才从 queue 重拾 + checkpointer | 回答后 **重新入队** → 任一 worker 同 `thread_id` 从 checkpointer 复活 + `Command(resume)` |
| 并发占用 | 数小时等待吃掉一个并发名额（默认 `max_concurrency=5`） | **等待零并发占用** |
| 抗重启 | 正常路径/崩溃路径分叉 | **正常与崩溃路径统一** |

- 理由：引入了 Redis checkpointer 却仍 hold-slot 轮询是"红利没用满"；park-and-release 才把"等待"做成无资源占用 + 天然抗重启。

---

## C. 知识库 RAG（➕ 定案，取代 §5.2）

| | 原《技术方案》（§5.2） | 现方案（§10.3） |
|---|---|---|
| 选型 | A/B **未定**，两路保留 + 配置开关，"倾向 B 需验证" | **定方案 B**（`SearchKnowledgeBase` 作 `BaseTool`），不再保留 A 路与开关 |

- 理由：FR-3.5「知识库检索可见步骤卡」是硬前提（方案 A 注入 system_prompt 则检索不可见）；叠加 token 更省、子任务级 query 更准。

---

## D. Skill 存储（⚠️ 加约束，补 §7 前提）

| | 原《技术方案》（§7） | 现方案（§10.4） |
|---|---|---|
| 载体 | 磁盘 `FilesystemBackend(SKILLS_ROOT)` + DB 元数据 | **一致：沿用磁盘** |
| 部署前提 | 未声明 | **显式约束**：`worker.py` 的 `NodeManager` 为多节点设计，`SKILLS_ROOT` 须为所有 Worker 节点可见的同一卷（单机部署 / 多机挂共享存储二选一） |

- 理由：磁盘方案多节点下不共享，跨节点 Skill 读不到；用户确认沿用磁盘，故以"部署约束 + 备选 MinIO 演进路径"兜底，而非改存储。

---

## E. 模型选择（➕ 补缺，PRD §4.1.10，原方案缺）

| | 原《技术方案》 | 现方案（§10.5） |
|---|---|---|
| 管理端 | 仅 §2.2"model 经 LLMService 注入" | 工作台对话模型行新增「灵思默认模型」单选；**移除「灵思任务执行模型」配置区（模型+执行模式）** |
| 用户端 | 无 | 发起输入区模型选择器，默认选中灵思默认模型，可 per-task 切换 |
| 落地 | — | `config.configurable.model_id` 注入；`_get_llm` 按 per-task model_id；移除 `linsight_executor_mode` 分支 |

---

## F. 任务模式菜单权限（➕ 补缺，PRD §4.7.7，原方案缺）

| | 原《技术方案》 | 现方案（§10.6） |
|---|---|---|
| 菜单 | §6 未提 | 「工作台菜单→首页」下新增「任务模式」子开关 |
| 规则 | — | 父子联动孤儿清理 + 入口/路由双重收口（不手写 403）+ 存量角色回填 + 单/多租户一致 |

---

## G. 工作区 / 文件模型（🧱 结构性重构，对原 §9 的替换 —— 本文档首次记录）

> 这是最大差异。原 §9 的文件逻辑全部挂在两个假设上：① **自研文件工具名**（`add_text_to_file`/`replace_file_lines`/`read_text_file`）；② **本地 `file_dir` 物理扫描**。任务模式收敛到 deepagents 原生工具后两者皆不成立；且文件不能挂 graph state（大 markdown 也不行）。现方案重构如下。

### G 总览

| 子项 | 原《技术方案》（§9 / utils.py） | 现方案 |
|------|------------------------------|--------|
| G1 文件工具 | **自研** `add_text_to_file/replace_file_lines/read_text_file` 作 BaseTool 保留（§9.3.2 路径A） | **deepagents 原生** `write_file/read_file/edit_file/ls`，自研文件工具下线 |
| G2 工作区真相载体 | 本地 `file_dir`（路径A）为工作载体；deepagents 虚拟FS(`state.files`)仅承 Skill+内部态 | **MinIO `workspace/{svid}/` 为唯一真相**；`file_dir` 退化为**写穿缓存**；**文件不挂 graph state** |
| G3 持久化触发 | hook 自研工具名（`handle_step_event_extra` + `step_event_extra_tool_dict`）即时上传 + 成功时 `get_all_files_from_session` 扫 `file_dir` 全量上传 | **自定义 `WorkspaceBackend.write` 写穿**（后端层 hook，工具无关）；E2B 摄入同一路径 |
| G4 产物 vs 中间分类 | `file_name in answer` 文本包含（utils.py:136） | **目录约定 `output/` vs `scratch/`**（`file_name∈answer` 仅兜底） |
| G5 大文件 | 未区分；仅图片结果直传 MinIO | **按 `SIZE_INLINE` 分流**：小文本→cache+写穿；大/二进制→直传 MinIO+指针清单，**不过 cache/state/上下文** |
| G6 代码产出文件 | `sync_files_to_local` 扫描回灌**裸 file_dir** + 图片直传 MinIO | copy-in（小push / 大 presigned URL）+ copy-out（全树扫描→按大小分流经 backend 摄入）+ `output/` 约定 |
| G7 清理 | `finally` 无条件 `rmtree(file_dir)`；中间文件靠"成功时上传"保住 | `rmtree` **只清 cache**（MinIO 是真相，写穿保证最新）；MinIO 按留存期治理 |
| G8 park 持久化 | 文件态依赖 worker 存活/成功上传；park/失败时未上传则丢 | 写穿使 MinIO 恒最新 → **park 即清 cache、resume 重建，文件天然 durable，无需 before_park flush** |

### G 核心模型（现方案）

```
工作区(按 session 唯一) = truth: MinIO workspace/{svid}/...  +  cache: 本地 file_dir(写穿)
收口 = 自定义 WorkspaceBackend(注入 create_deep_agent(backend=...))
  write(p,c): cache.write + minio.put(写穿)        # 不 hook 工具名、不进 state
  read(p,off,lim): cache 命中/懒加载 MinIO, 分页读   # 大 md 不全量入上下文
  ls(prefix): 以 MinIO 为准
```

### G 关键判定（现方案，伪代码）

```
摄入(附件/E2B/写工具) → 一律经 backend.write → cache + MinIO 写穿
分类: 路径前缀 output/ = 产物区; scratch/ = 中间(同样持久, 不进产物区)
大小: <=SIZE_INLINE 文本 → cache+写穿; 大/二进制 → 直传 MinIO + 指针清单
代码产出: 入沙箱(小push/大presigned URL) → 跑 → 全树扫描出沙箱 → 按大小分流摄入 → 枚举给模型
清理: rmtree(cache) 任意退出都安全; MinIO 仅终态删前缀; park 不删
```

### G 满足的约束

- **不挂 state**：正文只在 MinIO+cache，graph state/checkpointer 只存"图怎么走"。
- **大 markdown**：truth 是对象存储（任意大）；`read(offset,limit)` 分页；指针块零正文。
- **工作区统一**：deepagents 工具 / E2B / 附件 / 产物全部经 `WorkspaceBackend` 收口；多节点从 MinIO 物化同一工作区。
- **park durable**：写穿保证 MinIO 恒最新，消掉了"file_dir 模型"才需要的 before_park flush。

---

## H. 文档形态 / 门禁（➕ 补门禁）

| | 原《技术方案》 | 现方案（§10.8 + F034 design.md §2/§6） |
|---|---|---|
| Constitution Check | 无 | 补 C1–C7 门禁核对 |
| release-contract 登记 | 无 | 补登记 F034：领域对象 `LinsightSkill`、110 错误码段、`linsight_skill` 表 + Alembic |

---

## 作废与待办

**作废（不再作为方案依据）：**
- F034 [design.md](./design.md) 的「执行器=Celery `linsight_celery`」「Skill 正文=MinIO」两条决策 —— 被"沿用 worker.py""Skill 走磁盘"覆盖。
- 技术方案 §9.3.2「路径 A：本地 file_dir + 自研文件工具」及依赖自研工具名/file_dir 扫描的持久化逻辑（§9.4 / `utils.py` 的 `step_event_extra_tool_dict`、`get_all_files_from_session`、`read_file_directory`、`file_name in answer`）—— 被 G 重构取代。

**待办：**
1. **§9 替换版成文**：把 G 的工作区状态机（`WorkspaceBackend` + 写穿 + 分流 + 代码产出 copy-in/out + 目录约定 + 清理）正式写入技术方案 §9，删除路径 A 与自研文件工具依赖。
2. **release-contract 登记 F034**（领域对象 / 错误码段 / 新表）。
3. **POC 验证项汇总**：① deepagents 允许注入自定义 `FilesystemBackend`（替代 `virtual_mode`）且 E2B 产出可经其写入；② 子图 `subgraphs=True` 事件冒泡 + 并行不串流；③ Redis checkpointer park-and-release 隔任意时长续跑保真（R3）；④ 中文模型 `call_reason` 填写遵从率 + Skill progressive disclosure 命中率（R1）；⑤ presigned URL 大文件 seed 的脚本遵从率。

---

## 修订历史

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-10 | 初版：汇总现方案 vs 技术方案 8 项差异；首次正式记录 G 工作区/文件模型重构（MinIO 真相 + 写穿缓存 + WorkspaceBackend）作为对原 §9 的替换 | GuoQing Zhang |
