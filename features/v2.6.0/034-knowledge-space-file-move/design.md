# Design: 知识空间文件 / 文件夹移动（同空间 + 跨空间）

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
| client `SpaceDetail/` 新增 `MoveToDialog` + 行级 DnD hook | 左空间右文件夹弹窗 / 多选拖拽（投放目标=可视文件夹行 **+ 左侧空间列表的空间项**，后者=跨空间移到根、松手后二次确认）/ 同空间撤回 toast / 批量异常弹窗 | 不直接调 axios |

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
| 6 | **MinIO 不用搬**：对象路径按 file_id（`original/{id}.ext`）。**例外是文档图片目录** `knowledge/images/{knowledge_id}/{doc_id}`——chunk 里的图片引用指向旧空间目录;不搬也能用,但**旧空间被删除时图会丢** | 删旧空间后,已移走文件的图片裂开 | 迁移任务顺带把 images 目录拷到新空间路径并更新 chunk 引用;或至少在 tasks 里列为已知债 |
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
- **图片目录迁移**（坑 6）：**实现阶段定为记债,不在 T007 做物理拷贝**。原因——文档图片目录键为 `knowledge/images/{kid}/{doc_id}`,而 `doc_id` 与 file_id 的对应在解析侧不确定;按错误的键拷贝反而会弄坏图片引用。当前实现:移动后 chunk 内的图片引用仍指向**源空间路径**,图片照常解析(源 MinIO 对象不被移动删除,移动只删源向量/ES)。仅当**源空间整体被删除**时这些图才会裂开——届时由空间删除流程或一次性清理脚本统一迁移。T007 已在任务体注释中标注该行为。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-09 | 初版（仅同空间） | feature 设计 |
| 2026-06-10 | v2：纳入跨空间（复用复制管线/版本链整链/REBUILDING 状态/二次确认无撤回）;编号 032→034（032=OFD、033=linsight 已占用） | PRD 范围升级,产品确认三决策 |
| 2026-06-10 | 实现完成（Wave 1-4 全通,21 后端测试绿,本地验证移动+toast）。3 项降级：①跨空间拖到左侧空间列表未做（跨组件树成本高,弹窗已覆盖）②同空间撤回未做（toast 无动作按钮,后端已留 old_parent_id）③图片目录物理迁移记债（坑 6）。i18n 占位符须用 `{{0}}` 双花括号 | 实现落地 + 务实降级 |
