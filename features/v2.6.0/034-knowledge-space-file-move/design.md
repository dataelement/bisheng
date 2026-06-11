# Design: 知识空间文件 / 文件夹移动（同空间 + 跨空间）+ 文件夹上传

> 现状快照（Why this How）。spec=做什么，本文=为什么这么实现 + 今天代码长什么样，tasks=流水账。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-06-10（v2：纳入跨空间移动；产品已确认三点——迁移期显示「处理中」、文件夹可跨空间移、解析中文件移后在目标空间继续解析）

---

## 1. 目标与非目标

- **目标**：给文件 / 文件夹提供「移动到」弹窗和多选拖拽两种移动方式。
  - **同空间**：纯元数据 + 权限 tuple 操作（改 `file_level_path` / `level` + 换 OpenFGA `parent` tuple），秒级、可撤回，不触碰向量 / 解析 / minio。
  - **跨空间**：元数据即时迁移（含版本链整链）+ 检索数据（Milvus/ES chunk）异步迁移；二次确认、无撤回，迁移期文件显示「处理中」。
- **非目标**：
  - 跨空间不查重名、不迁移空间标签（PRD 拍板）。
  - 不重新解析文档（跨空间迁移以 ES 已有文本块为源，不重跑 ETL）。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7（分层 / 多租户 / 权限 / 错误码）。本功能特别注意两条：
  - **C2 双 DB**：子树批量前缀重写若用原生 SQL 的 `REPLACE()/CONCAT()` 属 MySQL-only 风险写法——用 Python 侧批量 update 或 dialect 兼容写法（DM8 由中央回归验证）。
  - **C3 租户边界**：移动仅限**同租户**空间之间——弹窗空间列表本身按当前租户过滤，服务端对 `target_space_id` 复用现有 `SpaceTenantMismatchError`(18041) 拒绝跨租户目标。
- **权限走 ReBAC/OpenFGA**（C4）：移动权限必须落到 OpenFGA relation 上，不能在业务层硬编码角色判断。
- **层级 ≤ 10**：复用现有 `SpaceFolderDepthError`(18011) 口径；移动后**子树最深层**不得超 10。
- **列表走 cursor 分页**（INV-6 / F027）：移动后列表刷新沿用现有 `list_space_children` cursor 协议。
- **版本链同空间不变式**（F039）：`knowledge_version_service` 强制同一版本链所有文件 `knowledge_id` 一致——跨空间移动必须**整链原子迁移**（document 锚点 + 全部版本文件），否则破坏该不变式。
- **每空间独立检索库**：`knowledge.collection_name`（Milvus）/ `index_name`（ES）/ `model`（embedding 模型）都是空间级，跨空间移动必须迁移 chunk 且按目标模型重算向量。
- **错误码段 180**（knowledge_space）：新增 `SpaceMoveInvalidTargetError`(18033)，其余复用 18011/18021/18040。**需在 release-contract 登记本 feature（F034）对 KnowledgeFile / KnowledgeDocument 新增的「移动」写行为。**

---

## 3. 方案对比与选定

### 决策 1：同空间与跨空间走同一入口、两条执行路径

- **备选**：A. 两个独立接口（同空间 move / 跨空间 transfer）；B. 一个 move 接口，后端按 `target_space_id == 当前空间` 分流。
- **选定**：B。
- **原因**：前端「移动到」弹窗是同一交互（左侧空间列表第一项即当前空间），用户不感知"两种移动"；校验逻辑（权限 / 循环 / 层级）也共用。后端在编排层分流：同空间走同步纯元数据路径，跨空间走「同步改元数据 + 异步迁移检索数据」。
- **何时重新考虑**：若跨空间迁移要加队列优先级 / 限流等独立运维属性，再拆接口。

### 决策 2：跨空间检索数据迁移 = 复用「知识库复制」的 copy_vector 管线，不重新解析

- **备选**：
  - A. 重跑 ETL（重新解析文档 → 切块 → embedding）——最彻底但极慢，且解析结果可能与原来不一致。
  - B. 复用 `file_worker.py` 复制功能的思路：从**源空间 ES** 按 file_id 读出全部文本块 → 改 metadata（knowledge_id）→ 写入**目标空间**（`add_texts` 写入时自动用**目标空间的 embedding 模型**算向量）→ 删源空间 Milvus/ES 数据。
- **选定**：B。
- **原因**：ES 里存着完整文本块，无需重新解析；`add_texts` 天然解决「源 / 目标 embedding 模型不同」（`knowledge.model` 每空间独立）；系统已有同构管线（复制功能）验证过这条路。成本 = 目标模型重算 embedding，按 chunk 数线性。
- **何时重新考虑**：未来若 Milvus 支持跨 collection 向量搬运且要求模型一致校验，可对「模型相同」的场景走纯向量拷贝加速。

### 决策 3：跨空间 = 元数据先行 + 异步迁移，迁移期复用 REBUILDING 状态

