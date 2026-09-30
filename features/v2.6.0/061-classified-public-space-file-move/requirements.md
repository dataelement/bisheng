# 需求说明 Requirements: 按文件分类自动移动到公共知识空间

## 阅读摘要
- 本文档说明：重写知识空间文件移动脚本，使其支持多个来源空间，并按一级、二级分类名称自动路由到公共知识空间及直属目录。
- 当前状态：`implemented`（目标标签快照一致性修复已通过自动化回归，真实 apply 待重新验证）
- 需要重点确认：版本链必须整体迁移；目标名称必须唯一精确匹配；`--apply` 会删除来源并生成新文件 ID。

## 元信息 Metadata
- Feature ID: `061-classified-public-space-file-move`
- Status: `implemented`
- Mode: `spec-then-implement`
- Created: `2026-07-17`
- Updated: `2026-07-17`
- Source request: `重写文档移动脚本，按一级/二级文件分类自动移动到公共知识空间及目录`

## 需求入口摘要 Intake Summary
- 问题 Problem: 现有脚本只能把一个来源空间的选定文件移动到一个显式目标，无法按门户分类批量分流多个来源空间。
- 当前状态 Current state: CLI 绑定单一 `source_space_id`、`target_space_id`、`target_folder_id` 和 `target_owner_id`；版本链文件被直接跳过。
- 目标结果 Target outcome: 运维人员只需指定多个来源空间 ID，脚本即可扫描全部成功文件，按分类 label 唯一匹配公共空间和根目录直属文件夹，并安全移动普通文件或完整版本链。
- 影响对象 Affected users/systems: 运维人员、知识空间文件、版本管理、门户分类配置、MySQL、MinIO、Milvus、Elasticsearch、标签和 OpenFGA。
- 请求停止点 Requested stopping point: `implementation + verification`

## 范围 Scope

### 包含 Includes
- `--source-space-id` 可重复传入，至少指定一个来源知识空间。
- 扫描每个来源空间全部目录层级下 `file_type=FILE`、`status=SUCCESS` 的文件。
- 从 `file_encoding` 解析一级分类 code，从 `file_subcategory_code` 读取二级分类 code。
- 使用门户配置把一级、二级 code 转换为对应 label。
- 一级 label 唯一精确匹配 `level=public` 的知识空间名称。
- 二级 label 唯一精确匹配目标空间根目录直属文件夹名称。
- 迁移普通文件和满足整体约束的完整版本链。
- 移动后文件所有者改为目标公共知识空间所有者。
- 迁移数据库记录、MinIO 对象、Milvus/Elasticsearch 索引、已通过及待审核标签，并重建目标 owner/parent 权限。
- 默认 dry-run；只有 `--apply` 才执行数据写入和来源删除。
- 每次执行生成逐文件、逐版本链可追踪的 JSON 报告。

### 不包含 Excludes
- 自动创建、改名或修复公共知识空间及文件夹。
- 模糊匹配、包含匹配或以 code 直接匹配目标名称。
- 将缺少二级分类的文件移动到目标空间根目录。
- 目标向量模型不一致时重新解析、重新嵌入或直接复制不兼容索引。
- 覆盖目标已有文件。
- 扩大到未指定来源空间中的版本文件。
- 启用多租户或实现跨租户标签、权限重映射；当前部署未启用多租户。
- 迁移收藏、分享链接以及其他保存旧文件 ID 的外部引用。
- 对真实业务环境自动执行 `--apply`。

## 需求列表 Requirements

### REQ-001: 多来源空间文件发现
作为运维人员，我需要一次指定多个来源知识空间，以便统一扫描所有符合条件的文件。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 命令重复传入多个 `--source-space-id` THEN 脚本 SHALL 去重并按空间 ID、文件 ID 稳定顺序扫描每个有效来源空间。
- `AC-REQ-001-02`: WHEN 来源记录不是普通文件或状态不是 `SUCCESS` THEN 脚本 SHALL 不选择该记录进行迁移。
- `AC-REQ-001-03`: WHEN 任一来源空间不存在或不是知识空间 THEN dry-run/apply SHALL 在写入前明确失败并返回输入错误退出码。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated unit test | `test/scripts/test_move_knowledge_space_files.py` 覆盖重复参数、去重与稳定排序 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | automated unit test | 文件类型和状态矩阵测试 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated preflight test | 无效来源空间在构造写操作前失败 |

