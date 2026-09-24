# 验证记录 Verification: 按文件分类自动移动到公共知识空间

## 阅读摘要
- 自动化验证覆盖多来源 CLI、分类/目标路由、冲突规划、版本链一致性、Saga 补偿、dry-run、报告、退出码和既有复制底座回归。
- 58 个定向测试、Ruff、Python 编译、架构守卫和差异检查均通过。
- 线上8个公共空间名称已事务性删除 `U+200B`；真实 dry-run 选中2089个文件，`target_space_not_found=0`。
- 真实 apply 已暴露并安全补偿目标标签不一致；本地修复尚未部署重跑，因此完整跨存储迁移仍需人工复验。

## 元信息 Metadata
- Feature ID: `061-classified-public-space-file-move`
- Status: `manual_verify_required`
- Related requirements: `features/v2.6.0/061-classified-public-space-file-move/requirements.md`
- Related tasks: `features/v2.6.0/061-classified-public-space-file-move/tasks.md`
- Created: `2026-07-17`
- Updated: `2026-07-17`

## 验证摘要 Verification Summary
- Overall status: `MANUAL_VERIFY_REQUIRED`
- Status rule: 自动化范围已通过；涉及真实多存储迁移的验收在实际环境演练前保持 `MANUAL_REQUIRED`。
- Completed tasks: `T001-T030`
- Remaining tasks: `无代码任务；真实 apply 继续保持人工授权`
- Blocked tasks: `无`

## 已执行命令 Commands Run
| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `.venv/bin/python -m pytest test/scripts/test_move_knowledge_space_files.py test/test_file_worker_copy_normal.py -q` | 功能、失败路径及既有复制底座回归 | 0 | PASS | `58 passed, 6 warnings`；warning 均来自现有依赖弃用提示 |
| `.venv/bin/ruff check scripts/move_knowledge_space_files.py test/scripts/test_move_knowledge_space_files.py` | 静态检查 | 0 | PASS | `All checks passed!` |
| `.venv/bin/ruff format --check scripts/move_knowledge_space_files.py test/scripts/test_move_knowledge_space_files.py` | 格式检查 | 0 | PASS | `2 files already formatted` |
| `.venv/bin/python -m py_compile scripts/move_knowledge_space_files.py` | Python 语法编译 | 0 | PASS | 无错误输出 |
| `PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py --help` | CLI 导入与参数烟测 | 0 | PASS | 显示可重复 `--source-space-id`、`--report-dir`、`--apply` |
| `bash scripts/arch-guard.sh <changed-python-file>` | 项目架构与敏感信息守卫 | 0 | PASS | 脚本和测试均无守卫输出 |
| `git diff --check` | 补丁空白和冲突标记检查 | 0 | PASS | 无错误输出 |

### REQ-007 缺陷复现与修复证据
| Stage | Command / Evidence | Exit Code | Result |
|---|---|---:|---|
| 线上现象 | apply 报告 `knowledge-file-move-20260717-180856-01b66b36.json`：93073、93074、93076 均报 `KnowledgeUtils.get_minio_client` 不存在，`target_file_id=-` | 4 | FAIL（修复前） |
| RED | `.venv/bin/python -m pytest ...::test_storage_exists_uses_managed_minio_storage ...::test_copy_object_if_present_uses_managed_minio_storage -q` | 1 | `2 failed`，与线上相同 `AttributeError` |
| GREEN | 同上两个 helper 测试并增加 `test_copy_file_sets_target_owner_and_folder_context` | 0 | `3 passed` |
| Final regression | `.venv/bin/python -m pytest test/scripts/test_move_knowledge_space_files.py test/test_file_worker_copy_normal.py -q` | 0 | `51 passed, 6 warnings` |
| Static lookup | `rg -n 'KnowledgeUtils\.get_minio_client|get_minio_storage_sync' scripts/move_knowledge_space_files.py` | 0 | 仅保留统一 import 和两个 `get_minio_storage_sync()` 调用 |