- **备选**：A. 全同步（确认后等迁移完成才返回）——大文件夹会让请求挂数分钟；B. 新增独立「迁移中」状态枚举——前后端都要适配新枚举；C. 元数据先行 + 复用 REBUILDING。
- **选定**：C。确认后**同步**完成：改 `KnowledgeFile.knowledge_id`（整版本链）+ `KnowledgeDocument.knowledge_id` + 重算 `file_level_path`/`level` + 换 FGA parent tuple + 文件状态置 `REBUILDING(4)`（仅原状态为 SUCCESS 的文件）→ 派发 celery 迁移任务。任务完成置回 SUCCESS；失败置 FAILED（可重试）。
- **原因**：用户视角「移完立刻在新位置看到」（AC-19）；REBUILDING 是现成状态、前端已有「处理中」样式,不引入新枚举。非 SUCCESS 状态文件（排队中/解析中/失败/违规/超时）**保持原状态**——它们在源空间本就没有(完整)向量：排队/解析中的任务执行时按当前 `knowledge_id` 取空间,自然落入目标空间(AC-21,产品已确认该语义)；失败/违规/超时的没有可迁数据,改归属即可。
- **代价**：迁移窗口内列表可见但检索不到（产品已接受）；REBUILDING 语义轻度复用（原本指"重建 chunk"）。
- **何时重新考虑**：若 REBUILDING 复用引起状态机歧义（如重建与迁移并发），再引入独立枚举。

### 决策 4：版本链整链迁移，document 锚点一起改

- **备选**：A. 只移主版本、历史版本留在原空间——直接违反「链内同空间」不变式（version_service 写路径会炸），否决；B. 整链迁移。
- **选定**：B。跨空间移动以**逻辑文档**为单位：`knowledge_document.knowledge_id` + 链上**全部** `knowledgefile.knowledge_id`（主版本+历史版本）在一个事务里改；`knowledge_document_version` 关联表不动（无空间字段）。历史版本文件同样各自派发检索数据迁移（它们各有自己的 chunk）。
- **原因**：版本服务强制「链内同空间」不变式（`knowledge_version_service.py:212`）；漏掉历史版本会直接违反不变式且把历史版本"留"在旧空间。MinIO 对象按 file_id 组织（`original/{file_id}.ext`），**不需要搬对象**。
- **参照**：删除的级联处理 `_cascade_version_links_on_delete`（knowledge_space_service.py:3175）——移动是它的"非破坏版"：同样按 document 分组展开整链，但只改归属不删数据。
- **何时重新考虑**：若 F039 版本模型重构（如版本表带空间字段），整链迁移逻辑需同步重审。

### 决策 5：move_file / move_folder 复用 can_edit，不改 OpenFGA 模型

- **选定**：把 `move_file`/`move_folder` 作为细粒度权限 id 映射到已有计算关系 `can_edit`（= editor∪manager∪owner），只在 `knowledge_space_permission_template.py` 加两行。
- **原因**：spec AC-06 的「所有/管理/编辑默认有、查看没有」正好等于 can_edit 档（与 rename_file/upload_file 同档）；不 bump 模型版本、不迁移 tuple、重启即生效。
- **何时重新考虑**：若产品要求"能编辑但不能移动"的独立授权，才升级为独立 relation。

### 决策 6：批量「移动其余」两步确认，后端无状态

- **选定**：第一次请求校验全部项,有冲突且 `skip_invalid=false` → 只返回冲突清单不提交；前端弹窗 →【移动其余】带 `skip_invalid=true` 重发。跨空间二次确认是前端交互（确认后才发请求），后端不感知。
- **原因**：AC-14/15 要求先弹窗让用户选；两步式让后端保持无状态、幂等。（备选：后端存"待确认批次"状态——引入会话态与超时清理，复杂度不值，否决。）
- **何时重新考虑**：若批量规模大到两次全量校验成为性能瓶颈，再考虑校验结果缓存。

### 决策 7：撤回仅同空间，前端驱动反向移动

- **选定**：同空间移动成功后前端记住每项 `originalParentId`，toast「撤回」= 反向再调一次 move（复用全套校验）。跨空间无撤回（PRD 拍板），二次确认替代。后端不存撤回态。
- **原因**：同空间可逆且廉价；跨空间撤回 = 再做一次反向迁移，成本高且语义复杂，产品已砍。（备选：后端撤回记录 + 时间窗——为 3 秒 toast 引入持久化状态,不值,否决。）
- **何时重新考虑**：若产品要求「关闭页面后仍可撤回」或多步撤回栈，升级为后端事务（见 §8）。

### 决策 8（产品拍板 2026-06-10，spec 评审追加）：目标侧权限只做前端展示过滤、跨空间成功 toast、标签清空

- **选定**：
  - 服务端**不**校验用户对目标空间/文件夹的 `upload_file` 权限——目标过滤仅是「移动到」弹窗的展示行为（评审曾标记 medium 安全项，产品明确否决服务端重复校验）。
  - 跨空间移动确认后 toast 提示移动成功（无撤回入口）。
  - 跨空间移动完成后**清空**文件原有的知识空间标签（`move_items` 同步事务内做，不留给异步任务）。
