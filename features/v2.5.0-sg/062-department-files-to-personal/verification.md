# F062 验证记录

- Date: `2026-09-09`
- Overall: `MANUAL_VERIFY_REQUIRED`（脚本本地实现与回归已完成，真实迁移未执行）
- Runtime: `src/backend/.venv/bin/python`，Python 3.10.19。
- 代码范围：新增脚本、新增定向测试、README 小节；旧迁移脚本与在线服务未修改。
- 最终脚本 SHA-256：`3f0b5b2024000dac63a3111622355a9fc86416da4513de5f5204c103870f6d26`。
- 最终测试 SHA-256：`62d3d459a9ce3bc3c74098e6c3daa7a0dee233812f90e173bc79ac83e7acc99d`。

## 证据

命令工作目录均为 `src/backend/`，除注明外。E-001 至 E-011 为原冲突跳过版本的历史证据，E-012 至 E-015 为本次覆盖规则更新的最终证据。

| ID | 命令或步骤 | 结果 | 说明 |
|---|---|---|---|
| E-001 | `.venv/bin/python -m pytest test/scripts/test_move_department_files_to_personal.py -q`，实现前 | 退出 2 | 测试先行：新模块不存在，符合预期红灯 |
| E-002 | 相同测试文件，首批预览/规划完成 | 26 passed | 用户归属、部门范围、目录、版本链、目标和批内冲突、只读预览 |
| E-003 | 相同测试文件，执行及主要失败路径完成 | 39 passed | 成功、重跑、复制/权限/验证/删除/事后验证失败、记录落盘失败、源数据变更及个人库创建 |
| E-004 | `.venv/bin/python -m pytest test/scripts/test_move_department_files_to_personal.py test/scripts/test_move_knowledge_space_files.py test/test_file_worker_copy_normal.py test/test_personal_default_space.py test/test_personal_space_create_guard.py -q` | 173 passed, 2 failed | 新增完整目录/版本执行和中断测试；失败为未改动的旧个人库测试 |
| E-005 | `.venv/bin/python -m pytest test/test_personal_default_space.py::test_ensure_personal_default_creates_when_missing test/test_personal_space_create_guard.py::test_user_initiated_personal_create_is_rejected -q --tb=line` | 2 failed | 未导入新测试文件也复现；两项均在旧服务读取数据库时使用 MagicMock database_url，SQLAlchemy 报 ValueError |
| E-006 | E-004 同范围，加 `-k 'not test_ensure_personal_default_creates_when_missing and not test_user_initiated_personal_create_is_rejected' --tb=short` | 173 passed, 2 deselected，退出 0 | 原冲突跳过版本；新文件的全部 44 项测试包含在通过集合中 |
| E-007 | `.venv/bin/ruff check scripts/move_department_files_to_personal.py test/scripts/test_move_department_files_to_personal.py` | PASS | 无 lint 问题 |
| E-008 | `.venv/bin/ruff format --check scripts/move_department_files_to_personal.py test/scripts/test_move_department_files_to_personal.py` | PASS | 两个文件格式一致 |
| E-009 | `.venv/bin/python -m py_compile scripts/move_department_files_to_personal.py` | PASS | Python 语法检查 |
| E-010 | `.venv/bin/python scripts/move_department_files_to_personal.py --help` | PASS | 使用真实导入链，不连接业务数据库执行；参数显示正确 |
| E-011 | 仓库根目录 `git diff --check`，对两个新文件 `git diff --no-index --check /dev/null <file>`，`bash scripts/arch-guard.sh <file>` | PASS | diff 检查、架构守卫无报告 |
| E-012 | 追加规则实现前运行新断言 | 预期失败 | 重复个人库选择 3 项、批次候选保留 1 项复现旧行为不满足需求 |
| E-013 | `.venv/bin/python -m pytest test/scripts/test_move_department_files_to_personal.py -q --tb=short` | 60 passed，退出 0 | 稳定选择默认库、逐个覆盖及最后一份保留、完整旧版本链、受保护目标拒绝、覆盖/删除/日志失败保留副本、复制期间目标变化 |
| E-014 | E-006 相同命令和范围 | 189 passed, 2 deselected，退出 0 | 包含新脚本 60 项；排除项为 E-005 已独立复现的旧测试环境问题 |
| E-015 | 对最终代码执行 E-007 至 E-011 检查（语法检查同时包含测试文件） | PASS | Ruff、格式、编译、真实 `--help` 导入、diff、架构守卫；no-index 对新增文件退出 1 表示存在差异，无空白错误输出 |

## AC 覆盖