### REQ-008 报告上下文复现与修复证据
| Stage | Command / Evidence | Exit Code | Result |
|---|---|---:|---|
| 真实现象 | document 6307 / file 94685 的 JSON：分类四字段为空，error 仅为泛化目标未解析说明 | 0 | FAIL（修复前报告） |
| RED | `.venv/bin/python -m pytest test/scripts/test_move_knowledge_space_files.py::test_version_chain_target_skip_preserves_category_and_route_failure_detail -q` | 1 | `1 failed`；两个版本触发两次 route resolution，旧实现还会丢失分类/detail |
| GREEN | focused planner tests | 0 | `3 passed` |
| Final regression | 完整定向 pytest | 0 | `52 passed, 6 warnings` |

### REQ-009 零宽字符与线上名称修复证据
| Stage | Command / Evidence | Exit Code | Result |
|---|---|---:|---|
| 线上现象 | 报告 `knowledge-file-move-20260717-183747-91a775b8.json` | 0 | 2110条 `target_space_not_found`；8个目标空间名称末尾均有 `U+200B` |
| RED | focused zero-width resolver tests | 1 | `2 failed, 2 passed`；`U+200B` 和 `U+FEFF` 均报 `target_space_not_found` |
| GREEN | 同上 focused tests | 0 | `4 passed, 6 warnings` |
| Final regression | 完整定向 pytest | 0 | `56 passed, 6 warnings` |
| 生产事务 | Knowledge IDs 3888、3889、3890、3891、3894、3895、3896、3897 | 0 | 提交后8个名称精确等于可见 label，不再含 `U+200B` |
| 真实 dry-run | `knowledge-file-move-20260717-190134-519f34f5.json` | 0 | `dry_run_selected=2089`、分类无效53、MD5冲突20、名称冲突1、`target_space_not_found=0`、`source_deleted=0` |
| 冲突清单 | `knowledge-file-move-20260717-190134-519f34f5-conflicts.json` | 0 | 21条均唯一关联到较早占用单元；未修改冲突文件 |

### REQ-010 目标标签快照一致性修复证据
| Stage | Command / Evidence | Exit Code | Result |
|---|---|---:|---|
| 线上现象 | 真实 apply 日志：来源89515、89516复制到94994、94995后均报 `target file tags do not match the source file` | 4 | FAIL（修复前）；目标已补偿删除、来源保留 |
| 生产只读核对 | 来源89515、89516的标签关联和标签主表联查 | 0 | 两者均为 `approved=[3298]`、`pending=[]`；标签3298有效，名称“行业情报” |
| RED | focused `copy_tags`/`verify_target` tests | 1 | `2 failed, 6 warnings`；旧实现未使用缓存快照，错误无双方标签 ID |
| GREEN | 同上 focused tests | 0 | `2 passed, 6 warnings` |
| Final regression | 完整定向 pytest | 0 | `58 passed, 6 warnings` |
| Static gates | Ruff、format、py_compile、CLI help、arch-guard、`git diff --check` | 0 | 全部 PASS |

冲突占用关系（跳过文件 `->` 较早占用文件）：

- 名称冲突：`94224 -> 93823`。
- MD5 冲突：`94269 -> 93784`、`94270 -> 93756`、`94271 -> 93762`、`94272 -> 93757`、`94273 -> 93751`、`94274 -> 93761`、`94275 -> 93786`、`94278 -> 93755`、`94279 -> 93767`、`94282 -> 93674`、`94283 -> 93675`、`94284 -> 93727`、`94286 -> 93647`、`94287 -> 93691`、`94288 -> 93760`、`94291 -> 93733`、`94292 -> 93800`、`94294 -> 93730`、`94295 -> 93684`、`94296 -> 93668`。

