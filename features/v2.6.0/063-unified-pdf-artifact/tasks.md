# 任务拆分 Tasks：知识文件统一 PDF 产物

## 阅读摘要

- 本文档用于按 SDD 实现 F063，默认执行全部未完成任务。
- 实现只建立统一 PDF 产物，不切换下载或预览，不处理历史回填。
- 行为任务优先增加失败测试，再提交最小实现；每项完成必须有新鲜验证证据。
- 浏览器与 Office 转换处理不可信文件，必须执行脚本、网络、文件访问、密钥和资源隔离验证。

## 元信息 Metadata

- Feature ID: `063-unified-pdf-artifact`
- Status: `completed / manual deployment verification pending`
- Related requirements: `features/v2.6.0/063-unified-pdf-artifact/requirements.md`
- Related design: `features/v2.6.0/063-unified-pdf-artifact/design.md`
- Created: `2026-07-20`
- Updated: `2026-07-21`

## 阶段 1：数据与状态基础 Foundation

- [x] T001 为 Artifact 模型、迁移、租户注册和配置编写失败测试
  - Done when: 测试覆盖独立表、三种来源、零历史回填、外键级联、租户模型注册和配置默认值，并在实现前按预期失败。
  - _Requirements: REQ-002, REQ-003, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-04, AC-REQ-003-04, AC-REQ-007-04_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-04, V-AC-REQ-003-04, V-AC-REQ-007-04_
  - _Depends: none_
  - _Boundary: tests only_

- [x] T002 实现 Artifact 模型、MySQL/DM8 迁移、租户注册和配置
  - Done when: `knowledge_file_pdf_artifact`、枚举、索引、外键、配置模型及 `initdb_config.yaml` 已落地，迁移不读取或回填历史 `KnowledgeFile`。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-04, AC-REQ-003-04, AC-REQ-007-04_
  - _Verification: T001 tests + migration source review_
  - _Depends: T001_
  - _Boundary: model, migration, tenant filter and Knowledge config only_

- [x] T003 为 Repository 条件状态机编写失败测试
  - Done when: 测试覆盖 request/claim/retry/complete/fail、可用引用读取、同代 first-success-wins、跨 generation 晚到写入和 `KnowledgeFile.update_time` 不变。
  - _Requirements: REQ-002, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-03, AC-REQ-004-02, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03_
  - _Verification: V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-004-02, V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03_
  - _Depends: T002_
  - _Boundary: repository tests only_

- [x] T004 实现同步/异步 Repository 与 generation 条件状态机
  - Done when: 所有条件写入显式包含 `tenant_id + knowledge_file_id + generation`，重复成功、晚到失败和过期代次均幂等终止。
  - _Requirements: REQ-002, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-04, AC-REQ-004-02, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03_
  - _Verification: T003 tests_
  - _Depends: T003_
  - _Boundary: Artifact repository only_

## 阶段 2：PDF 校验与转换 Core Conversion

- [x] T005 为统一校验器和全格式转换器编写失败测试
  - Done when: 14 种扩展名、原始 PDF、预览回退、Office、Text/Web、图片、损坏/加密 PDF、临时目录和恶意 HTML 均有自动测试或明确 slow/manual 标记。
  - _Requirements: REQ-001, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-001-06, AC-REQ-006-04, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-05_
  - _Verification: V-AC-REQ-001-01..06, V-AC-REQ-006-04, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-05_
  - _Depends: none_
  - _Boundary: converter and validator tests only_

- [x] T006 实现校验器、转换器注册表和受限转换运行时
  - Done when: PDF 输出统一校验；Office 使用 LibreOffice，TXT/Markdown/HTML 使用禁用脚本并阻断外部资源的 Playwright，图片保持方向和比例；临时文件和子进程均受控清理。
  - _Requirements: REQ-001, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-001-06, AC-REQ-006-04, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-05, AC-REQ-007-06_
  - _Verification: T005 tests + representative real conversion smoke_
  - _Depends: T005_
  - _Boundary: `bisheng/knowledge/pdf/` only_

## 阶段 3：调度与 Worker Artifact Lifecycle