### REQ-002: 按分类 label 唯一路由
作为运维人员，我需要脚本根据文件分类自动确定目标空间和目录，以避免人工维护目标 ID 映射。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN 文件同时具有有效一级、二级分类 code THEN 脚本 SHALL 从门户配置解析对应一级、二级 label。
- `AC-REQ-002-02`: WHEN 一级 label 唯一匹配公共空间名称且二级 label 唯一匹配该空间根目录直属文件夹 THEN 脚本 SHALL 生成该文件的目标路由。
- `AC-REQ-002-03`: IF 任一分类缺失、配置中不存在、目标名称未命中或命中多个候选 THEN 脚本 SHALL 跳过文件并记录稳定原因码，不产生迁移写入。
- `AC-REQ-002-04`: WHEN 同名文件夹只存在于目标空间更深层级 THEN 脚本 SHALL 视为未匹配，不递归使用该目录。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated unit test | 分类 code-to-label 索引及父子关系测试 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | automated resolver test | 公共空间和直属文件夹唯一匹配测试 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | parametrized unit test | 缺失、未知、零候选、多候选原因码矩阵 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | automated resolver test | 深层同名目录不参与候选 |

### REQ-003: 冲突与模型兼容性保护
作为运维人员，我需要不兼容或有重复风险的文件被安全跳过，以避免目标数据污染。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 目标目录已有同名普通文件 THEN 来源文件或整条版本链 SHALL 跳过并保留来源。
- `AC-REQ-003-02`: WHEN 目标空间任意位置已有相同 MD5 THEN 来源文件或整条版本链 SHALL 跳过并保留来源。
- `AC-REQ-003-03`: WHEN 来源空间与目标空间的向量模型不同 THEN 来源文件或整条版本链 SHALL 跳过，不复制索引。
- `AC-REQ-003-04`: WHEN 多个来源迁移单元路由到同一目标并互相同名或 MD5 冲突 THEN 脚本 SHALL 按稳定顺序保留第一个候选，其余跳过。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | automated unit test | 目标目录同名冲突测试 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | automated unit test | 目标空间 MD5 冲突测试 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | automated unit test | 模型不一致跳过测试 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | automated deterministic-order test | 多来源冲突预留集合测试 |

### REQ-004: 版本链整体迁移
作为版本管理用户，我需要移动后的逻辑文档保留完整版本关系，以便历史版本、版本号和主版本语义不被破坏。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: WHEN 文件属于版本链 THEN 脚本 SHALL 读取该逻辑文档的全部版本并将其作为一个迁移单元。
- `AC-REQ-004-02`: IF 链内任一文件不在指定来源空间、不是 `SUCCESS`、分类不完整、路由目标不同、模型不兼容或存在目标冲突 THEN 脚本 SHALL 跳过整条链。
- `AC-REQ-004-03`: WHEN 版本链满足全部条件并成功应用 THEN 目标 SHALL 使用新文件 ID 重建逻辑文档、原版本号、`is_primary` 和 `primary_version_id`。
- `AC-REQ-004-04`: WHEN 版本链迁移在来源删除前失败 THEN 脚本 SHALL 清理已创建的目标文件和目标版本图，并完整保留来源链。
- `AC-REQ-004-05`: WHEN 来源删除阶段发生可恢复失败 THEN 脚本 SHALL 尝试恢复来源文件工件和版本图，并在报告中记录补偿结果，不得报告整链成功。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | automated planner test | 按 `document_id` 聚合及版本排序测试 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | parametrized planner test | 范围、状态、分类、路由、模型和冲突矩阵 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | automated saga/service test | 新旧文件 ID 映射和目标版本图断言 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | automated failure-path test | 复制、标签、权限、版本图、验证阶段失败补偿 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | automated failure-path test | 部分来源删除失败后的恢复与报告断言 |

