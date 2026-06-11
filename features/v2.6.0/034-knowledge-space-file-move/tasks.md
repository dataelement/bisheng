# Tasks: 知识空间文件 / 文件夹移动（同空间 + 跨空间）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-06-10；产品拍板三点已回写；AC-03 已补「拖拽支持跨空间（投放到左侧空间项）」。2026-06-10 扩充 §5.5 文件夹上传（2.7 节 AC-24~31），/sdd-review spec 实质 LGTM（仅 2 条 low：AC-25/校验分工略带 How、3.2.4 作废系产品决策） |
| design.md | ✅ 已评审 | 2026-06-10；Constitution Check 无 BLOCKER；评审 4 项发现已修复（C2 子树 SQL 方言 / 同租户边界 / 决策备选与触发条件 / 手动验证入口）。同日 §9 文件夹上传（AC-24~31）评审：无 BLOCKER，1 项 medium 已修（补 C4 权限口径——入口 `upload_file` + 建夹逐节点 authorize，坑 U7）；2 low 记录跳过（U2 无重考触发条件、上传 Wave 待拆解） |
| tasks.md | ✅ 已拆解 | 2026-06-10 /sdd-review tasks LGTM（修复 4 项：T006/T007 任务内 Test-First、T007 tenant_id 传递、T009 数据源、T012 AC 标注格式）。2026-06-11 新增 Wave 5 文件夹上传 T013~T016，/sdd-review tasks LGTM（1 low 记录跳过：18025 并入 T013） |
| 实现 | 🔨 Wave 5 进行中 | Wave 1-4（移动）12/12 完成、本地验证通过（2 项降级见偏差记录；同空间撤回已改用 confirm 弹窗）。Wave 5（文件夹上传）4/4 代码完成；T016 手动回归待跑（design §9.7 清单） |

---

## 开发模式

按 Wave 组织；后端 Test-First 配对；前端手动验证（验证入口见 design §7）。
设计论证一律指向 design §3 决策 / §5 坑，任务内不复制。

---

## Tasks

### Wave 1 — 基础零件（无互相依赖，可并行）

- [x] **T001**: 权限模板新增 move_file / move_folder
  **文件**: `src/backend/bisheng/permission/domain/knowledge_space_permission_template.py`
  **逻辑**: 文件级权限项加 `{'id': 'move_file', 'label': '移动文件', 'relation': 'can_edit'}`，文件夹级同理加 `move_folder`（与 rename_file/upload_file 同档；见 design 决策 5——不动 OpenFGA 模型、不迁 tuple）
  **测试**: 断言 `default_permission_ids_for_relation`：editor/manager/owner 档含 move_file/move_folder，viewer 档不含
  **覆盖 AC**: AC-05, AC-06
  **依赖**: 无

- [x] **T002**: 错误码 SpaceMoveInvalidTargetError(18033)
  **文件**: `src/backend/bisheng/common/errcode/knowledge_space.py`
  **逻辑**: 18033，语义=无效移动目标（移入自身/子目录/当前父目录）；release-contract 已登记
  **覆盖 AC**: AC-10（对外可观测错误）
  **依赖**: 无

