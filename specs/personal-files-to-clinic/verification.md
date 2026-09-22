# 验证记录

- Date: 2026-09-22
- Status: VERIFIED（本地脚本交付）；真实环境迁移为 MANUAL_REQUIRED
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