- **何时重新考虑**：若出现绕过 UI 直调接口把内容移入无权限空间的实际滥用 / 安全要求升级，再补服务端目标校验（加一行 `_require_permission_id(target, 'upload_file')` 即可）。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**同空间移动（同步）**：
`前端选中项+目标 → POST /knowledge/space/{space_id}/files/move → 逐项校验(权限/循环/层级/重名) → 改 level_path+level、级联子树、换 parent tuple → 返回每项结果 → 列表刷新 + toast(撤回)`

**跨空间移动（同步改元数据 + 异步迁数据）**：
`二次确认 → 同一接口(target_space_id≠当前) → 校验(权限/层级;无重名校验) → 事务内: 版本链整链改 knowledge_id + 重算路径 + 换 parent tuple + SUCCESS 文件置 REBUILDING → 派发 migrate_file_vectors celery(逐文件) → 任务: 源ES读chunk → 改metadata → 目标空间 add_texts(目标模型重嵌入,双写Milvus+ES) → 删源空间数据 → 状态置回 SUCCESS / 失败置 FAILED`

**「移动到」弹窗**：
左侧空间列表 = 用户有 `upload_file` 权限的空间（ReBAC `list_accessible_ids` 过滤）；右侧 = 选中空间的 `list_space_children`（文件夹可选/无上传权限置灰，文件仅有查看权限时展示且置灰）。

### 4.2 关键数据结构 / 字段约定（对外契约）

**接口** `POST /api/v1/knowledge/space/{space_id}/files/move`

请求：
```
{
  "items": [{"id": 123, "type": "file"|"folder"}, ...],
  "target_space_id": 7,             // 必填;等于 {space_id} 即同空间移动
  "target_folder_id": 456 | null,   // null = 目标空间根
  "skip_invalid": false             // true = 跳过无效项只移其余
}
```
响应（HTTP 200）：
```
{
  "moved":   [{"id": 123, "type": "file", "old_parent_id": 9|null, "cross_space": false}],
  "invalid": [{"id": 124, "type": "folder", "name": "X", "reason": "no_permission"|"into_self"|"into_subtree"|"into_current_parent"|"depth_exceeded"|"name_conflict"}]
}
```
- `skip_invalid=false` 且 `invalid` 非空 → 不提交任何项（前端据此弹窗）。
- 同空间项返回 `old_parent_id` 供「撤回」；跨空间项 `cross_space=true`,前端不提供撤回。

**层级路径**：`file_level_path` = `/祖先id/祖先id`（不含自身），`level` = 深度 int。

**迁移任务**：`migrate_file_vectors(file_id)`（knowledge_celery 队列），按文件当前 `knowledge_id` 解析目标空间;幂等（重试安全：先写目标后删源,按 file_id 去重删除）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `knowledge_space.py`（endpoints）新增 move 路由 | 收参、调 service | 不写业务校验 |
| `knowledge_space_service.py` 新增 `move_items()` | 移动编排：逐项校验 + 同/跨空间分流 + 版本链展开 + 改路径/归属 + 换 tuple + 级联 + 派发迁移任务 | 不直接操作向量 |
| `worker/knowledge/` 新增 `migrate_file_vectors` | 跨空间检索数据迁移（ES读→目标写→删源→置状态） | 不改文件元数据归属（service 已改完） |
| `knowledge_space_permission_template.py` | 加 `move_file`/`move_folder` → `can_edit` 两行映射 | — |
| `common/errcode/knowledge_space.py` | 加 `SpaceMoveInvalidTargetError`(18033) | — |
| **前端（client）实现索引** ↓ | （以实际落地为准，覆盖 design 设想） | |
| `api/knowledge.ts` → `moveFilesApi` + 类型 `MoveResult/MovedEntry/InvalidEntry` | 封装 `POST /{space}/files/move`；业务错误带 `status_code` 供分支 | 不写交互 |
| `pages/knowledge/hooks/useKnowledgeMove.ts` | **移动编排大脑**：`executeMove`（跨空间二次确认 → 调接口 → 部分冲突两步 → 成功提示 → `onMoved` 刷新）；`handleMoveConfirm`（弹窗入口）；`dropMoveToFolder`（拖拽入口，同空间直接移动，吞掉取消/错误）；`undoMove`（同空间撤回：按 `old_parent_id` 分组反向移动） | 不持有拖拽状态 |
| `pages/knowledge/hooks/useKnowledgeMoveDrag.ts` | **拖拽状态机**（表格+卡片共用）：拖源 `handleDragStart`（拖选中集合或单项，写 `dataTransfer text/plain`）；文件夹 drop 目标 `handleFolderDragOver/Leave/Drop`；`dragOverFolderId` 高亮态 | 不调接口（drop 回调交给 `onMoveToFolder`） |
| `pages/knowledge/SpaceDetail/MoveToDialog.tsx` | 「移动到」弹窗：左=有上传权限的空间列表（`listUploadableSpacesApi`，当前空间置顶）/ 右=该空间文件夹导航（面包屑+进入）/「移动到此」=移到当前所在目录 | 不做移动本身（`onConfirm` 回调给 hook） |
| `SpaceDetail/index.tsx` | 装配：实例化两个 hook；批量「移动」按钮 handler；渲染 `MoveToDialog`；给 `FileTable`/`FileCard` 透传 `onMove`(单项→弹窗) / `onMoveToFolder`(拖拽) / 卡片拖拽 props；`onMoved` = `setSelectedFiles(new Set())` + 失效 `file-versions` + `onDeleteFile("")` 重载 | — |
| `SpaceDetail/{FileTable,FileCard}.tsx` | 行/卡片接拖源 + 文件夹接 drop 目标；行菜单加「移动」项。**列表行高亮=整行背景变色（`#bcd4ff`）；卡片高亮=`border-primary` 边框** | — |
| `SpaceDetail/KnowledgeSpaceHeader.tsx` | 批量操作下拉加「移动」项（`onBatchMove`/`canBatchMove`=有上传权限） | — |
| `pages/knowledge/hooks/useFileDragDrop.ts`（既有，本 feature 改） | **坑**：上传遮罩的四个 drag handler 加 `isExternalFileDrag` 守卫（仅 `dataTransfer.types` 含 `"Files"` 时触发），否则内部移动拖拽会误弹上传遮罩 | — |

