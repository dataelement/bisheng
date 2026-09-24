# 任务拆分 Tasks: 部门知识空间重复文档清理脚本

## 阅读摘要

- 本文档只规划 F057 运维脚本、对应测试、脚本文档和验证证据。
- 默认 dry-run；开发和自动化验证不得连接生产数据，也不得执行真实环境 `--apply`。
- 实现顺序采用后端 Test-First：先提交预期失败测试，再实现最小行为使其通过。
- 任何超出 `requirements.md` / `design.md` 的行为必须先更新规格并重新确认。
- task metadata、依赖、边界和 Coverage Matrix 是实现范围的权威依据。

## 元信息 Metadata

- Feature ID: `057-department-space-document-dedup`
- Version: `v2.5.0-sg`
- Status: `implemented-manual-verification-required`
- Mode: `spec-then-implement`
- Related requirements: [`requirements.md`](./requirements.md)
- Related design: [`design.md`](./design.md)
- Related project spec: [`spec.md`](./spec.md)
- Related release contract: [`../release-contract.md`](../release-contract.md)
- Created: `2026-07-19`
- Updated: `2026-07-19`

## 状态

| 阶段 | 状态 | 备注 |
|------|------|------|
| requirements.md | ✅ 已确认 | 用户于 2026-07-19 确认 |
| design.md | ✅ 已确认 | 用户于 2026-07-19 确认 |
| spec.md | ✅ 已确认 | 用户于 2026-07-19 确认 |
| tasks.md | ✅ 已确认 | 用户于 2026-07-19 确认并授权创建功能分支 |
| 实现 | ✅ 已完成 | 12 / 12 完成 |
| verification.md | 🟨 自动化通过 | 真实跨存储联调为 MANUAL_REQUIRED |

## 开发与验证约束

- 工作目录固定为 `src/backend/`。
- 脚本必须能直接运行：`python scripts/dedupe_department_space_documents.py`。
- 仅使用现有依赖、模型、Service、Repository/DAO 和基础设施客户端；不得新增数据库迁移、在线 API 或第三方依赖。
- 生产代码限定为一个新脚本，必要的复杂逻辑通过脚本内 dataclass、Protocol 和小函数拆分。
- 测试文件固定为 `test/scripts/test_dedupe_department_space_documents.py`，复用现有脚本测试的 mock/fake 模式，不要求真实数据库或外部服务。
- 所有 destructive backend 必须通过可替换 adapter 注入；dry-run 路径不得构造这些 adapter。
- 真实 MySQL/DM8、Milvus、Elasticsearch、MinIO、OpenFGA 联调标记为 `MANUAL_REQUIRED`，需要独立环境和新的数据执行授权。
- 当前工作区已有的 `portal_config_service.py` 与 `celerybeat-schedule.db` 修改不属于本 Feature，任何任务都不得修改、格式化或暂存它们。
- T001 开始前须获得新的实施确认，并按项目规范创建 `feat/v2.5.0-sg/057-department-space-document-dedup` 功能分支；创建分支时只携带现有工作区状态，不暂存、提交、隐藏或改写上述用户修改。

## 阶段 1：计划层 Test-First

- [x] T001 编写 CLI、安全前置和候选计划测试
  - Files: `src/backend/test/scripts/test_dedupe_department_space_documents.py`
  - Done when: 测试覆盖参数正整数校验、dry-run 默认值、多租户拒绝、scope 分类、发布状态无关、当前/历史/兼容旧文件判定、空 MD5、精确 MD5、多见证去重、损坏版本图、范围过滤和稳定 limit；测试以预期原因失败。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-006, REQ-008, REQ-014_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-07, AC-08, AC-09, AC-10, AC-17_
  - _Verification: V-AC-02, V-AC-03, V-AC-04, V-AC-05, V-AC-07, V-AC-08, V-AC-09, V-AC-10, V-AC-17_
  - _Depends: none_
  - _Boundary: tests only; no application or data writes_

- [x] T002 实现 CLI、内部模型和只读计划构建器
  - Files: `src/backend/scripts/dedupe_department_space_documents.py`
  - Done when: 脚本包含模块说明、backend root bootstrap、`argparse`、退出码常量、只读 dataclass/Protocol、单租户前置检查、批量候选查询、版本图校验、公共 MD5 索引、部门删除单元构建和稳定排序；T001 全部通过。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-006, REQ-008, REQ-014_
  - _Acceptance: AC-02, AC-03, AC-04, AC-05, AC-07, AC-08, AC-09, AC-10, AC-17_
  - _Verification: V-AC-02, V-AC-03, V-AC-04, V-AC-05, V-AC-07, V-AC-08, V-AC-09, V-AC-10, V-AC-17_
  - _Depends: T001_
  - _Boundary: script read path only; no ApplyExecutor and no external delete calls_