## 验收覆盖 Acceptance Coverage
| Acceptance ID | Requirement | Verification Method | Evidence | Status |
|---|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | V-AC-REQ-001-01 | CLI 去重、planner 稳定顺序测试 | PASS |
| AC-REQ-001-02 | REQ-001 | V-AC-REQ-001-02 | 文件类型/状态过滤测试 | PASS |
| AC-REQ-001-03 | REQ-001 | V-AC-REQ-001-03 | 缺失空间 preflight 与写操作未构造测试 | PASS |
| AC-REQ-002-01 | REQ-002 | V-AC-REQ-002-01 | 父子分类 code-to-label 测试 | PASS |
| AC-REQ-002-02 | REQ-002 | V-AC-REQ-002-02 | 公共空间和直属目录唯一匹配测试 | PASS |
| AC-REQ-002-03 | REQ-002 | V-AC-REQ-002-03 | 缺失、未知、歧义、无 owner 原因码矩阵 | PASS |
| AC-REQ-002-04 | REQ-002 | V-AC-REQ-002-04 | 深层同名目录排除测试 | PASS |
| AC-REQ-003-01 | REQ-003 | V-AC-REQ-003-01 | 目标目录同名冲突测试 | PASS |
| AC-REQ-003-02 | REQ-003 | V-AC-REQ-003-02 | 目标空间 MD5 冲突测试 | PASS |
| AC-REQ-003-03 | REQ-003 | V-AC-REQ-003-03 | 向量模型不一致跳过测试 | PASS |
| AC-REQ-003-04 | REQ-003 | V-AC-REQ-003-04 | 批内冲突稳定预留测试 | PASS |
| AC-REQ-004-01 | REQ-004 | V-AC-REQ-004-01 | document 聚合、版本排序及图完整性测试 | PASS |
| AC-REQ-004-02 | REQ-004 | V-AC-REQ-004-02 | 越界、状态、分类、路由、模型、冲突整链跳过矩阵 | PASS |
| AC-REQ-004-03 | REQ-004 | V-AC-REQ-004-03 | fake Saga 验证映射顺序；真实 ORM 版本图待演练 | fake PASS；真实环境 MANUAL_REQUIRED |
| AC-REQ-004-04 | REQ-004 | V-AC-REQ-004-04 | 复制半成品、标签、权限、目标验证、版本图失败补偿矩阵 | PASS |
| AC-REQ-004-05 | REQ-004 | V-AC-REQ-004-05 | 来源删除失败后恢复版本图/文件测试 | PASS |
| AC-REQ-005-01 | REQ-005 | V-AC-REQ-005-01 | copy operation 目标 owner/updater 与目录上下文测试 | PASS |
| AC-REQ-005-02 | REQ-005 | V-AC-REQ-005-02 | 快照/计数校验代码及 copy worker 回归；真实多存储待演练 | MANUAL_REQUIRED |
| AC-REQ-005-03 | REQ-005 | V-AC-REQ-005-03 | 权限集合精确等于 owner/parent 测试 | PASS |
| AC-REQ-005-04 | REQ-005 | V-AC-REQ-005-04 | 缺失/禁用目标 owner 路由测试 | PASS |
| AC-REQ-006-01 | REQ-006 | V-AC-REQ-006-01 | dry-run 不构造写操作测试 | PASS |
| AC-REQ-006-02 | REQ-006 | V-AC-REQ-006-02 | JSON 版本链追踪字段与汇总测试 | PASS |
| AC-REQ-006-03 | REQ-006 | V-AC-REQ-006-03 | apply 任一失败返回非零测试 | PASS |
| AC-REQ-006-04 | REQ-006 | V-AC-REQ-006-04 | 普通文件验证失败清理目标测试 | PASS |
| AC-REQ-007-01 | REQ-007 | V-AC-REQ-007-01 | helper 直接测试断言 managed storage、bucket 和非空对象检查 | PASS |
| AC-REQ-007-02 | REQ-007 | V-AC-REQ-007-02 | helper 直接测试断言对象存在时复制、不存在时不复制 | PASS |
| AC-REQ-007-03 | REQ-007 | V-AC-REQ-007-03 | RED/GREEN 复现及 copy operation 回归；真实环境待重跑 | automated PASS；真实环境 MANUAL_REQUIRED |
| AC-REQ-008-01 | REQ-008 | V-AC-REQ-008-01 | 目标目录未命中版本链的四个分类字段断言 | PASS |
| AC-REQ-008-02 | REQ-008 | V-AC-REQ-008-02 | chain reason code 兼容及 route code/reason detail 断言 | PASS |
| AC-REQ-008-03 | REQ-008 | V-AC-REQ-008-03 | counting resolver 断言分类一致时仅调用一次 | PASS |
| AC-REQ-009-01 | REQ-009 | V-AC-REQ-009-01 | 空间/目录带 `U+200B` 和 `U+FEFF` 路由回归 | PASS |
| AC-REQ-009-02 | REQ-009 | V-AC-REQ-009-02 | 普通首尾空白和可见字符精确匹配回归 | PASS |
| AC-REQ-009-03 | REQ-009 | V-AC-REQ-009-03 | 生产事务前后断言及17来源空间 dry-run | PASS |
| AC-REQ-009-04 | REQ-009 | V-AC-REQ-009-04 | 21条冲突与唯一占用单元关联断言 | PASS |
| AC-REQ-010-01 | REQ-010 | V-AC-REQ-010-01 | `copy_tags` 断言以缓存 `TagSnapshot` 精确替换目标 | PASS |
| AC-REQ-010-02 | REQ-010 | V-AC-REQ-010-02 | 断言审批私有 `_copy_file_tags` 路径不再调用且 import 已移除 | PASS |
| AC-REQ-010-03 | REQ-010 | V-AC-REQ-010-03 | 标签差异包含双方 approved/pending ID；既有补偿回归通过 | automated PASS；真实环境 MANUAL_REQUIRED |