### REQ-005: 目标所有权与工件完整性
作为目标公共知识空间管理员，我需要迁移文件归属于目标空间所有者，并且检索、预览和标签数据完整可用。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN 路由目标有效 THEN 每个目标文件 SHALL 将 `user_id/user_name/updater_id/updater_name` 设置为目标空间所有者。
- `AC-REQ-005-02`: WHEN 普通文件或版本链成功移动 THEN 原件、转换件、BBox、预览、Milvus、Elasticsearch、已通过和待审核标签 SHALL 与来源快照一致。
- `AC-REQ-005-03`: WHEN 目标文件创建 THEN OpenFGA SHALL 只写入目标所有者 `owner` 和目标目录 `parent` 必要关系，不复制来源访问权限。
- `AC-REQ-005-04`: IF 目标空间所有者不存在或已禁用 THEN 路由到该空间的文件 SHALL 跳过并记录原因。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | automated operations test | 目标记录所有者字段断言 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | automated snapshot/verification test | 存储、索引和标签快照数量/存在性断言 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | automated permission test | owner/parent tuple 且无来源权限复制 |
| AC-REQ-005-04 | V-AC-REQ-005-04 | automated preflight test | 缺失或禁用目标所有者跳过测试 |

### REQ-006: 安全执行、报告与退出状态
作为运维人员，我需要在真实写入前审核完整计划，并在失败后获得可追踪结果。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 未传 `--apply` THEN 脚本 SHALL 只执行读取和报告写入，不构造或调用业务写操作。
- `AC-REQ-006-02`: WHEN dry-run 或 apply 完成 THEN JSON 报告 SHALL 包含参数、来源/目标、分类、迁移单元类型、版本关系、状态、原因码、目标新 ID 和补偿错误。
- `AC-REQ-006-03`: WHEN 任一迁移单元失败 THEN apply SHALL 返回非零退出码；只有成功与业务跳过时 SHALL 返回零。
- `AC-REQ-006-04`: WHEN 普通文件目标复制或校验失败 THEN 脚本 SHALL 保留来源并尽力清理目标残留。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | automated run test | dry-run 不实例化写操作且只生成报告 |
| AC-REQ-006-02 | V-AC-REQ-006-02 | automated report schema test | JSON 字段及普通文件/版本链结果断言 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | automated exit-code test | success/skipped/failed 组合退出码测试 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | automated failure-path test | 普通文件既有补偿回归测试 |

### REQ-007: 使用项目统一 MinIO 客户端入口
作为迁移脚本执行者，我需要来源工件快照和预览复制使用当前项目的 MinIO 客户端入口，以便 apply 不会在复制前因调用不存在的方法而失败。

#### 验收标准 Acceptance Criteria
- `AC-REQ-007-01`: WHEN 脚本检查来源对象是否存在 THEN 脚本 SHALL 通过 `get_minio_storage_sync()` 获取客户端，并使用其 bucket 和 `object_exists_sync()` 完成检查。
- `AC-REQ-007-02`: WHEN 脚本补充复制预览对象 THEN 脚本 SHALL 使用同一客户端的 `copy_object_sync()`，且不存在来源对象时不得发起复制。
- `AC-REQ-007-03`: WHEN 来源对象快照成功 THEN 普通文件迁移 SHALL 继续进入 `copy_normal`；不得再出现 `KnowledgeUtils.get_minio_client` 的 `AttributeError`。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01 | V-AC-REQ-007-01 | automated regression test | 直接调用 `_storage_exists()`，断言统一 MinIO 入口及对象检查参数 |
| AC-REQ-007-02 | V-AC-REQ-007-02 | automated regression test | 直接调用 `_copy_object_if_present()`，覆盖存在/不存在两条分支 |
| AC-REQ-007-03 | V-AC-REQ-007-03 | automated operation regression | `copy_file` 快照通过后调用 `copy_normal`，并运行完整定向回归 |

### REQ-008: 版本链目标未解析报告保留诊断上下文
作为迁移脚本执行者，我需要版本链因目标无法唯一解析而跳过时仍能看到分类和具体底层原因，以便直接修复公共空间、目录或 owner 配置。

#### 验收标准 Acceptance Criteria
- `AC-REQ-008-01`: WHEN 版本链分类有效且成员分类一致，但目标无法解析 THEN 每个跳过结果 SHALL 保留一级、二级分类 code 和 label。
- `AC-REQ-008-02`: WHEN 目标解析失败 THEN `reason_code` SHALL 保持 `version_chain_target_unresolved` 兼容值，`error` SHALL 包含底层 route reason code 和说明。
- `AC-REQ-008-03`: WHEN 版本链成员分类一致 THEN 脚本 SHALL 只解析一次目标，且选中、跳过和来源保留行为不得改变。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-008-01 | V-AC-REQ-008-01 | automated planner regression | 目标目录未命中版本链的 skipped category 字段断言 |
| AC-REQ-008-02 | V-AC-REQ-008-02 | automated planner/report regression | 稳定 chain reason code 与底层 route detail 断言 |
| AC-REQ-008-03 | V-AC-REQ-008-03 | automated planner regression | 统一分类只调用一次 target resolver，并运行完整定向回归 |