| AC | 自动化证据 | 状态与边界 |
|---|---|---|
| AC-01 / AC-02 | E-014 | PASS：纯规划范围、user_id、无效用户与成员拒绝 |
| AC-03 | E-013 / E-014 | PASS：稳定选择 ID 最小默认库、既有创建入口与已有库复用；旧创建入口的 E-005 单列限制 |
| AC-04 / AC-05 | E-013 / E-014 | PASS：目录复用/创建、逐个同名覆盖、完整版本链迁移、保留主版本与版本号 |
| AC-06 | E-014 | PASS：预览编排无资源初始化/执行写入；数据库实际扫描待隔离环境验证 |
| AC-07 / AC-08 | E-013 / E-014 | PASS：内存状态编排、既有底座回归和失败注入；覆盖开始后的新副本保留；跨存储真实一致性 MANUAL_REQUIRED |
| AC-09 | E-014 / E-015 | 本地参数/上下文与静态检查 PASS；MySQL/DM8 真实执行 MANUAL_REQUIRED |
| AC-10 | E-013 / E-014 | PASS：来源和旧目标关系/版本/审批与模型拒绝分支；线上数据分布未验证 |

## 已知限制与人工验证

- 未执行真实数据库扫描或 `--apply`；测试以纯规划、内存状态与外部服务替身验证，不宣称真实 MinIO/Milvus/ES/OpenFGA 迁移完成。
- 2 项旧测试的数据库 mock 缺失已独立复现，未修改旧测试或在线服务来消除该问题。
- macOS 没有 DM8 驱动；双数据库运行实测需 Linux/CI 或隔离环境。
- 在隔离环境准备部门目录、无个人库用户、完整版本链和同名目标，先预览并核对源表零变化，再经授权 apply。验证个人库归属、目录层级、检索/预览/下载、版本链、权限及来源清理，然后重跑确认无重复迁移。
- apply 应在维护窗口串行执行；跨存储无全局事务，强杀或恢复失败可能保留残留，按 JSONL 和 cleanup_errors 核对，不能盲目重跑失败单元。
- 追加覆盖策略会永久删除旧目标及完整版本链，包括本批次前序迁入文件；JSONL 不包含可恢复的完整旧对象备份。覆盖开始后的失败保留新副本，旧目标可能部分删除，需人工核查。

## 实现审阅

- Spec Compliance Findings：未发现本次新增实现超出已确认文件范围。
- Code Quality Findings：未发现阻塞交付的新增问题；新脚本保留恢复失败后的目标副本，不修改底座。
- Coverage / Evidence Gaps：上述真实环境、DM8 与旧测试环境限制仍存在。
- Overall Decision：本地脚本交付完成；不作为生产迁移验收通过的证明。

## 2026-09-10 修复验证（替代旧复制补偿行为）

- 修改前：独立部署、解析失败/超时及模型不同可迁移的 3 个回归用例按预期失败；此前故障注入已复现底座索引清理报错后继续删除对象和记录，以及 ES=58/Milvus=0 时计数不匹配。
- 改为原记录迁移后，部门专项与既有通用迁移底座联合回归 172 项通过（32 条已有依赖/序列化警告，3.87 秒）。随后增加提交响应丢失的权限保护用例，单独通过；总计 173 项不同用例通过。
- 新执行测试使用真实 SQLite 事务，外部 ES/Milvus/OpenFGA/队列以替身注入异常。验证保留文件/文档/版本 ID 与原对象地址、源目录与部门库保留、索引降级、多部门顺序覆盖完整版本链、未登录用户创建个人库及目录、权限/数据库/审计失败保护、空预览零写入、外部引用不漏查、无全文件表扫描。
- 权限边界额外验证：数据库已提交但响应丢失时，不把已迁入个人库的文件恢复为旧部门权限；执行仍报告失败，需按审计核对实际结果。
- 不再让原复制流程的内存替身代表新流程；保留原规划/租户/路径/引用/版本保护测试，将旧复制补偿执行测试替换为上述事务及权限结果测试。
- Ruff check、语法编译、git diff --check 均通过；独立脚本 --help 退出码 0。仅修改部门脚本、其测试、README 和本规格文档，没有修改合并脚本、通用迁移底座或在线服务。
- 未更新容器，未访问真实业务数据库或执行 apply。真实 MySQL/DM8 事务、ES/Milvus 写入、OpenFGA 切换及用户端重新解析仍需隔离环境端到端验证，不把本地替身结果视为部署验收。

## 2026-09-10 容器个人库创建入口兼容修复

- 容器服务源码确认缺少 `ensure_personal_default_space_for_owner`，但存在无参公开入口 `ensure_personal_default_space()`。脚本的 `service_for()` 已绑定上传人身份，改用该入口；保留创建后的归属及 owner 权限校验。
- 先将创建测试限定为容器实际具备的接口，缺失个人库场景复现相同 AttributeError；已有个人库场景通过。修复后部门规划及记录迁移两个测试文件共 54 项通过，28 条依赖/序列化警告；Ruff 与 diff 检查通过。
- 已更新指定容器 `/app/scripts/move_department_files_to_personal.py`；旧文件备份后缀 `.bak-20260910-135757`。新文件 SHA-256 为 `f8f60df90721f4a9f241e54bbff35a927bf62c03e4bcc5fe8b0e036033a53399`，上传及读回一致，语法检查通过，容器 `--help` 退出 0。
- 本次未执行真实个人库创建或迁移；旧版创建入口缺少本地新版并发创建保护，实际执行仍须停写并串行运行。