**复用的现成零件**：
- 权限：`_require_permission_id(type, id, perm_id, space_id=)`；空间列表 ReBAC `list_accessible_ids`
- 父 tuple：`_replace_resource_parent_tuple` 思路（delete 旧 + write 新,`PermissionService.batch_write_tuples`）
- 重名（仅同空间）：`SpaceFileDao.count_folder_by_name / count_file_by_name`
- 子树：`SpaceFileDao.get_children_by_prefix(kid, prefix)`
- 版本链展开：参照 `_cascade_version_links_on_delete`（按 document 分组取整链）
- 向量迁移：参照 `worker/knowledge/file_worker.py` 复制管线（copy_normal/copy_vector）与 `rebuild_knowledge_worker.py` 的 ES 全量读 chunk 写法
- 文件状态：`KnowledgeFileStatus`（PROCESSING=1, SUCCESS=2, FAILED=3, REBUILDING=4, WAITING=5, TIMEOUT=6, VIOLATION=7）

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 移动文件夹必须**级联重写整棵子树**的 `file_level_path`（前缀替换）和 `level`（深度偏移）；跨空间时子树内每个文件还要改 `knowledge_id` 并逐个派发迁移 | 目录树断裂 / 子文件残留旧空间 | `move_items()` 子树批量 update |
| 2 | 「移动后子树最深 ≤ 10」按**子树最深**算：目标 level + 子树相对深度 > 10 即拒 | 建出 >10 层 | 校验阶段先查子树最深 |
| 3 | AC-09 继承权限重算**不用写代码**——OpenFGA parent tuple 一换,tupleToUserset 自动重算；直绑 tuple 不碰 | 手动重算继承,白做且易错 | parent tuple 双操作 |
| 4 | 「只校验被操作对象、不校验子项」（AC-08）：跨空间移动文件夹时**子文件即使无 move 权限也跟着走**——这是 PRD 明确语义,不是漏洞 | 误加递归权限校验,行为与 PRD 不符 | move_items 权限只查入参项 |
| 5 | **版本链整链迁移**：漏掉历史版本会违反「链内同空间」不变式（version_service 写路径会炸）;历史版本文件**各有自己的向量和 minio 对象**,迁移任务也要覆盖它们 | 历史版本残留旧空间,版本管理页报错 | move_items 按 document 展开整链 |
| 6 | **MinIO 不用搬**：对象路径按 file_id（`original/{id}.ext`）。文档图片目录 `knowledge/images/{knowledge_id}/{doc_id}` 的 chunk 引用指向旧空间路径,**但已核实（2026-06-11）删旧空间不会丢图**——空间删除的 MinIO 清理（`delete_knowledge_file_in_minio`）只按文件记录逐个删 4 个对象字段,全代码库无按 `knowledge/images/{kid}/` 前缀的删除逻辑,且该目录配匿名读策略,不依赖空间存在 | 误以为要赶在删空间前迁移图片,做多余的搬运工程 | 无需处理;真实债务是 images 目录**从来没人清理**(连本空间文件的图都留着)=存储泄漏,见 §8 |
| 7 | 跨空间迁移任务**执行中途**源/目标空间可能再变（连环移动）：任务按 file 当前 `knowledge_id` 解析目标,以「最后归属」为准;删源时按 file_id 删,幂等 | 重复迁移/删错空间 | migrate 任务读 DB 最新归属 + 幂等删 |
| 8 | 排队中/解析中文件跨空间移动：解析 celery 任务**执行时**才解析 knowledge_id → 自然写入新空间;但若任务已初始化旧空间客户端（极小窗口）,产物会落旧空间 | 偶发:移动后文件在新空间永远搜不到 | 迁移任务对此类文件不派发;解析完成后若发现归属已变,由解析任务终段按当前归属写入（实现时验证该窗口,必要时解析完成回查一次归属） |
| 9 | 同空间撤回是反向 move + 重新校验：原位置被占/原目录被删 → 撤回失败,保留当前态 | 不处理失败分支 | 撤回失败 toast |
| 10 | 拖拽目标限「当前可视范围」,拖拽中不展开文件夹/不进空间（AC-03）;**左侧空间列表项也是合法投放目标**（跨空间→根目录,松手后才弹二次确认,确认前不发请求） | 目标漂移、误投;或漏做跨空间拖拽 | DnD hook 禁用 hover 展开 + 侧栏空间项注册 drop target |