### REQ-009: 目标名称匹配忽略已知零宽格式字符
作为迁移脚本执行者，我需要分类 label 与目标空间或目录名称比较时忽略不可见的零宽空格和 BOM，以便界面显示相同的名称能够稳定路由，同时不扩大到模糊匹配。

#### 验收标准 Acceptance Criteria
- `AC-REQ-009-01`: WHEN 目标空间或根目录名称包含 `U+200B` 或 `U+FEFF` THEN 名称索引 SHALL 删除这些格式字符后再执行既有唯一精确匹配。
- `AC-REQ-009-02`: WHEN 名称只包含普通首尾空白或不含已知格式字符 THEN 既有 `.strip()` 和区分其他字符的精确匹配语义 SHALL 保持不变。
- `AC-REQ-009-03`: WHEN 线上8个公共空间名称末尾的 `U+200B` 被事务性清理并重新 dry-run THEN `target_space_not_found` SHALL 为0，且 dry-run SHALL 不移动或删除来源文件。
- `AC-REQ-009-04`: WHEN 修复后仍存在批内 MD5 或名称冲突 THEN 脚本 SHALL 继续按既有安全规则跳过，并输出可核对的冲突文件清单。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-009-01 | V-AC-REQ-009-01 | automated resolver regression | 空间和目录名称分别包含 `U+200B`、`U+FEFF` 时仍唯一命中 |
| AC-REQ-009-02 | V-AC-REQ-009-02 | automated normalization regression | 普通空白继续去除，其他可见字符不被模糊化 |
| AC-REQ-009-03 | V-AC-REQ-009-03 | production read-only dry-run | 线上名称事务更新前后快照、`dry_run_selected` 与目标未命中计数 |
| AC-REQ-009-04 | V-AC-REQ-009-04 | report analysis | `batch_md5_conflict` 和 `batch_name_conflict` 逐项清单及占用关系 |

### REQ-010: 目标标签严格复现来源快照
作为迁移脚本执行者，我需要目标文件的已通过和待审核标签严格等于复制前保存的来源快照，以便标签校验不会因为二次查询或增量写入产生不一致。

#### 验收标准 Acceptance Criteria
- `AC-REQ-010-01`: WHEN 来源文件已完成 `SourceSnapshot` THEN 标签复制 SHALL 以该快照作为唯一数据来源，并精确替换目标文件的已通过和待审核标签。
- `AC-REQ-010-02`: WHEN 标签复制开始 THEN 脚本 SHALL 不重新查询来源文件标签，也不得依赖仅追加缺失标签的增量语义。
- `AC-REQ-010-03`: IF 目标标签校验仍不一致 THEN 错误 SHALL 同时包含来源和目标的已通过、待审核标签 ID，且现有补偿流程 SHALL 保留来源并清理目标残留。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-010-01 | V-AC-REQ-010-01 | automated operation regression | `copy_tags()` 使用已缓存 `TagSnapshot` 精确写入目标标签 |
| AC-REQ-010-02 | V-AC-REQ-010-02 | automated interaction test | 断言不再调用重新查询来源标签的 `_copy_file_tags()` 路径 |
| AC-REQ-010-03 | V-AC-REQ-010-03 | automated verification/failure-path test | 标签不一致错误包含双方 ID，既有 Saga 补偿测试保持通过 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 不新增第三方依赖，不修改数据库 schema。
- `NFR-002`: 预检阶段批量加载空间、文件、版本关系和目标目录，避免逐文件数据库查询。
- `NFR-003`: 路由和冲突决策必须由显式排序决定，不依赖数据库自然顺序。
- `NFR-004`: 默认模式必须保持无业务写入；报告目录写入是唯一允许的 dry-run 文件系统副作用。
- `NFR-005`: 脚本继续兼容项目 Python 3.10、MySQL 和 DM8 ORM 语义。
- `NFR-006`: 不触碰当前工作区与本功能无关的用户改动。
- `NFR-007`: 缺陷修复不得改变路由、冲突、版本链、权限或来源删除语义，不新增依赖。
- `NFR-008`: 报告修复保持现有 JSON 字段和 `version_chain_target_unresolved` 原因码兼容。
- `NFR-009`: 零宽字符修复不得引入 Unicode 同义词、繁简、大小写或包含匹配；线上名称清理必须限定为已核验的8个空间 ID 并在单事务中提交。
- `NFR-010`: 标签修复不得修改在线审批发布流程、标签表结构或源文件标签；仅调整迁移脚本目标标签写入与诊断。

