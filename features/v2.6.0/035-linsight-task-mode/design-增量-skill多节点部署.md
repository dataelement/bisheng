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