---

## 6. 对外契约与依赖

### 6.1 我提供（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `POST /api/v1/knowledge/space/{space_id}/files/move`（含跨空间） | HTTP API | client SpaceDetail 移动到 / 拖拽 / 撤回 |
| 权限 id `move_file` / `move_folder`（can_edit 档） | 细粒度权限 | 权限配置 UI 自动出现 |
| `SpaceMoveInvalidTargetError`(18033) | 错误码 | 前端循环/无效目标提示 |
| `migrate_file_vectors` celery 任务 | 内部任务 | 跨空间迁移;失败重试入口 |
| `POST .../space/{id}/folders/upload`（文件夹上传，§9） | HTTP API | client SpaceDetail 文件夹上传（picker + 拖拽） |
| `SpaceFolderUploadCountExceededError`(18025，§9，可选兜底) | 错误码 | 前端 1000 超限兜底提示 |

### 6.2 我依赖（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `file_level_path` / `level` 层级模型 | KnowledgeFile 隐式契约 | 路径格式变更破坏级联 |
| OpenFGA parent 继承（can_edit/can_read 计算关系） | 授权模型 | 档位语义变更影响 move 权限 |
| 版本链「同空间」不变式 + document/version 三层模型（F039） | 数据模型 | 版本模型重构需同步改整链迁移 |
| 每空间 `collection_name`/`index_name`/`model` | Knowledge 字段 | 检索库组织方式变更则迁移管线重写 |
| ES 内文本块完整性（迁移以 ES 为源） | 隐式数据契约 | 若未来 chunk 只存 Milvus 不存 ES,迁移源失效 |
| `list_space_children` cursor 协议（INV-6） | 列表接口 | 弹窗文件夹树懒加载依赖 |

---

## 7. 测试与可观测

- **后端单测**（`test/knowledge/`）：AC-10/11/12（循环/超层/同空间重名;跨空间不查重名）、AC-08（不校验子项）、AC-13（各状态可移）、AC-09（继承随新父、直绑不变）、级联路径重写、**版本链整链迁移**（主+历史 knowledge_id 一致）、批量两步（skip_invalid）、迁移任务幂等（重复执行不重复写/删错）。
- **集成**：跨空间移动后——目标空间检索能命中、源空间检索不再命中、版本管理页关系完整、迁移失败置 FAILED 可重试。
- **手动验证**：本地起后端（:7860,`config=config.yaml uv run uvicorn bisheng.main:app`）+ client（:4001,`npm run dev`）,或用 120 测试环境（`http://192.168.106.120:8901/workspace/`,admin 账号）;准备两个空间（可配不同 embedding 模型）,互移文件/文件夹/多版本文件,观察 REBUILDING→SUCCESS 流转与两侧检索结果。
- 关键日志：move_items 每项 reason;migrate 任务 file_id+源/目标空间+chunk 数;失败必须 raise 不可静默。

---

## 8. 后续改进 / 不打算做的事

- **模型相同时的纯向量拷贝加速**：当前统一走重嵌入,模型相同场景可省 embedding 算力,待量级需要时再做。
- **跨空间撤回**：PRD 砍掉;若将来要做 = 反向迁移 + 后端撤回记录,另立项。
- **图片目录迁移**（坑 6）：**不做,且已核实无需做**（2026-06-11）。移动后 chunk 内的图片引用仍指向**源空间路径**,图片照常解析;原先担心「删旧空间会丢图」经核实**不成立**——空间删除只按文件记录删对象,从不按 `knowledge/images/{kid}/` 前缀清理,图不会裂。真实遗留问题是反方向的:**images 目录从来没人清理**(空间删除后本空间文件的图片也全留在 MinIO),属存储泄漏,与移动无关,如需治理另立清理脚本项。move_worker.py 头注释中"objects only need migrating before the source space is deleted"的说法同样基于旧假设,下次动该文件时顺手修正。

---

## 9. 文件夹上传（§5.5）设计

> 与「移动」正交：移动 = 空间内内容换位置；上传 = 把本地文件夹整树搬进空间。本节自包含，AC-24~31。

### 9.1 现状（接手必读）：前端已有「文件夹上传」半成品，但只做一层平铺