## 阶段 2：dry-run 与报告 Test-First

- [x] T003 编写 dry-run、报告与无写入保证测试
  - Files: `src/backend/test/scripts/test_dedupe_department_space_documents.py`
  - Done when: 测试证明默认运行不构造写入 adapter、不打开写事务；报告包含 schema/run ID/参数/空间和跳过统计/删除单元/见证/版本/影响计数，采用稳定顺序和原子替换，并拒绝不可写报告目录及敏感字段。
  - _Requirements: REQ-005, REQ-006, REQ-013, REQ-014_
  - _Acceptance: AC-01, AC-04, AC-09, AC-10_
  - _Verification: V-AC-01, V-AC-04, V-AC-09, V-AC-10_
  - _Depends: T002_
  - _Boundary: tests only; mocked filesystem and adapters_

- [x] T004 实现 dry-run 编排、影响快照和原子 JSON 报告
  - Files: `src/backend/scripts/dedupe_department_space_documents.py`
  - Done when: 无 `--apply` 时只执行只读计划和影响统计；初始/最终报告使用临时文件加 `os.replace` 原子更新；控制台只输出运行 ID、绝对报告路径和计数摘要；T003 全部通过。
  - _Requirements: REQ-005, REQ-006, REQ-013, REQ-014_
  - _Acceptance: AC-01, AC-04, AC-09, AC-10_
  - _Verification: V-AC-01, V-AC-04, V-AC-09, V-AC-10_
  - _Depends: T003_
  - _Boundary: script dry-run/report path only; destructive adapters remain unconstructed_

## 阶段 3：apply 删除编排 Test-First

- [x] T005 编写漂移校验、跨存储删除和关系清理测试
  - Files: `src/backend/test/scripts/test_dedupe_department_space_documents.py`
  - Done when: 测试覆盖逐单元重读、计划 fingerprint 漂移、完整版本链、兼容旧文件、公共不可删除断言、Milvus→ES→MinIO→OpenFGA 顺序、精确 ID 数据库事务、Tag/ReviewTag/ShareLink/相似度候选/推荐投影清理、收藏和审计保留，以及目标残留/公共见证验证；测试以预期原因失败。
  - _Requirements: REQ-007, REQ-008, REQ-009, REQ-010, REQ-015_
  - _Acceptance: AC-06, AC-11, AC-12, AC-13, AC-14, AC-18_
  - _Verification: V-AC-06, V-AC-11, V-AC-12, V-AC-13, V-AC-14, V-AC-18_
  - _Depends: T004_
  - _Boundary: tests only; all infrastructure mocked/faked_

- [x] T006 实现逐单元 ApplyExecutor 和执行后验证
  - Files: `src/backend/scripts/dedupe_department_space_documents.py`
  - Done when: `--apply` 在报告初始落盘后才构造写入 adapter；每单元重新加载和校验；按设计顺序同步清理外部资源；仅以已校验精确 ID 在单事务中清理活动关系、版本图和物理文件；保留收藏/历史；提交后执行派生状态失效和有界验证；T005 全部通过。
  - _Requirements: REQ-007, REQ-008, REQ-009, REQ-010, REQ-015_
  - _Acceptance: AC-06, AC-11, AC-12, AC-13, AC-14, AC-18_
  - _Verification: V-AC-06, V-AC-11, V-AC-12, V-AC-13, V-AC-14, V-AC-18_
  - _Depends: T005_
  - _Boundary: script apply adapter and exact target cleanup only; no product API/model/migration changes_

## 阶段 4：失败、幂等与恢复 Test-First

- [x] T007 编写失败停止、幂等重跑和受限恢复测试
  - Files: `src/backend/test/scripts/test_dedupe_department_space_documents.py`
  - Done when: 测试覆盖外部删除部分失败、数据库回滚、后续单元 pending、已完成单元保留、对象不存在幂等、退出码 4/5、checkpoint 原子更新、`--resume-report` 参数互斥/格式校验，以及主记录已删除时只允许提交后失效和只读验证。
  - _Requirements: REQ-011, REQ-012, REQ-013, REQ-014_
  - _Acceptance: AC-15, AC-16_
  - _Verification: V-AC-15, V-AC-16_
  - _Depends: T006_
  - _Boundary: tests only; recovery report cannot authorize database or external deletion_

