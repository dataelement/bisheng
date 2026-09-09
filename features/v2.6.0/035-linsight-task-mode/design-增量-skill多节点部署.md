# Design 增量 · 任务模式 Skill 多节点收口（F035 follow-up）

> 版本：v3.0.0 · 状态：**核实后收缩：步骤 1/2 不做** · 关联：[design.md](./design.md) §7 / §9 · [constitution C8](../../../docs/constitution.md#c8-no-shared-state-on-the-local-filesystem) · [08-deployment.md](../../../docs/architecture/08-deployment.md)
>
> **以本文 §2 / §3 为准。** 初稿曾主张改 `WorkspaceBackend.ls` 并让 `SkillsMiddleware` 改挂工作区 backend；2026-09-08 核实后确认发现层主路径已经跨节点可用，该架构改造废弃。正文方案是核实中扫出的 P0/P1 缺口 + 冷节点测试。

**一句话**：存储层已跨节点；发现层当前不会因多节点失效。不要改 `ls` / 中间件挂载。要修的是对象缺失报错、入队后技能被停用静默丢失、`exists()` 信本地 cache，以及把「A 上传 → B 冷盘执行」写成会失败的测试。

---

## 1. 背景

### 1.1 已经做完的：存储层（不要重做）

commit `2d0c645ba` 把 Skill **正文**从节点本地 `SKILLS_ROOT` 迁到 MinIO 内容寻址：

```
linsight/skills/{tenant_id}/{name}/{content_hash}.zip
```

DB 行（`linsight_skill`）只持指针（`object_path` + `content_hash`）。节点按 hash 本地物化，cache 可丢。内置技能由 API 进程 seeder 写入同一对象前缀；Worker 不再需要本地 `built-in/` 目录。这条已写入宪法 C8 与 `docs/architecture/08-deployment.md`。

`design.md` §7.1 里「多机须挂 `SKILLS_ROOT` 共享卷」的约束已划掉。**不要再走 NFS 共享卷。**

主路径已经通：API 节点 A 上传 → Worker 节点 B（空 `skills_cache_dir`、空 `file_dir`）执行；HITL 换节点 resume 同样再走 `_create_agent` → `materialize_session_skills`（当次 copy 进本机 cache）→ 再枚举。模型读 `SKILL.md` 走 `WorkspaceBackend`（MinIO 权威）。

### 1.2 原诊断「运行时发现层没做完」——已核实不成立

初稿认为：`SkillsMiddleware` 用 `FilesystemBackend(file_dir)` 枚举，发现绑死本机目录；HITL 换节点 / `file_dir` 未就绪会枚举到 0 个技能并静默降级。

三条 agent 路径（`task_exec.py` resume / continue / execute）**全部**走 `_create_agent`，而 `materialize_session_skills` 在 `create_linsight_agent` **之前**。`file_dir` 在 `_managed_execution` / `_managed_resume` 的 `yield` 之前赋值，`_init_file_directory` 首行就是 `os.makedirs`。`upload_files` 先 `_cache_write`（含 `mkdir`）再 PUT MinIO，所以枚举发生时本机目录必然已被**当次运行**填好。copy 失败时 `skills_present=False`，中间件不挂，且 `_push_skill_load_failure` 会推时间线——不是静默。

下列初稿场景也不构成「发现层漏做」：

| 初稿称 | 核实 |
|--------|------|
| HITL 换节点 resume，copy 失败或 `file_dir` 未就绪 → 枚举 0（静默降级） | **不成立**，见上 |
| 存量行 `content_hash=''` → 空 bundle | 现象在，但已经是显式失败（进 `failed` 并推用户） |
| 把 `skills_cache_dir` / `file_dir` 指到共享盘 | 配置误用；配置项已写 *"Do NOT point this at a shared volume"* |

实现细节仍成立（不要连带推翻）：`SkillsMiddleware` 不注册文件工具；`WorkspaceBackend.ls` 只出文件条目（`is_dir` 恒 `False`），原生 `skills=` 复用工作区 backend 会枚举到 0。这解释的是「为什么今天用本地 `FilesystemBackend`」，推不出「所以多节点发现会坏」。

### 1.3 收缩后的目标

不改发现层挂载，不改 `ls` 语义。把主路径的隐式契约用测试锁住，并修核实扫出的、多节点会放大或表现为节点不一致的缺口。

---

## 2. 原方案步骤：采纳 / 废弃

| 原步骤 | 结论 | 理由 |
|--------|------|------|
| 1. `WorkspaceBackend.ls` 合成一级虚拟目录项 | **废弃** | 发现层主路径不依赖这条。`glob` / `grep` 直接消费 `ls` 的 entries；deepagents `ls` 工具丢掉 `is_dir`，模型会看到无扩展名的 `/skills/foo` 并可能去 `read`。若将来做「目录语义对齐」，须另开、带 glob/grep 过滤与回归，不是本方案。 |
| 2. `SkillsMiddleware` 改挂 `WorkspaceBackend` | **废弃** | 依赖步骤 1；`WorkspaceBackend.__init__` 未调 `super()`，`cwd` / `virtual_mode` 未设，未验证调用链。门控从 `skills_present and file_dir` 改成 `and backend` 两边都恒真，是 no-op。 |
| 3.1 空 `content_hash` 显式失败 | **不单独做** | 现已进 `failed` 并推时间线；收益只是日志分类。 |
| 3.2 `SkillStore.exists()` 只信 MinIO | **采纳** → §3 P1-3 | seeder 自愈被本地 cache 短路，对象被带外删除后重启修不好。 |

枚举结果进 checkpoint（`skills_metadata` 键存在则 `before_agent` 短路）是既有机制：resume 不重放 entry node，continue 会短路。对多节点无害（正文读 MinIO；`/workbench/continue` 无 skills 入参）。换 backend 修不掉它，也不需要为多节点去修它。

---

## 3. 正文方案

主链路多节点已通。以下缺口没有一条能靠原步骤 1/2 修好。

### P0-1 · 对象缺失打成 500

`SkillStore.materialize` 只处理 `get_object_sync` 返回 `None`（`skill_store.py`）。生产 MinIO 在 NoSuchKey 时 `raise _thaw_s3_error(e)`（`core/storage/minio/minio_storage.py`），从不返回 `None`。skill 的 object key 刻意不带 `tenant_{code}/` 前缀，`_translate_to_root_prefix` 返回 `None`，F017 回退不会吞掉它。

于是三处降级全部失效：

- `list_files` 的 `except FileNotFoundError`
- `get_detail` 的空预览降级（只 catch `FileNotFoundError` / `ValueError`）
- `read_bundle_file` 的 11053 业务码

额外：`get_detail` 里 `list_files(...)` 写在 `SkillDetail(...)` 构造参数中，**不在 try 内**。用户看到裸 `S3Error` + 500，运维容易误判 MinIO 挂了。

**测试是假绿**：`FakeMinioStorage.get_object_sync` 缺失时返回 `None`，`test_missing_object_raises_not_found` 只在假 MinIO 下成立。修这条必须把 fake 改成抛 `S3Error`。

改动：

- `materialize` / `_minio_get` 把 NoSuchKey 收成 `FileNotFoundError`（工作区 `_minio_get_sync` 已有同样模式）
- `list_files` / `get_detail` / `read_bundle_file` 继续只对 `FileNotFoundError` 降级；`get_detail` 把 `list_files` 挪进 try
- `fake_minio.get_object_sync` 缺失时抛与生产同形的 `S3Error`

### P0-2 · 入队后技能被停用/删除则静默丢失

`wanted = selected ∩ enabled`（`skill_provisioning.py`）。被治理剔除的名字既不进 `copied` 也不进 `failed`；`task_exec` 只在 `failed` 非空时推时间线。

用户勾选提交 → 队列积压或 `ask_user` park → 期间管理员停用/删除 → worker 取到任务时直接跳过，`skills_present=False`，「技能优先」提示消失。前端问题卡片上的 chip 还在，模型行为像没选过。多节点把窗口从同进程毫秒级放大到跨 Redis 队列 + park-and-release 的分钟至小时级——这是初稿「多节点让 skill 出问题」里唯一站得住的部分。

改动：`selected - enabled`（以及 selected 里 DB 已无行的名字）进入 `failed`，走现有 `_push_skill_load_failure`。复制闸门语义不变：未启用的仍不 copy。

### P1-3 · `exists()` 只信 MinIO（原步骤 3.2）

`exists()` 一旦本地 cache 有 `SKILL.md` 就返回 `True`，不探对象。唯一调用方是 seeder 的 `_already_published`，docstring 写明探测意义是「对象被带外删除/损坏时下次启动自愈」。`write_bundle` 上传后种本地 cache 且无 GC，跑过一次 seeder 的节点 cache 永久是热的。

后果：MinIO 上 `linsight/skills/` 被误删后，该节点重启永远判 `unchanged`、永不重新发布；其它节点 500 / 加载失败。表现不一致，且「重启就能修」是错的。

改动：`exists()` 只信 `object_exists`。`materialize()` 的 cache hit（目录名即 hash）保留，那是读路径加速。单测：cache 有、MinIO 无时 `exists()` 为 False。

### P1-4 · E2B 拿不到技能脚本（与多节点无关，有 E2B 再做）

`_generate_tools` 用 `os.walk(file_dir)` 做 E2B copy-in **构建时快照**，而 materialize 在之后的 `_create_agent` 才写入 `/skills/`。内置技能的 `scripts/render_docx.py` 等在沙箱里不存在。prompt 按 `has_code_interpreter` 要求模型执行技能脚本，E2B 工具描述却是 `include_skills=False`。Local executor 用实时 cwd，不受影响。

改动（排期）：先 `materialize_session_skills` 再 `_generate_tools`，或在 tool 构建后把 `/skills/` 补进 copy-in。不要为这条改发现层。

### P1-5 · `SkillService` 同步打 MinIO（多 API 副本才明显）

`SkillService` 全是 `async def`，store 调用全部阻塞同步。worker 侧同类调用已 `asyncio.to_thread`。单机 compose 因写入方种了 cache、读命中本地而看不出来；多副本下上传落在 A1，A2/A3 冷 cache，详情页变成完整网络往返 + 解压 + 落盘，堵住该 uvicorn worker。

改动（排期）：读路径（`get_detail` / `read_bundle_file` / `_load_existing_bundle`）包 `asyncio.to_thread`，与 worker 对齐。

### P2 · 可排期

删除/创建非事务，留孤儿对象且无 GC；cache 只在执行删除的节点清理，worker 上旧 hash 目录残留；每个 API 副本启动全表扫技能行（`page_size=100000` + `bypass_tenant_filter`），迁移完成后是纯浪费。不进本轮。

### 测试（本轮要做，比改架构划算）

现有 `TestEnumerationLoop` 用 `_CacheBackend` + 真 `FilesystemBackend`，绕开了真 `WorkspaceBackend`，「A 上传 → B 冷盘执行」从未锁定。

补一条（**未改架构的当前代码上应直接绿**）：

1. A 节点 `write_bundle` 发布
2. B 节点用独立 `root` + 独立空 `file_dir` 的**真** `WorkspaceBackend`（同一 `FakeMinioStorage`）跑 `materialize_session_skills`
3. 断言 `copied` 非空、B 机 `file_dir` 下 `/skills/<name>/SKILL.md` 落盘、真 `SkillsMiddleware` 枚举到该技能

设施已有：`fake_minio.py` 的 put/get/exists/list；`test_skill_store.py` 的 `SkillStore(root=.../other-node, minio=store.minio)`。

另补：`test_workspace_backend.py` 一条 `ls` 结果均 `is_dir=False` 的正面断言（锁定现状，防止有人按废弃的步骤 1 改进去却无测试挡）。P0-1 的 fake 改抛 `S3Error` 后，重写 `test_missing_object_raises_not_found`。

---

## 4. 验收标准

1. **跨节点 CRUD + 执行（锁现状）**：A 上传 → B 空 cache / 空 `file_dir` 执行 → 枚举到技能、能 `read_file` 正文与附属文件。由 §3 冷节点测试锁定，不靠改 `ls`。
2. **HITL 换节点**：A park → B resume → 技能仍在；copy 失败走时间线，不静默。
3. **白名单**：未勾选 / 提交时即 `enabled=0` 的技能不 copy。入队后被停用/删除的名字进 `failed` 并上时间线（P0-2）。
4. **交付物**：`output/` 仍落工作区（不改中间件挂载，shadow 无新风险）。
5. **对象缺失**：详情页 / 预览走业务降级或 11053，不 500；fake 与生产同形（P0-1）。
6. **seeder 自愈**：cache 热、对象没了时 `exists()` 为 False，下次启动会重新发布（P1-3）。
7. **回归**：`test_ls_authoritative_from_minio`、`test_skill_provisioning` 现有用例、代码解释器 `os.walk(file_dir)` 不动。

---

## 5. 明确不要做的事

- 不要做原步骤 1/2（合成 `ls` 目录项、中间件改挂 `WorkspaceBackend`）。
- 不要把 `SKILLS_ROOT` / `file_dir` / `skills_cache_dir` 做成 NFS 共享卷。
- 不要让 Worker 再从镜像 `builtin_skills/` 直接加载。
- 不要把 `WorkspaceBackend.ls` 改成完全非递归。
- 不要在 Alembic 里做 bundle 数据迁移；空 hash 继续靠 `scripts/migrate_skills_to_object_storage.py`。
- 不要重做存储层（内容寻址、`content_hash` 列、seeder）。

---

## 6. 落地顺序

| 顺序 | 内容 | 规模 |
|------|------|------|
| 1 | 冷节点测试 + `ls` 的 `is_dir=False` 断言（应在当前代码上绿） | 小 |
| 2 | P0-1：`S3Error` → `FileNotFoundError`；fake 对齐；`get_detail` 包住 `list_files` | 小 |
| 3 | P0-2：`selected - enabled` 进 `failed` | 小 |
| 4 | P1-3：`exists()` 只信 MinIO + 单测 | 小 |
| 5 | P1-4 / P1-5 / P2 | 排期；有 E2B 或多 API 副本再做 |

若环境里 B 机技能仍不生效，先查 `content_hash` 是否为空、以及迁移脚本是否在**持有本地残留 bundle 的那台 API 机**跑过——那是升级残留，不是发现层。

---

## 7. 现状锚点

| 职责 | 位置 |
|------|------|
| Skill 对象存储 + 本地 hash cache | `linsight/domain/services/skill_store.py` |
| 本轮复制闸门 | `linsight/domain/services/skill_provisioning.py` · `materialize_session_skills` |
| 装配 SkillsMiddleware | `linsight/domain/services/agent_factory.py`（`skills_advertised`） |
| 工作区 `ls`（只返回文件） | `linsight/domain/services/workspace_backend.py` · `ls()` |
| 任务启动触发复制 | `linsight/domain/task_exec.py` · `_create_agent` |
| 存量空 hash 窄回填 | `linsight/domain/services/skill_bundle_backfill.py`；`scripts/migrate_skills_to_object_storage.py` |
| 技能详情 / 预览 | `linsight/domain/services/skill_service.py` · `get_detail` / `read_bundle_file` |
| 内置技能 seeder | `linsight/domain/services/builtin_skill_seeder.py` · `_already_published` |