- 前端早已具备：`webkitdirectory` 选择器（`client/.../SpaceDetail/index.tsx:961`）、拖拽目录读取（`useFileDragDrop.ts:41` `readTopLevelFolderFiles`）、文件夹上传编排（`useFileUpload.ts:288` `handleUploadFolder`）、过滤工具（`knowledgeUtils.ts:224` `filterFolderUploadFiles`）。
- **但现有行为 = 被作废的旧规则 3.2.4**：`filterFolderUploadFiles` 用 `rel.split("/").length !== 2` **只留文件夹根目录直属文件、过滤掉所有子文件夹文件**；拖拽 `readTopLevelFolderFiles` 也只读一层。即现有「上传文件夹」实际是「把根层文件平铺传上来，不重建子目录树」。
- 后端无「按相对路径重建目录树」能力：`add_folder`（单建一个文件夹，`knowledge_space_service.py:2772`，含深度 18011 / 同目录重名 18012 校验）与 `add_file`（往一个 `parent_id` 放平铺文件，`:2940`，含权限/容量/MinIO/celery 派发）各自独立。
- **结论**：§5.5 是把这套半成品从「一层平铺」升级为「全量嵌套 + 服务端重建目录树」——前端递归化 + 后端新增批量编排，不是从零起。

### 9.2 复用的现成零件（几乎全有）

| 能力 | 现成件 | 锚点 |
|---|---|---|
| 目录读取 | webkitdirectory 选择器 / `webkitGetAsEntry` 递归 | `index.tsx:961` / `useFileDragDrop.ts:174` |
| 相对路径 | `file.webkitRelativePath`（`getRootFolderName`） | `knowledgeUtils.ts:208` |
| 格式白名单 | `ALLOWED_EXTENSIONS` / `getAllowedExtensions(etl4lm)`（后端 `FileExtensionMap`，`base_file_pipeline.py:25`） | `knowledgeUtils.ts:56` |
| 单文件大小 | `DEFAULT_MAX_FILE_SIZE_MB=200` ← `bishengConfig.uploaded_files_maximum_size` | `knowledgeUtils.ts:111` / `index.tsx:540` |
| 文件本体上传 | `uploadFileToServerApi` → `file_path` | `api/knowledge.ts:1405` |
| 建文件夹 | `add_folder`（深度/重名已校验） | `service:2772` |
| 注册文件 + 派发解析 | `add_file`（权限/容量/MinIO/celery） | `service:2940` |
| 容量校验 | 用户档 `QuotaService.get_knowledge_space_upload_limit_bytes`(18024) / 租户 `get_tenant_storage_remaining_bytes`(19403) | `quota_service.py:514` / `:482` |
| 文件重名 | md5/name 冲突 → 临时对象 + FAILED + 前端覆盖（**不报错**） | `knowledge_service.py:1259` |

### 9.3 关键决策

#### 决策 U1：目录树重建放**后端新增批量接口**，不靠前端多次调现有接口编排

- **备选 A**（前端编排）：前端解析 `relativePath` → 需建文件夹集合，按层序逐个 `createFolderApi` 建树拿 id，再逐文件 `addFile` 到对应 parent。后端零改。
- **备选 B**（后端批量接口）：新增 `POST .../space/{id}/folders/upload`，收 `{parent_id, items:[{file_path, relative_path}]}`，服务端一次性：顶层文件夹重名校验 → 解析相对路径建目录树（事务）→ 层级校验 → **容量整批预校验** → 逐文件注册 + 派发解析 → 返回每文件结果（含重名 FAILED）。
- **选定 B**。
- **原因**：① spec 把「层级 / 文件夹重名 / 容量」定为**服务端为准 + 整批拒**，B 让这三项在一个事务里集中判、整批 reject 干净；A 的逐请求建树把校验摊到几十上百次往返，部分失败后半建的目录树难回滚。② 容量校验现有是 `add_file` 内「上传后查 `current_total > limit`」的逐文件式（`service:2974-2993`），逐文件编排会传一半才超限——违反 AC-30「上传后超出 → 拒整批」；B 可在建树前按「本批总大小 + 已用 vs 上限」预判。③ 目录父子顺序、`path→id` 映射在服务端一次算清，比前端管理更稳。
- **代价**：后端新写批量编排 service（约等于 `add_folder×N + add_file×N` 的合并体）。
- **何时重新考虑**：若产品要求边传边显示每个子文件夹的创建进度（强前端编排感），再回到 A。

> 注：文件**本体**仍走现有 `uploadFileToServerApi` 逐个传 MinIO 拿 `file_path`——本设计不改这条；1000 文件即 1000 次本体上传 + 1000 个解析任务入队，属现有上传模式（坑 U6）。批量接口只做「注册 + 建树 + 集中校验」。

#### 决策 U2：全量嵌套——前端递归读取 + 废弃「只留根层」过滤

- 去掉 `filterFolderUploadFiles` 的 `split("/").length !== 2` 单层过滤，改为保留所有层级文件、只按「格式 / 隐藏 / 超大」过滤；拖拽侧 `readTopLevelFolderFiles` 改为递归读全部子目录（`FileSystemDirectoryEntry` 递归）。
- **原因**：对齐产品拍板「3.2.4 作废、全量嵌套」。

