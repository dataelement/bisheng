# 验证记录

- Date: 2026-09-22
- Status: VERIFIED（本地脚本交付）；真实环境迁移为 MANUAL_REQUIRED。当前科室库/部门库兜底规则的证据见末尾 T12，前面为历史记录。
- Code State: 新增独立脚本及两个测试文件，README 新增说明；未提交，保留已有工作区改动。
- Environment: `src/backend/.venv/bin/python`，Python 3.10；SQLite 临时数据库，仿真外部索引和权限。使用 `--noconftest` 避免全局测试预模拟替换生产查询实现。

## 证据

| Evidence | Command / Step | Result | Scope |
|---|---|---|---|
| E-001 | 实现前执行新增两个路由测试 | 预期红灯：脚本模块尚不存在，收集失败 | 测试先行 |
| E-002 | 下列四个测试文件联合执行 | PASS：154 passed, 7 warnings，8.16 秒，exit 0 | AC-1～4、原脚本回归 |
| E-003 | `.venv/bin/python -m ruff check scripts/move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic*.py` | PASS | 语法、导入、静态规范 |
| E-004 | 同上路径运行 `ruff format --check` | PASS：3 files already formatted | 格式 |
| E-005 | `.venv/bin/python scripts/move_personal_files_to_clinic.py --help` | PASS：展示完整路径、预览/apply、报告及恢复参数 | CLI |
| E-006 | `git diff --check` | PASS | 跟踪文件差异 |

E-002 命令（在后端根目录执行）：

```bash
.venv/bin/python -m pytest \
  test/scripts/test_move_personal_files_to_clinic.py \
  test/scripts/test_move_personal_files_to_clinic_integration.py \
  test/scripts/test_move_clinic_knowhow_to_public.py \
  test/knowledge/test_knowledge_migration_inline.py -q --noconftest
```

新增 74 项，既有相关回归 80 项；警告来自既有 TestUserRow 收集提示和第三方 Swig/jieba/pkg_resources 弃用提示。

## 覆盖范围

| Acceptance | Status | Evidence |
|---|---|---|
| AC-1 路径及后代、根目录、删除过滤、分页、租户隔离 | PASS | E-002：实际 ORM 查询及 500 条分页边界，全部扫描 SQL 为 SELECT |
| AC-2 原始上传人回退、唯一主组织、最近科室、固定首个目标、逐项原因 | PASS | E-002：规则参数化、组织循环/缺失/停用、兼任组织不参与 |
| AC-3 保留 ID/版本/向量/共享入口、逐层目录与根目录权限、目标冲突 | PASS | E-002：SQLite 事务与内容指纹校验；根目录权限对照现有权限服务的 parent 契约 |
| AC-4 预览无业务写入、执行前重查、失败继续、写报告失败停止、恢复 | PASS | E-002：索引/权限部分失败、提交响应丢失、提交后刷新失败、恢复拒绝额外授权/内容变化 |

## 发现与修正

- 根目录父权限对象使用项目真实类型 `knowledge_space`；新增测试与现有权限服务契约比对，避免仿真掩盖类型错误。
- 租户查询集成测试显式注册生产 SQLAlchemy 租户过滤事件，与真实初始化流程一致；确认不同租户文件被排除。
- 复核按规范文档处理，单个文档条件变化不阻塞同目录其他文档；复核只加载相关来源/目标目录，避免每个文档重复扫描全部个人库目录。

## 未执行及运行风险

- NOT_RUN：真实 MySQL/DM8、ES、Milvus、OpenFGA 端到端迁移。当前任务仅编写脚本，未授权连接或修改生产数据。
- MANUAL_REQUIRED：在部署环境先运行默认预览并核对未迁移清单；维护窗口停止相关写入后用真实超级管理员显式 `--apply`。
- 仅支持已就绪共享存储规范文档；没有版本链或未就绪内容不会自动解析补建。
- 数据库和外部索引/权限非原子；独立恢复文件需保留，恢复只修复中断项至数据库当前归属，不是整批撤销。空目录可能保留，需要人工核对。

## T4 报告精简验证（当前代码状态）

用户追加要求后，主报告改为仅含未迁移文件的五字段列表；预览、成功文件、路径未匹配与恢复快照不再混在主报告中。恢复子目录仅保存未完成单元的必要状态。