- [x] T008 实现失败 checkpoint、幂等语义和受限恢复
  - Files: `src/backend/scripts/dedupe_department_space_documents.py`
  - Done when: 任一单元失败立即停止并标记 completed/failed/pending；数据库元数据存在时按正常路径重校验和幂等重试；主记录已删除时恢复模式只能重试缓存/任务失效及只读验证；非法或被篡改边界的报告拒绝执行；T007 全部通过。
  - _Requirements: REQ-011, REQ-012, REQ-013, REQ-014_
  - _Acceptance: AC-15, AC-16_
  - _Verification: V-AC-15, V-AC-16_
  - _Depends: T007_
  - _Boundary: script failure/recovery path only; no force or skip-validation escape hatch_

## 阶段 5：端到端编排与文档

- [x] T009 补充进程内端到端回归测试
  - Files: `src/backend/test/scripts/test_dedupe_department_space_documents.py`
  - Done when: 使用 fake read/write adapters 从 `parse_args()` 运行到最终报告，覆盖完整 dry-run、完整 apply、漂移跳过、失败停止和恢复路径；公共 witness 快照在所有路径保持不变；测试不连接真实基础设施。
  - _Requirements: REQ-001, REQ-005, REQ-007, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015_
  - _Acceptance: AC-01, AC-11, AC-12, AC-15, AC-16, AC-17, AC-18_
  - _Verification: V-AC-01, V-AC-11, V-AC-12, V-AC-15, V-AC-16, V-AC-17, V-AC-18_
  - _Depends: T008_
  - _Boundary: tests only; in-process fakes, no real data mutation_

- [x] T010 完成 `run()` / `main()` 集成和退出码收敛
  - Files: `src/backend/scripts/dedupe_department_space_documents.py`
  - Done when: CLI 能从 `src/backend/` 直接运行；dry-run/apply/resume 三条路径按设计编排；异常边界映射到 0/2/3/4/5；T009 及此前全部脚本测试通过。
  - _Requirements: REQ-001, REQ-005, REQ-007, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015_
  - _Acceptance: AC-01, AC-11, AC-12, AC-15, AC-16, AC-17, AC-18_
  - _Verification: V-AC-01, V-AC-11, V-AC-12, V-AC-15, V-AC-16, V-AC-17, V-AC-18_
  - _Depends: T009_
  - _Boundary: CLI orchestration only; no behavior beyond confirmed spec_

- [x] T011 更新运维 README
  - Files: `src/backend/scripts/README.md`
  - Done when: README 包含脚本用途、单租户限制、公共/部门/版本/MD5 口径、默认 dry-run、参数表、全量与限定示例、报告字段、恢复限制、退出码、维护窗口建议及 `--apply` 不可逆警告。
  - _Requirements: REQ-005, REQ-006, REQ-011, REQ-012, REQ-013, REQ-014_
  - _Acceptance: AC-01, AC-10, AC-15, AC-16, AC-17_
  - _Verification: V-DOC-01_
  - _Depends: T010_
  - _Boundary: docs only; no command execution and no data mutation_

## 阶段 6：验证与交付

- [x] T012 执行自动化验证并生成 `verification.md`
  - Files: `features/v2.5.0-sg/057-department-space-document-dedup/verification.md`, `features/v2.5.0-sg/057-department-space-document-dedup/tasks.md`
  - Done when: 记录每条命令、退出码和输出摘要；全部 AC 有 PASS/FAIL/MANUAL_REQUIRED 状态；完成 targeted pytest、完整脚本测试目录回归、Ruff format/check、`py_compile`、CLI `--help`、架构守卫和 `git diff --check`；真实基础设施验证明确标记 MANUAL_REQUIRED 且提供操作步骤；仅在有新鲜证据时勾选任务。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18_
  - _Verification: V-AC-01, V-AC-02, V-AC-03, V-AC-04, V-AC-05, V-AC-06, V-AC-07, V-AC-08, V-AC-09, V-AC-10, V-AC-11, V-AC-12, V-AC-13, V-AC-14, V-AC-15, V-AC-16, V-AC-17, V-AC-18, V-DOC-01, V-STATIC-01, V-MANUAL-01_
  - _Depends: T011_
  - _Boundary: verification and SDD status updates only; no real environment apply_

## 验证方法 Verification Methods