- [x] **T003**: DAO 子树辅助
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_space_file.py`（SpaceFileDao）
  **逻辑**: 新增「子树最深 level」查询（供 10 层校验按子树最深算，见 design 坑 2）；确认 `get_children_by_prefix` / `count_folder_by_name` / `count_file_by_name` 可复用。**C2 注意**：避免 MySQL-only SQL（design §2）
  **覆盖 AC**: AC-11（支撑）
  **依赖**: 无

### Wave 2 — 移动服务（Test-First）

- [x] **T004**: move_items 单元测试（先红）
  **文件**: `src/backend/test/knowledge/test_knowledge_space_move.py`
  **逻辑**: mock DAO / PermissionService / celery 派发，覆盖：
  - 同空间校验矩阵：无 move 权限(no_permission) / into_self / into_subtree / into_current_parent / depth_exceeded（按子树最深）/ name_conflict / `skip_invalid` 两步语义（false 有冲突→不提交只回清单；true→提交其余）
  - 级联：移动文件夹后子孙 `file_level_path` 前缀替换 + level 偏移正确
  - 权限：只校验入参项不递归子项（AC-08）；parent tuple 删旧写新（AC-09 直绑不变由 tuple 不动保证）
  - 跨空间：版本链整链 knowledge_id 变更（主+历史，document 锚点一起）；文件标签清空；SUCCESS→REBUILDING、非 SUCCESS 状态保持；不做重名校验；跨租户目标→18041
  **覆盖 AC**: AC-01, AC-02, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-20, AC-23
  **依赖**: T001, T002, T003

- [x] **T005**: KnowledgeSpaceService.move_items 实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**: 编排=逐项校验 → 同/跨空间分流（design 决策 1/3）→ 事务内改 `file_level_path`/`level`（+跨空间改 `knowledge_id` 整版本链、清标签、置 REBUILDING）→ parent tuple 替换 → 跨空间逐文件派发 `migrate_file_vectors`。版本链展开参照 `_cascade_version_links_on_delete`（design 决策 4）
  **测试**: T004 全绿
  **覆盖 AC**: 同 T004
  **依赖**: T004

- [x] **T006**: API 端点 + 集成测试
  **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`、`src/backend/test/knowledge/test_knowledge_space_move_api.py`
  **逻辑**: `POST /{space_id}/files/move`（请求/响应契约=design §4.2，含 `target_space_id`/`skip_invalid`/`moved[].old_parent_id`/`invalid[].reason`）；收参调 service 不写业务。**任务内先写集成测试（红）再实现端点（绿）**。若现有空间列表接口无法按 `upload_file` 权限过滤（供 T009 弹窗左侧用），本任务一并补查询参数（复用 ReBAC `list_accessible_ids`）
  **测试**: happy path（同/跨空间）+ invalid 清单不提交 + skip_invalid 提交其余
  **覆盖 AC**: AC-01, AC-14, AC-15（后端语义侧）
  **依赖**: T005

### Wave 3 — 跨空间迁移任务

- [x] **T007**: migrate_file_vectors celery 任务 + 幂等单测
  **文件**: `src/backend/bisheng/worker/knowledge/move_worker.py`、`src/backend/test/knowledge/test_move_worker.py`
  **逻辑**: 按 file 当前 knowledge_id 解析目标（design 坑 7）：源空间 ES 读全部 chunk → metadata 更新（knowledge_id 等）→ 目标空间 `add_texts` 双写 Milvus+ES（目标模型自动重嵌入，design 决策 2）→ 删源空间数据（按 file_id，幂等）→ 状态 REBUILDING→SUCCESS / 失败→FAILED（可重试）。**图片目录**：拷贝 `knowledge/images/{old_kid}/{doc_id}` 至新空间路径并更新 chunk 引用（design 坑 6，做全）。**解析中兜底**：验证 design 坑 8 的窗口，必要时在解析任务完成段回查归属
  **约束**: 任务参数携带 `tenant_id`（Celery headers → 执行前恢复 `current_tenant_id` ContextVar，与既有 knowledge_celery 任务一致）。**任务内先写幂等单测（红）再实现（绿）**
  **测试**: mock ES/Milvus/minio；幂等（重复执行不重复写/删错）；失败置 FAILED
  **覆盖 AC**: AC-19, AC-21, AC-22
  **依赖**: T005

### Wave 4 — 前端 Client（手动验证）

- [x] **T008**: client API 封装
  **文件**: `src/frontend/client/src/api/knowledge.ts`
  **逻辑**: `moveFilesApi(spaceId, {items, target_space_id, target_folder_id, skip_invalid})`，错误带 status_code 供分支
  **依赖**: T006

