# Tasks: F051-部门子树与用户物理清理运维脚本

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 已确认硬删除、资产转移、历史数据保留与受保护节点策略。 |
| tasks.md | ✅ 已评审 | 需求、验收、任务与验证映射完整。 |
| 实现 | ✅ 已完成 | 5 / 5 完成；真实 `--apply` 留给维护窗口人工执行。 |

---

## 开发模式

- 后端 Test-First：核心计划与执行逻辑先用 mock 隔离 MySQL、OpenFGA、资产转移服务，再实现最小脚本。
- 双库约束：部门树遍历使用 ORM 的 `parent_id` 批量读取与应用层遍历，不引入递归 SQL、方言专有函数或 Schema 变更。
- 安全约束：测试不得传入真实 `--apply`，任何测试中的外部写入均使用 mock；脚本默认 dry-run。
- 范围约束：仅新增运维脚本、包装器、测试与 README，不修改现有业务服务、接口、数据库结构或组织同步逻辑。

---

## Tasks

### 阶段 1：测试与预检计划

- [x] **T001**: 建立部门子树清理脚本的单元测试骨架
  _Requirements: REQ-001, REQ-002, REQ-005_
  _Acceptance: AC-01, AC-02, AC-04, AC-05_
  _Verification: V-001_
  _Boundary: 仅新增 `src/backend/test/department/test_purge_department_subtree_script.py`，所有数据库、OpenFGA 和资产转移调用必须 mock。_
  **逻辑**：为子树解析、用户去重、dry-run 无副作用、`BS@guest`、`is_tenant_root`、接收人不存在/在删除集合中、外部同步用户与树外成员关系、Linsight 依赖删除建立失败测试。
  **依赖**：无。

- [x] **T002**: 实现 dry-run 计划构建与完整预检
  _Requirements: REQ-001, REQ-002, REQ-005_
  _Acceptance: AC-01, AC-02, AC-04_
  _Verification: V-001, V-002_
  _Boundary: 仅新增 `src/backend/scripts/purge_department_subtree.py` 的计划模型、参数校验、子树遍历和只读预检路径；不得写入数据库或 OpenFGA。_
  **逻辑**：用 `argparse` 接收 `--dept-id`、`--transfer-to-user-id`、`--apply`；在 `bypass_tenant_filter()` 下按 `parent_id` 收集子树，按 `user_id` 去重成员，校验受保护节点与接收人，输出稳定的影响摘要和阻塞原因。
  **依赖**：T001。

### 阶段 2：受控执行路径

- [x] **T003**: 增加资产转移与用户/部门物理清理执行逻辑
  _Requirements: REQ-002, REQ-003, REQ-004, REQ-005_
  _Acceptance: AC-02, AC-03, AC-05, AC-06_
  _Verification: V-001, V-003_
  _Boundary: 仅修改 `src/backend/scripts/purge_department_subtree.py` 与 T001 测试；复用 `ResourceOwnershipService`、`DepartmentChangeHandler`、`PermissionService`，不修改它们的生产实现。_
  **逻辑**：按用户/租户/资源类型、每批最多 500 项转移已注册资源；任一转移失败停止后续删除。随后删除 Linsight 三张用户外键表，再清理已确认的账号关系和部门作用域关联，按叶到根删除部门，并以 `crash_safe=True` 写入 OpenFGA 清理操作、报告待补偿状态。
  **依赖**：T002。

### 阶段 3：可运行性与运维交付

- [x] **T004**: 添加 shell 包装器与运维文档
  _Requirements: REQ-001, REQ-005_
  _Acceptance: AC-01, AC-03_
  _Verification: V-004_
  _Boundary: 仅新增 `src/backend/scripts/purge_department_subtree.sh`，并修改 `src/backend/scripts/README.md`。_
  **逻辑**：包装器按脚本目录约定选择解释器、设置 `PYTHONPATH` 并原样转发参数；README 记录 dry-run、`--apply`、接收用户参数、不可逆风险、外部同步重建提示和维护窗口建议。
  **依赖**：T003。

### 阶段 4：验证与交付记录

- [x] **T005**: 运行定向验证并记录结果
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06_
  _Verification: V-001, V-002, V-003, V-004_
  _Boundary: 只运行测试、格式化和 CLI `--help`；不得使用真实数据库、OpenFGA、外部同步源或真实 `--apply`。_
  **逻辑**：执行定向 pytest、Ruff format/check、`--help`；将实际命令与结果写入最终完成报告，并标明真实环境验证缺口。
  **依赖**：T004。

---

## Verification Map

| ID | 方法 | 覆盖 |
|----|------|------|
| V-001 | `uv run pytest test/department/test_purge_department_subtree_script.py` | dry-run、预检、删除顺序、资产失败、OpenFGA 补偿报告。 |
| V-002 | 定向测试中的 mock 断言 | 不带 `--apply` 时没有数据库、Redis 或 OpenFGA 写入。 |
| V-003 | 定向测试中的调用断言 | 资产按批转移、失败阻断、账号关联与部门叶到根清理、`crash_safe=True`。 |
| V-004 | `uv run ruff format --check ...`、`uv run ruff check ...`、`python scripts/purge_department_subtree.py --help` | 格式、静态检查与 CLI 可发现性。 |

---

## 实际偏差记录

- 当前分支为 `feat/2.5.0-sg`，且工作区存在与本特性无关的未提交改动。实现阶段不会修改或覆盖这些文件；是否创建/切换特性分支须在不影响该脏工作区的前提下单独处理。
- 规格确认后发现 Linsight 三张表的非空用户外键会阻断用户物理删除；执行人确认改为删除 `linsight_session_version`、`linsight_sop`、`linsight_sop_record`，已同步更新 `spec.md` 与 T001/T003。
- 已创建 `codex/v2.6.0/051-purge-department-subtree` 分支，原有脏工作区文件保持不变。