## 澄清记录 Clarifications

### Session 2026-07-17
- Q: 名称匹配使用 label 还是 code？ -> A: 使用分类 `label` 精确匹配。
- Q: 二级目录匹配范围？ -> A: 只匹配目标空间根目录直属文件夹。
- Q: 移动后文件所有者？ -> A: 改为目标公共知识空间所有者。
- Q: 文件状态与版本？ -> A: 仅 `SUCCESS`，但包括版本链文件。
- Q: 重复规则？ -> A: 目标目录同名或目标空间任意位置相同 MD5 均跳过。
- Q: 租户规则？ -> A: 当前系统未启用多租户，不增加租户区分。
- Q: 版本链策略？ -> A: 完整保留；链内分类及目标一致才整体移动，否则整链跳过。
- Q: 标签规则？ -> A: 当前无租户隔离，沿用现有标签迁移逻辑。
- Q: 缺少二级分类？ -> A: 跳过，一级和二级必须同时存在。
- Q: 版本链部分位于来源范围？ -> A: 整条链跳过，不扩大来源范围。
- Q: 向量模型不一致？ -> A: 跳过文件或整条版本链。
- Bug evidence: 真实 apply 中 3 个普通文件在来源工件快照阶段报 `AttributeError: type object 'KnowledgeUtils' has no attribute 'get_minio_client'`，均未创建目标文件；修复范围限定为 MinIO 客户端入口及对应回归测试。
- Bug evidence: 文档 6307 因目标未解析跳过，但 JSON 中四个分类字段为空且 `error` 只包含泛化说明；代码证明分类已解析成功，丢失发生在 `skip_known()` 未传 category 且 route reason 被折叠。
- Bug evidence: 线上报告 `knowledge-file-move-20260717-183747-91a775b8.json` 中2110条有效分类均为 `target_space_not_found`；公共空间3888、3889、3890、3891、3894、3895、3896、3897的名称末尾实际包含 `U+200B`，而 `_normalize_label()` 仅调用 `.strip()`。进程内忽略 `U+200B` 后2089个文件立即进入迁移计划。
- Bug evidence: 真实 apply 中来源文件89515、89516完成数据库、MinIO、Milvus、Elasticsearch和权限复制后，在目标标签校验时报 `target file tags do not match the source file`；补偿删除目标94994、94995并保留来源。只读查询确认两个来源均有有效已通过标签3298、无待审核标签。代码同时存在“快照读取”和“复制时二次查询+增量添加”两套标签来源，无法保证严格校验的一致性。

## 假设 Assumptions
- 名称匹配去除普通首尾空白、`U+200B` 和 `U+FEFF` 后区分其他字符；中文 label 不做同义词、全半角或繁简转换。
- 同名空间或根目录同名文件夹无法唯一确定目标，按“未匹配”同类安全规则跳过。
- 目标空间所有者取 `Knowledge.user_id` 对应的有效用户；不存在时不猜测其他管理员。
- 同一版本链内部允许历史版本文件名重复；冲突检查针对目标既有文件和其他迁移单元，不把链内成员互相视为冲突。

## 风险 Risks
- `--apply` 会删除来源记录并生成新文件 ID，收藏、分享链接和外部引用会中断。
- MySQL、MinIO、Milvus、Elasticsearch 与 OpenFGA 不支持统一事务；版本链采用复制、验证、提交、补偿的 Saga，持续依赖故障仍可能留下需人工处理的残留。
- 旧 CLI 的显式来源筛选和目标参数将被移除，属于不向后兼容的运维接口变化。
- 真实依赖完整性只能在提供业务空间 ID 和可访问中间件的环境中通过 dry-run/apply 演练确认；本任务默认不执行真实 apply。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