- [x] **T009**: MoveToDialog 移动到弹窗
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/MoveToDialog.tsx`
  **逻辑**: 左侧=有 upload_file 权限的空间列表（首项当前空间；数据源=T006 确认/补充的过滤接口）；右侧=选中空间的文件夹树（cursor 懒加载）+ 文件（置灰）；无上传权限文件夹置灰；「移动到此」
  **覆盖 AC**: AC-04, AC-07
  **手动验证**: 120 环境两账号对比可见空间/置灰项
  **依赖**: T008

- [x] **T010**: 多选拖拽（同空间 + 跨空间）
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/`（DnD hook + 列表行 + 侧栏空间项 drop target）
  **逻辑**: 多选整批拖拽；投放目标=可视文件夹行（同空间）+ **左侧空间列表项（跨空间→该空间根，松手后二次确认）**；拖拽中禁 hover 展开/跳转（design 坑 10）
  **覆盖 AC**: AC-02, AC-03
  **手动验证**: 多选拖到文件夹行 / 拖到侧栏其它空间；拖拽中 hover 文件夹不展开
  **依赖**: T008

- [x] **T011**: 交互整合（冲突弹窗 / 撤回 / 二次确认 / 处理中）
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/`（index + toast/confirm 组件）
  **逻辑**: 批量冲突弹窗「存在无权限移动的文件/文件夹：{名称}」【移动其余文件】【取消移动】（其余 reason 同理）；同空间成功 toast 带「撤回」（记 old_parent_id 反向 move，失败提示不破坏当前态，design 决策 7）；跨空间二次确认 + 成功 toast（无撤回，design 决策 8）；REBUILDING 显示「处理中」
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-17, AC-18, AC-19（前端侧）
  **手动验证**: 混合有/无权限批量移；同空间移后 3 秒内撤回 / 超时撤回入口消失；跨空间确认弹窗与处理中流转
  **依赖**: T009, T010

- [x] **T012**: i18n（zh-Hans / en / ja）+ 全量手动验证清单
  **文件**: `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 弹窗/确认/toast/错误提示全部 key 化；按 design §7 手动验证一遍（两空间互移、多版本文件、不同 embedding 模型、各状态文件），作为对 AC-01 至 AC-23 的端到端人工回归
  **依赖**: T011

### Wave 5 — 文件夹上传（§5.5 / AC-24~32，design §9）

- [x] **T013**: 后端 upload_folder_items 服务（任务内 Test-First）+ 错误码 18025
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`、`src/backend/bisheng/common/errcode/knowledge_space.py`、`src/backend/test/knowledge/test_knowledge_space_folder_upload.py`
  **逻辑**: 新增 `upload_folder_items(parent_id, items[{file_path, relative_path}])` 编排（design 决策 U1）：入口 `_require_permission_id('upload_file')`（同 `add_file:2952` 口径）→ 数量兜底 ≤1000（18025）→ 顶层夹重名 `count_folder_by_name`（18012）→ 解析 relative_path 建目录树（每节点初始化权限 tuple，**坑 U7**，复用 `_initialize_child_resource_permissions`）→ 建树后最深层级 ≤10（18011）→ **容量整批预校验**（本批总大小+已用 vs 用户档/租户上限，**坑 U2**，18024/19403）→ 逐文件复用现有注册+解析派发逻辑（文件重名走现有 FAILED+覆盖语义，**坑 U4**，不拒批）。整批校验失败不留半成品（事务）
  **测试**: 先红后绿——多层 path 建树父子正确 / 层级>10 整批拒 / 顶层重名拒 / 容量触顶整批拒不留半成品 / >1000 拒 / 文件重名不拒批 / 每个新建夹有权限初始化调用
  **覆盖 AC**: AC-25, AC-26, AC-28, AC-29, AC-30, AC-31
  **依赖**: 无（复用 Wave 1-2 现成件）

- [x] **T014**: API 端点 POST /{space_id}/folders/upload + 集成测试
  **文件**: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`、`src/backend/test/knowledge/test_knowledge_space_folder_upload_api.py`
  **逻辑**: 请求/响应契约=design §9.4（items[{file_path, relative_path}]；响应复用 add_file 每文件结果结构）；收参调 service 不写业务。**任务内先写集成测试（红）再实现端点（绿）**
  **测试**: happy path（嵌套树）+ 各拒批场景返回对应错误码（前端据此 toast，AC-32）
  **覆盖 AC**: AC-25, AC-32（错误码可观测侧）
  **依赖**: T013