## 人工验证 Manual Verification
| Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| AC-REQ-004-03 | 在隔离环境准备含至少两个版本的来源逻辑文档，先 dry-run 审核，再授权执行 `--apply`，查询目标 document/version rows | 新文件 ID 与新 document ID 生成；`version_no/is_primary/primary_version_id` 与来源语义一致 | 未执行；未提供业务空间 ID，且本任务明确禁止自动真实 apply | NOT_RUN |
| AC-REQ-005-02 | 对同一迁移样本核对目标 MinIO 原件/转换件/BBox/预览、Milvus/ES 记录数、已通过及待审核标签；确认来源已清理 | 目标各工件与来源快照一致，来源仅在全部验证通过后删除 | 未执行；需要可访问的真实中间件和业务授权 | NOT_RUN |
| AC-REQ-007-03 | 部署修复后重新 dry-run；审核计划无新增异常后，再对原命令执行 apply，重点核对 93073、93074、93076 | 不再出现 `get_minio_client` AttributeError；符合路由条件的文件进入复制/验证流程 | 用户提供真实报告：3 个文件分别迁移到 94914、94915、94916，`success=3, failed=0` | PASS |
| AC-REQ-008-01..02 | 重新 dry-run，查看 document 6307 / file 94685 的 JSON | 分类 code/label 非空，目标可解析时进入候选 | `STD/标准规范`、`STD-V33N/岗位规程与安全`，target `3896/94733`，`dry_run_selected` | PASS |
| AC-REQ-009-03..04 | 事务清理空间名称后对17个来源空间 dry-run，再解析冲突 | 目标空间全部命中，冲突保持安全跳过 | 2089条选中，目标未命中0，21条冲突全部可关联 | PASS |
| AC-REQ-010-03 | 部署更新脚本后先对来源89515、89516对应迁移单元重跑，核对目标标签，再继续批量 apply | 目标标签为3298，校验通过后才删除来源；不再出现标签不一致 | 本地修复未部署，未重跑真实 apply | NOT_RUN |

## 失败与缺口 Failures and Gaps
- 修复后的真实 apply 未执行；修复前 apply 已证明目标补偿成功、来源保留。
- 自动测试使用 fake/mock 验证 Saga 顺序和补偿协议，不能替代真实数据库与多中间件联调。
- 修复前真实 apply 已验证统一客户端缺陷；修复后的真实 apply 尚未执行。日志和 `target_file_id=-` 表明 3 个失败文件在 `copy_normal` 前终止，没有创建目标文件。
- 用户后续提供的真实报告已显示 93073、93074、93076 成功迁移到 94914、94915、94916，汇总 `success=3, failed=0`。
- REQ-009 的代码修复已在本地工作区验证，但未直接覆盖运行中容器脚本；线上当前问题已通过清理异常名称解决，代码加固需走正常部署。
- REQ-010 的代码修复同样仅在本地工作区；运行中容器仍使用“二次查询 + 增量添加”实现，部署前继续执行 apply 会重复失败。
- 测试输出包含 6 条现有依赖弃用 warning，不影响本次测试退出码和断言结果。
- `features/` 被当前仓库 `.gitignore` 忽略；规格文件存在于工作区，但如需纳入提交应由维护者显式处理忽略规则。

## 验证质量门 Verification Quality Gate
- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by fresh evidence.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