#### 决策 U3：1000 上限按「过滤前原始总数」前端主挡、后端兜底

- 前端读到的原始文件总数（含所有嵌套层、**过滤之前**）> 1000 → 直接报错整批不传（产品拍板计数口径）。后端批量接口对收到的文件数兜底校验（防绕 UI 直调）。

#### 决策 U4：静默过滤（格式 / 隐藏 / 超大）在前端，后端格式兜底

- 前端按 `ALLOWED_EXTENSIONS` + 200MB + 隐藏文件静默剔除，不报错、不占名额，合规文件才进上传；后端 `add_file` 链路本就有格式校验（`base_file_pipeline` → `KnowledgeFileNotSupportedError`/18022）兜底。

> **AC-32（产品 2026-06-11 补充）**：所有拒批场景（数量 / 层级 / 顶层夹重名 / 容量）前端一律以 **toast** 提示具体原因——前端挡下的直接 toast；服务端拒的按错误码映射 toast 文案。

### 9.4 数据流 + 接口契约

数据流：
`选文件夹(picker/拖拽) → 前端递归取全部文件+relativePath → 校验：总数>1000 整批拒 / 静默过滤格式·隐藏·超大 → 逐个 uploadFileToServerApi 传本体拿 file_path → POST .../folders/upload(parent_id + [{file_path, relative_path}]) → 服务端：顶层夹重名 → 建目录树 → 层级≤10 → 容量整批预校验 → 逐文件注册+派发解析 → 返回每文件结果 → 列表刷新`

**接口** `POST /api/v1/knowledge/space/{space_id}/folders/upload`

请求：
```
{
  "parent_id": 456 | null,          // 上传落点(当前目录)，null=空间根
  "items": [
    {"file_path": "tmp/uuid.pdf", "relative_path": "我的资料/子目录/a.pdf", "size": 1048576}
  ]
}
```
- `relative_path` 第一段 = 待建顶层文件夹名；中间段 = 子目录树；末段 = 文件名。
- 同一顶层文件夹名只校验一次重名（U3 坑）。
- `size`（实现时新增）= 前端报告的文件字节数，仅用于**容量整批预校验**（整批拒的 UX）；权威配额校验仍由注册环节（add_file 复用）逐文件执行,客户端谎报 size 只会让预校验放行、随后被逐文件校验挡住。

响应：复用 `add_file` 的每文件结果结构（成功项 + 重名 FAILED 项，前端走现有覆盖弹窗）。整批校验失败（数量 / 层级 / 顶层夹重名 / 容量）→ 4xx + 错误码，**整批不落库**。

**权限口径（C4）**：
- 入口权限与现有单文件上传同口径——对落点（`parent_id` 文件夹，或空间根）`_require_permission_id('upload_file')`，复用 `add_file` 开头的写法（`service:2952`）。不引入新权限 id。
- 批量新建的**每个文件夹节点**必须初始化权限 tuple（FGA parent 继承），复用 `add_folder` 内的 `_initialize_child_resource_permissions`（`service:2814`）——constitution C4「资源创建必须 authorize」硬规定，批量编排合并时**最容易漏的就是这步**，漏掉会建出无主文件夹（继承链断裂，后续移动/授权都异常）。

校验落点：

| 校验 | 落点 | 错误码 |
|---|---|---|
| 入口权限 `upload_file`（落点文件夹/空间） | 服务端（C4 统一入口） | 18040 已有 |
| 总数 ≤ 1000 | 前端主挡 + 后端兜底 | 新增 18025（或复用参数错误） |
| 格式 / 隐藏 / 超大 | 前端静默过滤 + 后端格式兜底 | 18022（格式）已有 |
| 层级 ≤ 10 | 服务端（建树后最深层） | 18011 已有 |
| 顶层文件夹重名 | 服务端（parent 下 `count_folder_by_name`） | 18012 已有 |
| 容量（用户档 / 租户） | 服务端**整批预校验** | 18024 / 19403 已有 |
| 文件重名 | 服务端复用现有 md5/name → FAILED | 无（走覆盖流程） |

### 9.5 已知坑