- [x] T007 为 Artifact Service 调度、过滤、发布失败和删除快照编写失败测试
  - Done when: 测试覆盖新 generation、固定路径先失效、目录/引用/缺对象跳过、显式 tenant header、发布失败独立落库以及批量删除快照。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-05, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-007-04, AC-REQ-007-05_
  - _Verification: V-AC-REQ-003-02, V-AC-REQ-003-05, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-007-04, V-AC-REQ-007-05_
  - _Depends: T004_
  - _Boundary: Artifact service tests only_

- [x] T008 实现 Artifact Service 的 generation、投递和所有权感知清理
  - Done when: 同步/异步入口复用统一规则，显式投递 `knowledge_pdf_celery`，发布失败不影响主流程，并能在父记录删除前生成来源快照。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-05, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-06, AC-REQ-007-04, AC-REQ-007-05_
  - _Verification: T007 tests_
  - _Depends: T007_
  - _Boundary: `knowledge_pdf_artifact_service.py` only_

- [x] T009 为 PDF Celery Worker 编写失败测试
  - Done when: 测试覆盖 ORIGINAL、PARSE_PREVIEW、GENERATED、预览 provenance、自动重试、并发提交、过期任务、候选回收、租户隔离和日志脱敏。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-001-02, AC-REQ-001-06, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-04, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-007-04, AC-REQ-007-05_
  - _Verification: V-AC-REQ-001-02, V-AC-REQ-001-06, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-04, V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-05, V-AC-REQ-005-06, V-AC-REQ-007-04, V-AC-REQ-007-05_
  - _Depends: T006, T008_
  - _Boundary: PDF Worker tests only_

- [x] T010 实现并注册 PDF Celery Worker
  - Done when: Worker 按候选优先级处理、生成 attempt 路径、条件提交、自动重试和回收，且不修改知识解析状态。
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-06, AC-REQ-002-02, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-04, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-007-04, AC-REQ-007-05_
  - _Verification: T009 tests_
  - _Depends: T009_
  - _Boundary: PDF task and Worker registration only_

## 阶段 4：业务链路集成 Integration

- [x] T011 为上传、解析完成、覆盖、重解析、复制和预览 provenance 编写失败测试
  - Done when: 测试覆盖同步/异步解析成功与失败、无解析直投、普通覆盖新 MD5、Web 覆盖顺序、`copy_normal` 和空间迁移去重。
  - _Requirements: REQ-003, REQ-006_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-006-01_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-05, V-AC-REQ-003-06, V-AC-REQ-006-01_
  - _Depends: T010_
  - _Boundary: trigger and preview regression tests only_

- [x] T012 接入全部上传、解析、覆盖、重解析、复制和迁移入口
  - Done when: 原始对象持久化后建立 generation；解析最终状态后投递；无解析路径直投；固定对象覆盖前失效；预览保存当前源 MD5 provenance。
  - _Requirements: REQ-003, REQ-006_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-05, AC-REQ-003-06, AC-REQ-006-01_
  - _Verification: T011 tests_
  - _Depends: T011_
  - _Boundary: existing Knowledge upload/parse/copy integration points only_

- [x] T013 接入单文件、目录、批量、整库和历史版本删除
  - Done when: 所有入口在删除父记录前取得快照；GENERATED 由 Artifact 删除，ORIGINAL/PARSE_PREVIEW 由既有所有者删除；路径去重且 NotFound 幂等。
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-04, AC-REQ-005-06, AC-REQ-006-01_
  - _Verification: V-AC-REQ-005-04, V-AC-REQ-005-06, V-AC-REQ-006-01_
  - _Depends: T008, T012_
  - _Boundary: existing Knowledge deletion paths and MinIO helper only_

## 阶段 5：部署、安全与兼容 Deployment and Compatibility