- [x] **T015**: 前端目录读取升级（全量嵌套）+ 过滤 + 1000 挡 + toast
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileDragDrop.ts`、`src/frontend/client/src/pages/knowledge/knowledgeUtils.ts`、`SpaceDetail/index.tsx`
  **逻辑**: 拖拽 `readTopLevelFolderFiles` 改递归读全部子目录（保真 relativePath）；废 `filterFolderUploadFiles` 单层过滤（design 决策 U2），改为全层级保留 + 静默过滤（格式/隐藏/超大；隐藏判定按 path **每一段**，**坑 U5**）；原始总数（过滤前）>1000 → toast「单次批量文件总数最多 1000 个」整批不传（决策 U3）；全被过滤 → toast 无可上传文件，不发请求
  **覆盖 AC**: AC-24, AC-26, AC-27, AC-32（前端侧）
  **手动验证**: 拖 3 层嵌套文件夹（混入不支持格式/隐藏/超大）；picker 入口同验
  **依赖**: 无（与后端并行）

- [x] **T016**: 前端接通批量接口 + 拒批 toast + i18n + 手动回归
  **文件**: `src/frontend/client/src/api/knowledge.ts`、`src/frontend/client/src/pages/knowledge/hooks/useFileUpload.ts`、`src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 新增 `uploadFolderApi(spaceId, {parent_id, items})`；`handleUploadFolder` 改为：逐文件 `uploadFileToServerApi` 传本体 → 调批量接口注册建树 → 刷新列表；**服务端拒批错误码（18011/18012/18025/18024/19403）逐一映射 toast 文案（AC-32）**；文件重名 FAILED 项复用现有覆盖弹窗；文案 key 化三语；按 design §9.7 手动回归（含顶层重名、构造超容量）
  **覆盖 AC**: AC-24, AC-25, AC-29, AC-30, AC-31, AC-32
  **手动验证**: design §9.7 清单全跑
  **依赖**: T014, T015

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。

- Wave 5 / T013：接口契约 items 增加 `size` 字段（前端报告字节数）——容量整批预校验的数据源；权威配额校验仍在注册环节逐文件执行。design §9.4 已更新。
- Wave 5 / T016：服务端拒批 toast 未逐码手写映射——`uploadFolderApi` 走 `skip403Redirect` 统一拦截管线，自动按 `api_errors.<code>` 翻译并 toast（18011/18012/18024/19403 文案已存在，新增 18025 三语）；前端挡下的（>1000、全被过滤、顶层重名预查）显式 showToast。AC-32 全覆盖。
- Wave 5：隐藏的顶层文件夹整体拖入 → 静默不上传（沿用既有行为,属 AC-27 静默过滤语义延伸）。

- T007：图片目录物理迁移由「做全」改为「记债」（doc_id↔file_id 键不确定，误拷会弄坏引用）；移动后图片引用仍指向源空间路径、照常解析，仅源空间被删时才需迁移。论证见 design §8 + §5 坑 6。
- T010：拖拽**仅做同空间拖到文件夹**（用户 2026-06-10 拍板）。跨空间拖到左侧空间列表项降级——左侧空间列表在 `pages/knowledge/sidebar/KnowledgeSpaceItem.tsx`，与 SpaceDetail 不同组件树，跨树传 payload + 外层接移动编排成本高；跨空间移动已由「移动到」弹窗完整覆盖。AC-03 跨空间拖拽部分未实现。
- T011：同空间**撤回（AC-16/17）已实现**——因 toast 无动作按钮，改用 confirm 弹窗承载（移动成功后弹「已移动 N 项 / [撤回][关闭]」），撤回按 `moved[].old_parent_id` 分组反向移动（见 `useKnowledgeMove.undoMove`）。其余（冲突两步 / 跨空间二次确认 / 处理中状态）均已实现。
- 修复：移动成功 toast 文案占位符须用 react-i18next 双花括号 `{{0}}`（初版误用单花括号导致计数恒显 0），已在 move_success / move_cross_success / move_partial_desc 三 key 修正。