| # | 反直觉事实 | 不知道会怎样 | 处理 |
|---|---|---|---|
| U1 | 现有「文件夹上传」= 旧 3.2.4（只传根层、过滤子文件夹），不是没做——是做了旧规则 | 以为从零做，漏改 `filterFolderUploadFiles`/`readTopLevelFolderFiles` | 决策 U2 改造点 |
| U2 | 容量校验现有是 `add_file` 内「逐文件上传后查超限」，批量逐文件会传一半才超 | 部分文件已落库才报容量错，违反「整批拒」 | 批量接口建树前按本批总大小预校验 |
| U3 | 文件夹重名只校验**顶层**那个文件夹（parent 下）；子目录树是新建的不会撞 | 误对每层子目录做重名校验 | 仅顶层 `count_folder_by_name` |
| U4 | 文件重名**不报错**（现有 = 临时对象 + FAILED + 前端覆盖），与「文件夹重名报错拒」是两套语义 | 误把文件重名也做成整批拒 | AC-31 复用现有，前端覆盖弹窗 |
| U5 | 隐藏判定要看 `relativePath` **每一段**（子目录可能是隐藏夹如 `.git/`） | 只判文件名，漏掉隐藏目录下文件 | 前端过滤按 path 段 |
| U6 | 解析与单文件上传同管线，1000 文件 = 1000 次 MinIO 本体上传 + 1000 个解析任务入队 | 误以为批量接口「一次传完」 | 本体仍逐个传，批量接口只做注册 + 建树 |
| U7 | 批量建树的每个文件夹节点都要走权限 tuple 初始化（C4 authorize），不是只插 DB 行 | 建出"无主"文件夹：继承链断裂，后续授权/移动异常 | 复用 `_initialize_child_resource_permissions`（`service:2814`），逐节点 |

### 9.6 对外契约（增量）

- **新增**：`POST .../space/{id}/folders/upload`（client SpaceDetail 用）；可能新增错误码 `SpaceFolderUploadCountExceededError`(18025) 作后端兜底。
- **复用**：18011 / 18012 / 18022 / 18024 / 19403；`uploadFileToServerApi` / `add_folder` / `add_file` / `QuotaService` / 解析管线。
- **依赖**：`webkitRelativePath`（浏览器能力）、`file_level_path`/`level` 层级模型、QuotaService 配额口径。
- **release-contract 待登记**：F034 行追加「§5.5 文件夹上传：新增 `folders/upload` 批量接口 + 18025；无新增领域对象（复用 SpaceFile/解析/配额）」。

### 9.7 测试

- **后端**：目录树重建（多层嵌套 path → 正确父子）、层级 > 10 整批拒、顶层夹重名拒、容量整批预校验（本批总和触顶 → 整批拒、不留半成品）、文件重名走 FAILED 不拒批、数量兜底。
- **前端**：递归取全部嵌套文件、1000（过滤前）挡、静默过滤格式/隐藏/超大、两入口（picker + 拖拽）、覆盖弹窗复用。
- **手动**：传一个 3 层嵌套文件夹（混入不支持格式 + 隐藏文件 + 超大文件）→ 只合规文件按树重建；传顶层重名文件夹 → 拒；构造超容量 → 整批拒。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-09 | 初版（仅同空间） | feature 设计 |
| 2026-06-10 | v2：纳入跨空间（复用复制管线/版本链整链/REBUILDING 状态/二次确认无撤回）;编号 032→034（032=OFD、033=linsight 已占用） | PRD 范围升级,产品确认三决策 |
| 2026-06-10 | 实现完成（Wave 1-4 全通,21 后端测试绿,本地验证移动+toast）。3 项降级：①跨空间拖到左侧空间列表未做（跨组件树成本高,弹窗已覆盖）②同空间撤回未做（toast 无动作按钮,后端已留 old_parent_id）③图片目录物理迁移记债（坑 6）。i18n 占位符须用 `{{0}}` 双花括号 | 实现落地 + 务实降级 |
| 2026-06-10 | 本地测试后修订：①同空间撤回**改用 confirm 弹窗实现**（不再降级）②修复内部拖拽误触发上传遮罩（`useFileDragDrop` 加 `isExternalFileDrag` 守卫）③卡片视图补拖拽（抽 `useKnowledgeMoveDrag` 共用）④拖拽高亮：列表=整行背景变色、卡片=边框变色。§4.3 前端实现索引按实际重写 | 联调修 bug + UX 调整 |
| 2026-06-10 | 纳入 §5.5 文件夹上传设计（§9，AC-24~31）：后端新增 `folders/upload` 批量接口重建目录树 + 容量整批预校验，复用配额/解析/重名/层级管线；前端从「一层平铺」升级全量嵌套（废 `filterFolderUploadFiles` 单层过滤、拖拽递归读全树）；关键现状=前端已有半成品但行为=旧 3.2.4。可选新增错误码 18025 | spec 扩 §5.5，探明前端已有半成品 |
| 2026-06-11 | 修正坑 6 / §8：核实「删旧空间丢图」不成立——空间删除（`delete_knowledge_file_in_minio`）只按文件记录删对象，从不按 `knowledge/images/` 前缀清理，移走文件的图不会裂；真实问题是 images 目录无人清理（存储泄漏，另立项） | 用户要求核实删除链路 |
| 2026-06-11 | Wave 5 文件夹上传实现完成（T013~T016）：后端 `upload_folder_items` + `POST /{space_id}/folders/upload` + 18025（13 个新测试绿，知识模块零回归）；前端递归读全树、全层级静默过滤（隐藏按 path 段）、`uploadFolderApi` 走 `skip403Redirect` 统一 toast（AC-32）。契约偏差：items 增加 `size` 字段（§9.4 已更新）。AC-32 产品补充已落 spec | Wave 5 实现落地 |