- 红灯：更新报告结构断言后，2 个定向测试因旧报告仍为完整对象而失败。
- E-007：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest` → **79 passed, 6 warnings，7.24 秒，exit 0**。
- 当前报告相关行为证据以 E-007 为准；前述 154 项联合回归为 T1～T3 阶段历史证据。
- E-007 覆盖：仅匹配但不符合条件的文件、执行失败、同目录其他文件成功不列出、全局失败时列出未处理文件、最小恢复状态、恢复回源保留原因、恢复成功移除记录、无法确认匹配的损坏目录不进入指定目录报告，以及已有迁移事务/权限/索引失败路径。
- E-008：修改的脚本/测试 Ruff check 与 format --check、`git diff --check` 均通过。
- 本次未执行真实迁移，未改动组织匹配、目标选择和迁移规则。

## T5 所有者失效回退验证（当前代码状态）

- 用户已确认目标库所有者失效时可使用操作人作为迁移文件的权限 owner；通过默认关闭的 `--use-operator-as-file-owner` 显式启用。
- 红灯：默认拒绝和有效所有者场景通过，启用开关的缺失/禁用所有者两个场景因原有检查拒绝而失败（2 failed, 4 passed）。
- E-009：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest` → **92 passed, 6 warnings，6.96 秒，exit 0**，覆盖当前 AC-1～5。
- 新覆盖：操作人校验失败时不启用回退；默认拒绝；缺失/禁用所有者可回退；有效所有者不替换；文件上传人/原始上传人和 Knowledge.user_id 不被新开关改写；索引失败和提交后失败均能恢复；恢复更换操作人不改变已记录的权限 owner；操作人禁用、目标库所有者变更和投影未就绪仍拒绝。
- E-010：修改脚本和两个测试文件 Ruff check、format 检查，`--help` 与 `git diff --check` 通过。
- 使用 security-review 校验本次权限变更边界：校验有效全局超级管理员后启用，限定失效所有者场景；保留租户/版本/审批/索引/权限读回验证；恢复只沿用写前持久化账号。
- 不改变主报告的精简结构；回退账号只存在于未完成单元的独立恢复状态中。
- 未部署或运行真实迁移；数据库及外部索引/权限仍为本地 SQLite 与仿真验证。

## T6 未解析文件支持（2026-09-30，当前代码状态）

- 用户授权修改脚本以支持未解析成功文件；未执行真实 apply、部署或连接生产服务。
- 红灯：新增非成功状态迁移用例在旧实现因“存在未完成或不一致的共享投影”失败。此前测试加载解析器时另遇本地 SciPy `_spropack` 动态库错误；测试改为对不应调用的解析/通用迁移入口设置调用即失败的模块替身，目录创建用例沿用 ORM 仿真并隔离业务服务导入。未修改运行环境或生产服务。
- E-011：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest --tb=short` → **127 passed，6.80 秒，exit 0**。
- 覆盖：状态 NULL/3/5/6/7 的规划及迁移；两侧无索引、仅 ES、部分分块；保留原状态/错误/上传人/内容/向量/未完成投影；未解析文件索引部分写入失败及提交后失败恢复；无版本链原始文件迁移、权限写后异常和提交后异常恢复；解析/重建/投影租约拒绝；空侧出现新分块或内容变化拒绝提交；原始文件已生成版本、已成功或目标冲突拒绝；原有成功文件严格校验、租户/组织/权限/恢复/报告行为回归。
- E-012：脚本及两份测试 `ruff check`、`ruff format --check`、脚本 `--help`、`git diff --check` 均通过。
- 限制：真实 MySQL/DM8、ES、Milvus、OpenFGA 尚未端到端验证；本地 SQLite 和外部接口仿真不能证明生产迁移已完成。实际 apply 仍要求维护窗口停止相关写入。正在解析/重建、执行中的投影、未知状态、损坏版本链、审批或其他业务条件不满足的文件仍记录并暂缓；迁移不修复解析失败、不创建缺失分块。

## T7 已有版本链但尚无管理入口（2026-10-12）

- 用户授权修改本地脚本；未部署、未连接生产或执行真实迁移。
- 红灯：新增正常迁移、权限写后异常恢复及提交后刷新失败恢复，在旧实现均因“规范文档主版本或管理入口异常”失败（6 failed）；修复后同组通过。
- E-013：使用 backend `.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic_integration.py -k versioned_without_manager -q --noconftest --tb=short` → **22 passed，1.47 秒，exit 0**。
- E-014：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest --tb=short` → **150 passed，9.17 秒，exit 0**。随后仅将测试准备函数中未使用的局部绑定改名为 `_backend` 以通过静态检查，不改变可执行行为。
- 覆盖：规划保留已有文档 ID；完整多版本链及文档迁移；保留 NULL/3/5/6/7 解析状态、错误原因、原文件、上传人和全部入口/投影进度；引用为空或当前文档均支持；无解析任务、无管理入口创建、无索引写入；权限写后异常按源库恢复、提交后异常按目标库恢复；主版本不一致、文档位置异常、已有成功版本、外部文档引用、失效管理入口、共享入口、投影租约、审批、缺失版本文件、已有共享内容均拒绝；提交前出现内容及恢复前激活入口拒绝覆盖。
- E-015：三份 Python 文件 `ruff check`、`ruff format --check`，脚本 `--help`、`git diff --check` 均通过。静态检查曾发现一个测试局部变量未使用，已修复并复验。
- 限制：无管理入口路径要求 ES/Milvus 共享内容均为空。已有共享内容需核对入口关系，`--force-rewrite` 不放过该状态。本地 SQLite 与外部接口仿真不能替代 MySQL/DM8 行锁及真实索引/权限端到端验证；正式执行仍需维护窗口停止相关写入。