| ID | 方法 | 自动化状态 |
|----|------|------------|
| V-AC-01 | dry-run orchestration 测试断言所有写 adapter 构造/调用次数为 0 | 自动化 |
| V-AC-02 | planner 测试覆盖 scope 与发布状态组合 | 自动化 |
| V-AC-03 | planner 测试覆盖当前成功文件 MD5 命中 | 自动化 |
| V-AC-04 | 参数化测试覆盖 null/空白/大小写/SimHash | 自动化 |
| V-AC-05 | 版本 fixture 证明公共历史版本不成为见证 | 自动化 |
| V-AC-06 | apply fake 断言完整版本链的所有物理资源进入删除 | 自动化；真实存储为 V-MANUAL-01 |
| V-AC-07 | 无版本记录 fixture 进入 legacy 删除单元 | 自动化 |
| V-AC-08 | 损坏/跨空间版本图参数化测试断言零写入和 reason code | 自动化 |
| V-AC-09 | 多公共见证 fixture 断言单一 unit 与完整 witnesses | 自动化 |
| V-AC-10 | CLI/filter/limit 测试断言只收窄部门目标 | 自动化 |
| V-AC-11 | 重校验 fixture 修改 scope/status/MD5/版本图后断言 skipped | 自动化 |
| V-AC-12 | fake adapters 断言跨存储和 DB 清理顺序、公共零修改 | 自动化；真实存储为 V-MANUAL-01 |
| V-AC-13 | fake transaction 断言活动关系精确删除 | 自动化 |
| V-AC-14 | fake transaction 断言收藏/审计零删除并进入 impact count | 自动化 |
| V-AC-15 | 故障注入测试断言 fail-fast、pending、退出码 4 和 checkpoint | 自动化 |
| V-AC-16 | 不存在对象、重复运行和受限 resume 参数化测试 | 自动化 |
| V-AC-17 | 多租户开启 fixture 断言退出码 2 且零查询/写入 | 自动化 |
| V-AC-18 | post-check 残留注入测试断言退出码 4 | 自动化；真实存储为 V-MANUAL-01 |
| V-DOC-01 | README 内容检查与人工阅读 | 自动化搜索 + 人工阅读 |
| V-STATIC-01 | Ruff、py_compile、CLI help、arch-guard、diff check | 自动化 |
| V-MANUAL-01 | 隔离的 MySQL/DM8 + Milvus + ES + MinIO + OpenFGA 环境执行 fixture dry-run/apply/重跑，禁止生产 | MANUAL_REQUIRED |

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-17 | T001, T002, T009, T010, T012 | V-AC-17 |
| REQ-002 | AC-02 | T001, T002, T012 | V-AC-02 |
| REQ-003 | AC-03, AC-05, AC-07, AC-08 | T001, T002, T012 | V-AC-03, V-AC-05, V-AC-07, V-AC-08 |
| REQ-004 | AC-03, AC-04, AC-05, AC-09 | T001, T002, T012 | V-AC-03, V-AC-04, V-AC-05, V-AC-09 |
| REQ-005 | AC-01 | T003, T004, T009, T010, T011, T012 | V-AC-01 |
| REQ-006 | AC-10 | T001, T002, T003, T004, T011, T012 | V-AC-10 |
| REQ-007 | AC-08, AC-11 | T005, T006, T009, T010, T012 | V-AC-08, V-AC-11 |
| REQ-008 | AC-06, AC-07 | T001, T002, T005, T006, T012 | V-AC-06, V-AC-07 |
| REQ-009 | AC-06, AC-12 | T005, T006, T012 | V-AC-06, V-AC-12, V-MANUAL-01 |
| REQ-010 | AC-06, AC-12, AC-13, AC-14 | T005, T006, T012 | V-AC-06, V-AC-12, V-AC-13, V-AC-14 |
| REQ-011 | AC-15 | T007, T008, T009, T010, T011, T012 | V-AC-15 |
| REQ-012 | AC-16 | T007, T008, T009, T010, T011, T012 | V-AC-16 |
| REQ-013 | AC-01, AC-04, AC-09, AC-14 | T003, T004, T007, T008, T009, T010, T011, T012 | V-AC-01, V-AC-04, V-AC-09, V-AC-14 |
| REQ-014 | AC-15, AC-17 | T001, T002, T003, T004, T007, T008, T009, T010, T011, T012 | V-AC-15, V-AC-17, V-STATIC-01 |
| REQ-015 | AC-12, AC-18 | T005, T006, T009, T010, T012 | V-AC-12, V-AC-18, V-MANUAL-01 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task and verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside confirmed requirements or design.
- [x] Real destructive integration is explicitly MANUAL_REQUIRED and excluded from implementation authorization.

## 实际偏差记录 Implementation Notes

> 实现期间仅记录已经发生的偏差。若偏差改变范围、行为、安全边界或验收标准，必须先更新规格并重新确认。

- 无范围或行为偏差。安全复核补充了 skipped 恢复终态、外部删除前 scope 校验、数据库事务内公共见证/版本链加锁复核和结构化运行上下文，均属于已确认 REQ-007、REQ-012、REQ-014 的实现细化。
- 当前虚拟环境未安装 `pytest-cov`/`coverage`，未生成覆盖率百分比；详见 `verification.md`。真实基础设施联调保持 `MANUAL_REQUIRED`，未执行真实 `--apply`。