- [x] T014 实现独立队列、低并发 Worker 启动能力和转换隔离基线
  - Done when: task 显式路由到 `knowledge_pdf_celery`；两份 entrypoint 支持默认并发 2 的 `pdf` 模式且不加入现有 Worker bundle；项目 Docker Compose 与 `base.Dockerfile` 均保持不变。
  - _Requirements: REQ-004, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-006-04, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-06_
  - _Verification: V-AC-REQ-006-04, V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-06_
  - _Depends: T010_
  - _Boundary: Celery config, entrypoints and backend worker documentation only; Docker Compose and base Dockerfile excluded_

- [x] T015 执行现有下载/API/依赖兼容性回归
  - Done when: 现有单文件和批量下载仍读取原始对象；无新增 Router/API/Beat；前端、`pyproject.toml` 和 `uv.lock` 均无功能性改动。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-REQ-004-05, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: V-AC-REQ-004-05, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04_
  - _Depends: T012, T013, T014_
  - _Boundary: tests and diff/source review only_

## 阶段 6：验证与收尾 Verification and Cleanup

- [x] T016 运行验收验证并创建 `verification.md`
  - Done when: Ruff、目标 Pytest、迁移、Shell、任务路由、真实转换和安全 smoke 均记录命令与结果；每个 AC 标记 PASS、FAIL、MANUAL_REQUIRED 或 NOT_RUN。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01..06, AC-REQ-002-01..04, AC-REQ-003-01..06, AC-REQ-004-01..05, AC-REQ-005-01..06, AC-REQ-006-01..04, AC-REQ-007-01..07_
  - _Verification: verification.md_
  - _Depends: T001..T015_
  - _Boundary: verification and SDD status updates only_

- [x] T017 修复 `sh entrypoint.sh` 执行 Bash 脚本时的启动语法错误
  - Done when: POSIX shell 调用后端 entrypoint 时先以原参数切换到 Bash；`pipefail`、数组和 `wait -n` 不再被 `/bin/sh` 解析；Dockerfile 与 Compose 保持不变。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-07_
  - _Verification: V-AC-REQ-007-07 + deployment contract regression + shell syntax checks_
  - _Depends: T014_
  - _Boundary: `src/backend/entrypoint.sh`, deployment contract test and F063 SDD records only_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..06 | T005, T006, T009, T010, T016 | V-AC-REQ-001-01..06 |
| REQ-002 | AC-REQ-002-01..04 | T001, T002, T003, T004, T010, T016 | V-AC-REQ-002-01..04 |
| REQ-003 | AC-REQ-003-01..06 | T001, T002, T007, T008, T011, T012, T016 | V-AC-REQ-003-01..06 |
| REQ-004 | AC-REQ-004-01..05 | T002, T003, T004, T007, T008, T009, T010, T014, T015, T016 | V-AC-REQ-004-01..05 |
| REQ-005 | AC-REQ-005-01..06 | T003, T004, T007, T008, T009, T010, T013, T016 | V-AC-REQ-005-01..06 |
| REQ-006 | AC-REQ-006-01..04 | T005, T006, T011, T012, T013, T014, T015, T016 | V-AC-REQ-006-01..04 |
| REQ-007 | AC-REQ-007-01..07 | T001, T002, T005, T006, T007, T008, T009, T010, T014, T016, T017 | V-AC-REQ-007-01..07 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes

- 普通上传重复确认流程当前未把新内容 MD5 持久化，T011/T012 必须以顺序回归覆盖。
- `src/backend/entrypoint.sh` 存在用户未提交重构，T014 只能在当前工作树版本上追加 `pdf` 模式。
- 历史文件保持无 Artifact 记录；第一阶段不实现回填或孤立 attempt 定时扫描。
- Scope Update（2026-07-21）：用户确认不在 `docker/docker-compose.yml` 新增 PDF Worker；独立进程、资源和网络限制改由实际部署环境配置。
- Scope Update（2026-07-21）：用户确认不修改 `src/backend/base.Dockerfile`；复用镜像已有转换依赖，F063 不提供专用非 root 镜像用户。
- Bugfix（2026-07-21）：容器使用 `sh entrypoint.sh` 启动 Bash 脚本，在第 30 行数组初始化处报语法错误；T017 通过脚本自切换 Bash 修复，不修改 Dockerfile 或 Compose。