## T8 所有个人库的接口同步文件（2026-10-12）

- 用户要求遍历全部个人库，仅把接口同步文件迁到原始上传人的科室绑定库；复用已有脚本，增加 `--api-sync-only`，默认普通模式不变。没有部署、连接生产或执行真实 apply。
- 红灯：新增来源及命令用例在实现前因缺少 `api_sync_only` 参数/命令开关失败（8 failed）。
- E-016：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -k api_sync -q --noconftest --tb=short` → **17 passed，0.85 秒，exit 0**。
- E-017：同上命令去掉 `-k api_sync` → **167 passed，8.19 秒，exit 0**。
- 新增覆盖：两种接口元数据标记、空/无效元数据、普通模式兼容、原始上传人优先、原目录保留、混合来源版本链拒绝及只记录接口文件；CLI 省略目录扫描全部个人库、失败报告和恢复单元持久化筛选；规范文档、未建立管理入口文档及无版本文件正常迁移，锁内及恢复阶段来源标记消失时拒绝写入。
- E-018：三份 Python 文件 `ruff check`、`ruff format --check`、脚本 `--help` 均通过；`git diff --check` 通过。
- 接口来源口径从当前 `audit_api_sync_uploader_clinic_spaces.is_api_sync_file`、`move_clinic_knowhow_to_public` 和同步服务写入元数据验证，不按文件名或普通 `file_source` 字段推测；不修改其他现有接口迁移脚本。
- 限制：复用 T7 的无管理入口、共享存储及维护窗口约束。本地 SQLite 与仿真不能证明生产 MySQL/DM8、ES、Milvus、OpenFGA 端到端迁移成功。

## T9 接口同步文件只取直接目录（2026-10-12）

- 用户修正接口同步迁移模式的目录口径：目标只取文件直接所在目录名，根文件迁入目标根目录。普通模式和旧恢复报告的目标不改变；未部署或执行真实迁移。
- 红灯：修改目录映射断言及新增同名目录/目标冲突用例，在旧实现因仍保留完整路径而失败（5 failed, 7 passed）。
- E-019：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -k api_sync -q --noconftest --tb=short` → **29 passed，1.29 秒，exit 0**；随后补充两种文件类型的目标文件重名保护，纳入最终回归。
- E-020：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest --tb=short` → **181 passed，8.87 秒，exit 0**。
- 覆盖：目标仅保留直接目录、不同完整来源的同名目录合并、根目录文件、完整来源路径筛选及失败报告、目标库根下同名文件阻断目录创建；规范文档/无管理入口/无版本链三种文件迁移至一级目录并验证路径及层级，权限写后异常和提交后异常分别恢复源/目标；来源祖先或目标目录改名时拒绝，源路径与目标路径分别校验；目标文件重名时不覆盖；旧接口同步恢复报告仍沿用完整目标层级。
- E-021：三份 Python 文件 `ruff check`、`ruff format --check`、脚本 `--help`、`git diff --check` 通过。测试中的正则表达式已改用原始字符串以符合静态规则；无运行时行为变化。
- 限制：依旧要求维护窗口和共享存储。不同来源目录折叠到同名目标目录后，文件冲突跳过并记录；不删除或覆盖目标文件。SQLite/外部接口仿真不能证明生产环境迁移完成。

## T10 后台执行准备（2026-10-12）

- 生产只读预检：1362 个候选、746 个组织路由跳过；目标重名 113 个、候选相互冲突 28 个（有重叠），冲突去重 123 个。用户明确保留目标文件、冲突源文件暂缓，固定执行清单为 1239 个文件，869 个暂缓文件不移动。
- 6 个非冲突文件解析成功但仅有管理入口、共享投影 failed，内容代次未应用且无租约；只读检查 ES/Milvus 均无分块，OpenFGA 读取通过。增加默认关闭的保守迁移开关并保留失败状态。
- 65 个执行范围内文件的目标库所有者失效，沿用已确认的操作人回退方案；管理员 ID 1 的全局超级管理员身份通过生产只读核查。
- 定向复现：原实现开启选项仍拒绝失败投影（3 failed, 3 passed）。修复后，定向 12 项通过，覆盖正常迁移、提交前后恢复及租约/投影执行/共享入口/代次异常拒绝。
- E-022：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py /Users/wenruli/code/project/bisheng/首钢项目/outputs/personal-clinic-run-plan-20261012/test_scoped_migration.py -q --noconftest --tb=short -o asyncio_mode=auto` → **197 passed，9.92 秒，exit 0**。
- 控制器测试覆盖固定范围、路由变化、暂缓报告保留、越界文件拒绝、维护条件拒绝、成功审计及审计写入失败停止。仅运行外部测试目录时需显式 `asyncio_mode=auto`，避免未读取后端 pytest 配置。
- Ruff check、格式检查、CLI help、启动脚本 `sh -n` 和 `git diff --check` 通过。控制器最终数据库核验和解冻为静态准备，尚未真实执行。
- 生产脚本副本与本地原版差异仅模块说明和空行；本次新增代码尚未部署，未冻结写入或启动 apply，等待维护窗口确认。

