# Design 增量 · 任务模式 Skill 运行时发现支持多节点（F035 follow-up）

> 版本：v3.0.0 · 状态：方案待实现 · 关联：[design.md](./design.md) §7 / §9 · [constitution C8](../../../docs/constitution.md#c8-no-shared-state-on-the-local-filesystem) · [08-deployment.md](../../../docs/architecture/08-deployment.md) · [Skill 能力恢复方案](../../../docs/PRD/2.6%20灵思%20deepagents%20迁移%20PRD/灵思任务模式%20Skill%20能力恢复方案.md)
> 本文是 F035 Skill 存储迁到对象存储之后的**运行时发现层**收尾：去掉 `SkillsMiddleware` 对节点本地目录的依赖，使 API 与灵思 Worker 分机部署时技能枚举与加载一致。
>
> **一句话**：bundle 存储已经跨节点；发现仍绑本地 `file_dir`。改 `WorkspaceBackend.ls` 合成目录项，再让 `SkillsMiddleware` 直接挂工作区 backend。

---

## 1. 背景与问题

### 1.1 已经做完的：存储层（不要重做）

commit `2d0c645ba`（「技能 bundle 改存对象存储，多节点下不再各存各的」）把 Skill **正文**从节点本地 `SKILLS_ROOT` 迁到 MinIO 内容寻址：

```
linsight/skills/{tenant_id}/{name}/{content_hash}.zip
```

DB 行（`linsight_skill`）只持指针（`object_path` + `content_hash`）。节点按 hash 本地物化，cache 可丢。内置技能由 API 进程 seeder 写入同一对象前缀；Worker 不再需要本地 `built-in/` 目录。这条已写入宪法 C8 与 `docs/architecture/08-deployment.md`「灵思技能 bundle 迁至对象存储」。

`design.md` §7.1 里「多机须挂 `SKILLS_ROOT` 共享卷」的约束已划掉。**不要再走 NFS 共享卷。**

### 1.2 还没做完的：运行时发现层

任务启动走 Fork X（复制时过滤）：`materialize_session_skills` 把 `enabled ∩ selected` 的 bundle 写进工作区 `/skills/<name>/`（MinIO + 本地 `file_dir` 写穿）。随后 `create_linsight_agent` 装配：

```python
# agent_factory.py
skills_advertised = bool(skills_present and file_dir)
SkillsMiddleware(
    backend=FilesystemBackend(root_dir=file_dir, virtual_mode=True),
    sources=[("/skills/", "Skills")],
)
```

原因写在注释里：deepagents `SkillsMiddleware` 靠 `ls` 返回的 **`is_dir=True` 目录项**发现技能；而 `WorkspaceBackend.ls` 对 MinIO 做 `list_objects(..., recursive=True)`，只返回文件，`is_dir` 几乎永远是 `False`。原生 `skills=`（复用工作区 backend）因此枚举到 0 个技能。

于是发现路径绑死在**本机 `file_dir` 里已经有真实目录**。单次任务、执行节点上 copy 成功时能用；下列场景会失效或变脆：

| 场景 | 现象 |
|------|------|
| HITL park 后换节点 resume，copy 失败或 `file_dir` 未就绪 | 中间件枚举到 0 个技能，任务照跑（静默降级） |
| 存量行 `content_hash=''`（未在持有残留 bundle 的机器上跑迁移脚本） | B 机 MinIO 无对象，copy 得到空 bundle |
| 把 `skills_cache_dir` / `file_dir` 指到共享盘 | 违反 C8，多进程抢同一 cache 目录 |

### 1.3 目标形态

| 层 | 权威存储 | 本地盘角色 |
|----|----------|------------|
| Skill bundle（租户库） | `linsight/skills/{tenant}/{name}/{hash}.zip` | 按 hash 物化的 disposable cache |
| 本轮白名单副本 | `workspace/{svid}/skills/<name>/...` | 写穿 cache；换节点可从 MinIO 重建 |
| 技能发现 | 同一 `WorkspaceBackend`（MinIO `ls` + 懒读） | **不再要求**发现前本地目录已存在 |

Fork X 复制闸门**保留**：模型物理上看不到未授权技能。变的只是「发现不再依赖本机目录已经在」。

---

## 2. 方案

分三步，必须按序合入。步骤 1 未合就做步骤 2，会枚举到 0 个技能。

### 步骤 1 — `WorkspaceBackend.ls` 合成一级虚拟目录项

文件：`src/backend/bisheng/linsight/domain/services/workspace_backend.py` 的 `ls()`。

**保持现有递归文件列表**（agent 的 `ls` 工具、现有单测都依赖「能看到文件」），**额外**按所列前缀的下一级 path segment 合成目录项。不要改成完全非递归，否则模型一次 `ls("/output")` 看不到嵌套文件。

伪逻辑：

```python
# 现有：recursive list → file entries（is_dir=False）
file_entries = [...]

# 新增：对 prefix 下「还有更深一层」的 key，抽出 immediate child 作为目录
# 例：ls("/skills/") 看到
#     skills/foo/SKILL.md
#     skills/foo/scripts/a.py
#     skills/bar/SKILL.md
#     → 合成
#     FileInfo(path="/skills/foo", is_dir=True, size=0)
#     FileInfo(path="/skills/bar", is_dir=True, size=0)
#     不合成 /skills/foo/scripts（那是 ls("/skills/foo/") 的事）
dir_entries = synthesize_immediate_dirs(rel_prefix, file_entries)

return LsResult(entries=dir_entries + file_entries)
```

约束：

- 目录 path 与文件一样，去掉 `workspace/{svid}/` 前缀，以 `/` 开头，避免 `_object_key` 二次拼接。
- 只合成 **immediate child**，避免 `ls("/skills/")` 把 `scripts/` 也当成技能。
- 与已有 `test_ls_authoritative_from_minio` 兼容：那些断言是 `any(endswith file)`，多几个 dir 条目不会破。

辅助函数放在同文件，纯函数、可单测，例如 `_immediate_dir_entries(rel_prefix, file_paths) -> list[FileInfo]`。

### 步骤 2 — `SkillsMiddleware` 改挂 `WorkspaceBackend`

文件：`src/backend/bisheng/linsight/domain/services/agent_factory.py`。

现在：

```python
SkillsMiddleware(
    backend=FilesystemBackend(root_dir=file_dir, virtual_mode=True),
    sources=[("/skills/", "Skills")],
)
```

改为：

```python
SkillsMiddleware(
    backend=backend,  # 本轮注入的 WorkspaceBackend
    sources=[(f"/{WORKSPACE_SKILLS_DIR}/", "Skills")],
)
```

门控从 `skills_present and file_dir` 改为 `skills_present and backend`：发现不再要求本地目录先有文件。`file_dir` 仍留给代码解释器 `os.walk`，与 skill 枚举解耦。

`SkillsMiddleware` 不注册文件工具（deepagents 0.6.8 / 0.6.12 已核实），第二套 backend 不会 shadow `write_file`。改成同一 `WorkspaceBackend` 后，连「两套 backend 路径要对齐」这层都没有了。

`materialize_session_skills` **保留**：它仍是白名单闸门，把允许的 bundle 写进 `workspace/{svid}/skills/`。copy 失败继续走现有 `_push_skill_load_failure`，禁止静默跳过。

Resume / 换节点：copy 幂等（同 key 再 PUT）。即便本机 `file_dir` 是空的，`ls` 读 MinIO 也能看到 `/skills/<name>/`。

### 步骤 3 — 空 `content_hash` 与 `exists()` 以 MinIO 为准

两处加固，改动很小：

1. `skill_provisioning._collect_bundle_pairs`：`content_hash` 为空时直接视为失败（不要去物化 `.../.zip`），日志带上 `tenant/name`。存量未迁移技能会进 `failed` 并推给用户，而不是空跑。
2. `SkillStore.exists()`：不要「本地 cache 有 `SKILL.md` 就 True」。以 MinIO `object_exists` 为准，避免 A 机删了对象、B 机 cache 还谎称存在。`materialize()` 的 cache hit（目录名即 hash）可以保留，那是读路径加速。

---

## 3. 文件级清单

| 文件 | 动作 |
|------|------|
| `linsight/domain/services/workspace_backend.py` | `ls()` 合成 immediate 目录项；抽出纯函数 |
| `linsight/domain/services/agent_factory.py` | `SkillsMiddleware(backend=workspace_backend)`；门控不再依赖 `file_dir` |
| `linsight/domain/services/skill_provisioning.py` | 空 hash 显式失败；注释改为「发现走 WorkspaceBackend，不再依赖本地 dir」 |
| `linsight/domain/services/skill_store.py` | `exists()` 只信 MinIO |
| `test/linsight/test_workspace_backend.py` | 新增：`ls("/skills/")` 对嵌套文件合成 `is_dir=True` 的 `/skills/foo` |
| `test/linsight/test_skill_provisioning.py` | `TestEnumerationLoop` 改为真实 `WorkspaceBackend` + `FakeMinio`，**禁止**再用 `FilesystemBackend(file_dir)`；加「空 `file_dir` / 另一 cache 根」仍能枚举 |
| `test/linsight/test_skill_store.py` | `exists()` 在 cache 有、MinIO 无时返回 False |
| `docs/architecture/08-deployment.md` | 补一句：运行时发现已不依赖节点本地 `/skills` 目录；`file_dir` 仍是代码解释器缓存 |

不改：`SkillStore` 的内容寻址布局、`linsight_skill` 表、Fork X 复制闸门、内置技能 seeder（已写入 MinIO，Worker 不需要再 seed）。

---

## 4. 验收标准

1. **跨节点 CRUD + 执行**：API 节点 A 上传技能 → Worker 节点 B（空 `skills_cache_dir`、空 `file_dir`）跑勾选了该技能的任务 → `SkillsMiddleware` 枚举到该 name，模型能 `read_file` 到 `SKILL.md` 和附属文件。
2. **HITL 换节点**：A 机 park → B 机 resume → 技能仍在，不丢能力、不静默。
3. **白名单**：未勾选 / `enabled=0` 的技能，B 机 `ls("/skills/")` 看不到对应目录。
4. **交付物**：`output/` 仍落工作区，不写进技能对象前缀（shadow 不回归）。
5. **存量空 hash**：任务时间线出现 skill load failure，而不是「看起来没选技能」。
6. **回归**：`test_ls_authoritative_from_minio`、`test_skill_provisioning` 现有用例、代码解释器 `os.walk(file_dir)` 路径不动。

单测用两个 `SkillStore(root=...)` + 同一个 `FakeMinio` 模拟 A/B 节点，不必真起两台机器。

---

## 5. 明确不要做的事

- 不要把 `SKILLS_ROOT` / `file_dir` / `skills_cache_dir` 做成 NFS 共享卷。
- 不要让 Worker 再从镜像 `builtin_skills/` 直接加载（seeder 已把内置技能发到 MinIO，再开第二条路径会重新引入节点差）。
- 不要把 `WorkspaceBackend.ls` 改成完全非递归：会改变 agent 文件工具行为，超出本次范围。
- 不要在 Alembic 里做 bundle 数据迁移（DDL-only）；空 hash 继续靠 `scripts/migrate_skills_to_object_storage.py`。
- 不要重做存储层（内容寻址、`content_hash` 列、seeder）。那已经落地。

---

## 6. 落地顺序与工作量

| 顺序 | 内容 | 规模 | 依赖 |
|------|------|------|------|
| 1 | `ls` 合成目录项 + 单测 | 小 | 无 |
| 2 | `SkillsMiddleware` 改挂 WorkspaceBackend + 枚举单测改 FakeMinio | 中 | 必须先合 1 |
| 3 | 空 hash / `exists()` 加固 | 小 | 可与 1 并行 |
| 4 | `08-deployment.md` 补一句；有环境则做一次 A 上传 B 执行的手工验收 | 运维 | 2 合入后 |

若当前环境技能在 B 机仍不生效，先查 `content_hash` 是否为空、以及 `migrate_skills_to_object_storage.py` 是否在**持有本地残留 bundle 的那台 API 机**跑过——那是升级残留，不是本方案能替代的。

---

## 7. 现状锚点（写方案时的代码位置）

| 职责 | 位置 |
|------|------|
| Skill 对象存储 + 本地 hash cache | `linsight/domain/services/skill_store.py` |
| 本轮复制闸门 | `linsight/domain/services/skill_provisioning.py` · `materialize_session_skills` |
| 装配 SkillsMiddleware | `linsight/domain/services/agent_factory.py`（`skills_advertised` 一段） |
| 工作区 `ls`（只返回文件） | `linsight/domain/services/workspace_backend.py` · `ls()` |
| 任务启动触发复制 | `linsight/domain/task_exec.py` · `_create_agent` |
| 存量空 hash 窄回填 | `linsight/domain/services/skill_bundle_backfill.py`；运维脚本 `scripts/migrate_skills_to_object_storage.py` |

---

## 8. 核实结论（2026-09-08，LineWalker）

> 本节是对 §1–§6 的**核实批注**，不是方案修订。做了两轮独立核查：一轮追发现链路的调用顺序，一轮不设预设地扫多节点缺口。
>
> **一句话**：病因诊断不成立（发现层当前不会失效），但"skill 这块有问题"的直觉是对的 —— 真缺陷在别处，其中一条正是本方案步骤 3.2 顺手提到的。**建议只采纳步骤 3.2，步骤 1/2 不做。**

### 8.1 §1.2 的三个失效场景，逐条核对

| 方案称 | 核实结果 |
|------|----------|
| HITL 换节点 resume，copy 失败或 `file_dir` 未就绪 → 枚举 0 个技能（静默降级） | **不成立**。三条 agent 路径（`task_exec.py:529` resume / `:646` continue / `:732` execute）**全部**走 `_create_agent`，而 `materialize_session_skills` 就写在它体内（`:1083`）、`create_linsight_agent`（`:1088`）之前。`file_dir` 在两个 asynccontextmanager 的 `yield` 之前赋值（`:323` / `:497`），`_init_file_directory` 首行就是 `os.makedirs`，不存在"未就绪"。copy 失败时 `skills_present=False` → 中间件**根本不挂载**，且 `_push_skill_load_failure`（`:1087`）会把失败技能名推成 timeline 步骤 —— **不是静默** |
| 存量行 `content_hash=''` → copy 得到空 bundle | 现象在，但**已经是显式失败**：异常 → `failed.append(name)` → 推给用户（`skill_provisioning.py:117-132`）。步骤 3.1 的收益只是日志分类更准，不是行为修复 |
| 把 `skills_cache_dir` / `file_dir` 指到共享盘 | 配置误用，与代码无关。配置项 description 已写死 *"Do NOT point this at a shared volume"*（`core/config/settings.py:485-489`） |

**方案漏掉的关键前提**：`WorkspaceBackend.upload_files` 是 **先 `_cache_write` 再 `_minio_put_sync`**，且 `_cache_write` 自动 `mkdir(parents=True)`。所以枚举发生时，本机 `file_dir` 必然已被**当次运行**填好——发现层不需要"上一次运行留下的目录"。这条契约已被 `test/linsight/test_skills_zone_readonly.py:112` 的 `_cache_read` 断言锁定。

**方案中描述正确的部分**（这几条核实无误，不要因为上面的结论一并推翻）：`SkillsMiddleware` 确实不注册任何文件工具（deepagents 已装版本 **0.6.12**，`middleware/skills.py:786-834` 的 `__init__` 无 tools）；`WorkspaceBackend.ls` 确实只出文件条目（`is_dir` 恒 `False`），原生 `skills=` 复用工作区 backend 会枚举到 0。

### 8.2 步骤 1 / 2 建议不做的理由

1. **步骤 1 会波及 `glob` 和 `grep`（方案未评估）**。`WorkspaceBackend` 的 `glob` 与 `grep` **都直接消费同一个 `ls` 的 entries**：`glob` 遍历 entries 匹配即返回 → 合成的 `/skills/foo` 目录项会作为结果交给模型；`grep` 对每个条目调 `_materialize` 去 MinIO 拉取 → 每个合成目录项一次注定失败的 GET。更要紧的是 deepagents 的 `ls` **工具**只把 path 列表返回给模型（`middleware/filesystem.py:991-997`，`_apply_permissions_to_ls_results` 把 `is_dir` 丢掉），模型会看到无扩展名的 `/skills/foo` 混在文件路径里，可能去 `read` 它。方案 §5 只写了"不要改成完全非递归"，没有覆盖这两个消费者。
2. **步骤 2 有实现级风险**：`WorkspaceBackend.__init__`（`workspace_backend.py:483-496`）**没有调用 `super().__init__()`**，继承自 `FilesystemBackend` 的 `self.cwd` / `self.virtual_mode` / `self.max_file_size_bytes` 全部未设置。把 `SkillsMiddleware` 直接挂上去之前，必须确认其调用链不碰这些继承属性，否则是 `AttributeError`。
3. **步骤 2 的门控改动是 no-op**：`skills_present and file_dir` 中 `file_dir` 恒非空（见 8.1）；改成的 `skills_present and backend` 中 `backend` 也恒非 `None`（`agent_factory.py:892-893` 有 `_default_backend` 兜底）。两者都等价于 `bool(skills_present)`。

**另有一个方案没发现、且换 backend 也修不掉的机制**：枚举结果被 checkpoint 持久化。枚举只发生在 `before_agent` / `abefore_agent`（`middleware/skills.py:941` / `:987`），结果写进 state 的 `skills_metadata`；短路条件仅判断键是否存在：

```python
# deepagents/middleware/skills.py:960-961
if "skills_metadata" in state:
    return None
```

（`PrivateStateAttr` 只影响 input/output schema 冒泡，它仍是 graph channel，照常被 checkpointer 持久化。）`_resume_workflow` 用 `Command(resume=...)` 从中断处续跑，entry node **不重放**，压根到不了枚举；`_continue_workflow` 会到达但被这行直接短路。

这对多节点**无害**：模型 `read_file("/skills/<name>/SKILL.md")` 走的是 `WorkspaceBackend`（MinIO 权威），不是中间件那个 `FilesystemBackend`，跨节点照样读得到。清单也不会与实际复制的不一致 —— 追问虽复用同一 svid + thread，但 `/workbench/continue` 端点只接受 `session_version_id` + `question` 两个参数（`linsight/api/endpoints/linsight.py:300-305`），没有 skills 入参，`session_model.skills` 不可变。

### 8.3 核查中扫出的真缺口（本次不改，留待排期）

主链路多节点是通的，但以下 5 条是真的。**没有一条能靠步骤 1/2 修好。**

| # | 缺口 | 性质 | 用户感知 |
|---|------|------|----------|
| **P0-1** | `S3Error` 击穿三处降级 handler → 技能详情页 500 | 当前代码就坏（触发条件：对象缺失） | 报错，但是**错误的报错**（裸 S3Error + 500，运维会误判 MinIO 挂了） |
| **P0-2** | 入队→执行之间技能被停用/删除 → 丢技能 | 当前代码就坏 | **完全静默** |
| **P1-3** | `exists()` 先看本地缓存，seeder 的自愈永不发生 | 需对象被带外删除 | 各节点表现不一致，**且重启修不好** |
| **P1-4** | E2B 拿不到技能脚本（顺序倒置） | 仅 E2B 配置 | 脚本 `FileNotFoundError` → 撞 tool-loop breaker |
| **P1-5** | `SkillService` 在事件循环里做同步对象存储 I/O | 多副本才明显 | 静默，只表现为偶发慢 |

**P0-1**：`SkillStore.materialize` 只处理 `data is None`（`skill_store.py:397-399`），但生产 MinIO 在 NoSuchKey 时是 `raise _thaw_s3_error(e)`（`core/storage/minio/minio_storage.py:509` / `:512`），**从不返回 None**；且 skill 的 object key 刻意不带 `tenant_{code}/` 前缀（`skill_store.py:279-289` 有注释说明理由），`_translate_to_root_prefix` 返回 `None`，连 F017 回退都不会吞掉它。于是三处降级全部失效：`skill_store.py:357-359`（`list_files` 的 `except FileNotFoundError`）、`skill_service.py:150`（`get_detail` 的空预览降级）、`skill_service.py:169`（`read_bundle_file` 的 11053 业务码）。额外：`get_detail` 里的 `list_files(...)` 写在 `SkillDetail(...)` 的构造参数里（`skill_service.py:159`），**根本不在 try 块内**。
> **测试是假绿**：`test/linsight/fixtures/fake_minio.py:50-53` 的 `get_object_sync` 在缺失时返回 `None`，所以 `test_skill_store.py:178-180` 的 `pytest.raises(FileNotFoundError)` 只在假 MinIO 下成立。修这条时必须同步把 fake 改成抛 `S3Error`，否则改完仍然测不出来。

**P0-2**：`skill_provisioning.py:104-105` 的 `wanted = sorted(name for name in selected if name in enabled)` —— 被 governance 剔除的名字**既不进 `copied` 也不进 `failed`**，而 `task_exec.py:1086-1087` 只在 `failed` 非空时推时间线。用户勾选技能提交 → 队列积压或任务在 `ask_user` park 住 → 期间管理员停用/删除该技能 → worker 取到任务时直接跳过，`skills_present=False`，"技能优先"整段提示消失。前端问题卡片上的技能 chip 还在，模型行为像没选过技能。**多节点把窗口从单机同进程的毫秒级放大到跨 Redis 队列 + park-and-release 的分钟至小时级** —— 这是本方案的问题意识里唯一真正对的那部分，但方案没识别出它。

**P1-3（= 本方案步骤 3.2，独立核查佐证，建议单独采纳）**：`skill_store.py:299-301` 的 `exists()` 一旦本地缓存有 `SKILL.md` 就短路返回 `True`，不探对象。唯一调用方是 seeder 的 `_already_published`（`builtin_skill_seeder.py:117`），而那里的 docstring 明确写着这次探测的意义就是"对象被带外删除/损坏时下次启动自愈"。又因为 `write_bundle` 上传后顺手种了本地缓存（`skill_store.py:326-329`）且缓存无 GC，跑过一次 seeder 的节点缓存永久是热的。后果：MinIO 上 `linsight/skills/` 前缀被误删后，该节点重启永远判 `unchanged`、**永不重新发布**，而其它节点 500 / 技能加载失败 —— 表现不一致且"重启就能修"的心智模型是错的，最费排查时间。

**P1-4**：`_generate_tools`（`task_exec.py:716`）里用 `os.walk(file_dir)` 构造 E2B 的 copy-in 集合（`workbench_impl.py:2185-2198`）是**构建时快照**，而 materialize 在 `_create_agent`（`task_exec.py:732` → `:1083`）才把 bundle 写进 `file_dir` —— 顺序倒置，内置技能的 `scripts/render_docx.py` 等在 E2B 沙箱里根本不存在。同一 context 里还自相矛盾：`agent_factory.py:334-341` / `:365-372` 只按 `has_code_interpreter` 门控，硬性要求模型执行技能脚本、告诉它 `open("skills/<name>/assets/…")` 可用，而 E2B 的工具描述用 `include_skills=False`、注释已承认 skills 不在那里。Local executor 用实时 cwd（`local_sync_path`）不受影响。**与多节点无关。**

**P1-5**：`SkillService` 全是 `async def`，但 store 调用全部阻塞同步（`skill_service.py:148/159/166/226/228/242/258/361`）。对照 worker 侧同一批调用被明确包了 `asyncio.to_thread` 并写明理由（`skill_provisioning.py:113-116`）。单机看不见是因为写入方顺手种了本地缓存、读永远命中本地盘；**多副本下**上传落在 A1，A2/A3 是冷缓存，每次详情页/文件预览都变成完整网络往返 + 解压 + 落盘，**阻塞整个 uvicorn 进程**（entrypoint `--workers 2`，即一半容量）。

**P2（真实但影响可控）**：删除/创建非事务，留孤儿对象且全系统无 GC（`skill_service.py:255-258` / `:361-374`）；缓存只在执行删除的那个节点清理，worker 上旧 hash 目录永久残留（`skill_store.py:380-383`）；每个 API 副本每次启动全表扫一遍技能行（`skill_bundle_backfill.py:59-60`，`page_size=100000` + `bypass_tenant_filter`），迁移完成后是纯浪费。

### 8.4 真正该补的是测试，不是架构

现有 `TestEnumerationLoop`（`test/linsight/test_skill_provisioning.py:257`）用的是 `_CacheBackend` 假货 + 真 `FilesystemBackend`，**绕开了真 `WorkspaceBackend`** —— 所以"A 机上传 → B 机冷盘执行"这条链路在测试里从未被真正走过，本方案 §4 验收标准 1 的场景至今无人锁定。而设施全是现成的：

- `test/linsight/fixtures/fake_minio.py` 已具备 `put` / `get` / `exists` / `list_objects`；
- `test/linsight/test_skill_store.py:172-176` 已经有 `SkillStore(root=tmp_path / "other-node", minio=store.minio)` 的 A/B 节点写法（`test_materializes_from_storage_when_cache_is_cold`）—— 正是方案 §4 建议的手法，存储层已经这么做了。

建议补一条端到端用例：A 节点 `write_bundle` 发布 → B 节点用**独立 `root` + 独立空 `file_dir`** 的**真** `WorkspaceBackend`（共享同一 `FakeMinioStorage`）跑 `materialize_session_skills` → 断言 ① `copied` 非空、② B 机 `file_dir` 下 `/skills/<name>/SKILL.md` 落盘、③ 真 `SkillsMiddleware.abefore_agent({}, ...)` 枚举到该技能。**这条用例应当在未改架构的当前代码上直接通过** —— 它把"发现层依赖本机目录"这个隐式契约变成一条会失败的断言，比改架构划算得多。

顺带补 `test/linsight/test_workspace_backend.py` 一条 `is_dir` 正面断言：当前"`WorkspaceBackend.ls` 从不返回 `is_dir=True`"这个关键事实只被几个 stub 的默认值固化，没有任何断言锁定它。