## T11 原始上传人匹配失败后使用当前上传人（2026-10-13）

- 原始上传人优先；用户无效、主组织异常、组织链异常、无科室或无有效科室库时，使用不同的当前上传人按相同规则再次查找。两者均失败保留原错误码并记录两次原因；已有上传人字段保持不变。
- 预览加载及执行前复核同时批量查询两人的用户和主组织信息，匹配来源或目标变化仍拒绝迁移。恢复继续使用原报告记录的目标。
- 红灯：新增规则及查询集成场景在旧实现出现 11 failed、3 passed，失败对应不兜底或缺少双人失败原因。集成测试准备过程中修正了重复绑定同一科室库的唯一约束冲突；原有拒绝测试改为隔离当前上传人的有效兜底路由。
- E-023：在 `src/backend/` 执行 `.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest --tb=short` → **205 passed，9.87 秒，exit 0**。
- 覆盖：原始上传人有效时优先其科室库、八类匹配失败后的当前上传人兜底、当前上传人缺失或相同、两人均无库的失败原因、真实 ORM 查询加载两人信息、完整版本链迁移且保留上传人，以及执行前原始上传人路由恢复有效时拒绝沿用旧计划。
- E-024：三份 Python 文件 `ruff check`、`ruff format --check`，脚本 `--help`、`git diff --check` 均通过。
- 边界：仅本地脚本及文档修改；未提交、未部署、未连接生产或执行真实迁移。SQLite 与索引/权限仿真不替代真实 MySQL/DM8、ES、Milvus、OpenFGA 的端到端验证。

## T12 科室库均匹配失败后兜底部门库（2026-10-13）

- 用户确认四级顺序：原始上传人科室库 → 当前上传人科室库 → 原始上传人部门库 → 当前上传人部门库。全部失败才跳过；保留首次错误码并记录不同失败原因，同人及同一组织错误去重。
- 从唯一主组织向上查最近 `org_level=dept`；部门库必须发布、非收藏、范围为 `department`、owner_type 为 `department`，且 owner_id 与实际部门绑定一致。同阶段多库按 ID 取首个，不越过无绑定的最近部门查上级部门。
- 部门路由保存 `department_id`，执行及恢复锁内复核目标类型、范围归属和绑定。旧科室库计划/恢复单元仍只接受科室库，恢复不按新组织路由重新选目标。使用 security-review 检查目标类型边界和绑定一致性，保留租户、权限所有者及写后读回校验。
- 红灯：新增场景在原实现为 15 failed、2 passed；失败因缺少部门库兜底或部门失败原因。修复后调整无版本链测试的权限断言，只核对迁移单元内文件，排除准备数据中已删除的历史文件权限。
- E-025：`.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -k 'department_fallback or clinic_plan_cannot_accept' -q --noconftest --tb=short` → **24 passed，1.09 秒，exit 0**，此后补充接口同步模式的迁移和恢复参数，纳入 E-026。
- E-026：在 `src/backend/` 执行 `.venv/bin/python -m pytest test/scripts/test_move_personal_files_to_clinic.py test/scripts/test_move_personal_files_to_clinic_integration.py -q --noconftest --tb=short` → **235 passed，10.76 秒，exit 0**。
- 覆盖：四级顺序、部门首库选择、主组织本身为部门、最近无库不越级、缺绑定/错误范围归属/停用部门/无效库拒绝；普通和接口同步模式下规范文档及无版本链文件迁入部门库，提交前权限失败和提交后刷新失败恢复且固定报告目标；执行及恢复时目标类型、owner_id 或绑定变更拒绝；科室库旧计划不能直接接受部门库目标。
- E-027：三份 Python 文件 `ruff check`、`ruff format --check`，脚本 `--help`、`git diff --check` 均通过。
- 边界：未提交、未部署、未连接生产或执行真实迁移。SQLite 与索引/权限仿真不能证明 MySQL/DM8、ES、Milvus、OpenFGA 的真实迁移结果。
