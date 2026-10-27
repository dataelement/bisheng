# Tasks: F112 应用发布说明

**关联规格**：[spec.md](./spec.md) · [design.md](./design.md)
**版本**：v3.0.0；隔离分支 `codex/112-vibe-release-notes`

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户 2026-10-27 确认 |
| design.md | ✅ 已评审 | 用户 2026-10-27 确认 |
| tasks.md | ✅ 已拆解 | 21 项任务清单自审 LGTM |
| 实现 | 代码与本地验证完成 | 28/30；仅本功能定向验证 |

## 任务审查

按 sdd-review tasks 的 21 项自审：AC-01 至 AC-20 均有测试任务；后端测试先于业务实现；任务均不跨两个 SPA；模型/错误/DDL 基础设施优先。每项最多两个手改文件，生成器及 wheel 的机械派生产物明确例外。无 Worker 代码变动，继续使用原 Celery headers → tenant ContextVar 和 deployment_id。无测试降级声明；真实验收未执行不记通过。

## 执行任务

- [x] **T001**（基础设施）：两张模型增加可空 LargeText 字段
  - 文件：`src/backend/bisheng/app_publish/domain/models/app_deployment.py`、`src/backend/bisheng/database/models/app_version.py`
  - 内容：原有对象各增 release_notes；不新增表、索引、通用 UPDATE；代码回滚保留列。
  - 依赖：无

- [x] **T002**（基础设施）：错误码
  - 文件：`src/backend/bisheng/common/errcode/app_publish.py`
  - 内容：核对空闲 16233，增加 AppReleaseNotesInvalidError；不回显正文。
  - 依赖：无

- [x] **T003**（基础设施）：幂等 DDL
  - 文件：`src/backend/bisheng/core/database/alembic/versions/v3_0_0_f112_release_notes.py`
  - 内容：当前 head=vibe_merge_release_20261025；再次以 alembic heads 核对后接入。共享 DDL guards 增加两列；downgrade 丢列，须备份。
  - 依赖：T001

- [x] **T004**（后端 Domain 测试）：说明校验与发布接收测试
  - 文件：`src/backend/test/app_publish/test_release_notes.py`
  - 内容：使用既有 publish_db/tarball/owner fixture；规范化、边界、无副作用、跨 session 保存、旧值为空；先红后绿。
  - 依赖：T001、T002
  - 覆盖 AC: AC-03, AC-04, AC-07, AC-08, AC-11, AC-17

- [x] **T005**（后端 Domain）：规范化及 receive 保存
  - 文件：`src/backend/bisheng/app_publish/domain/release_notes.py`、`src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py`
  - 内容：normalize_release_notes(str|None)；accept 增可选 keyword 参数，创建草稿之前校验；只把 deployment_id 交 Celery，tenant headers→ContextVar 原合同不改。
  - 依赖：T004

- [x] **T006**（后端 API 测试）：发布 API 与能力测试
  - 文件：`src/backend/test/app_publish/test_release_notes_api.py`、`src/backend/test/app_publish/test_deploy_api.py`
  - 内容：现有 api_app 认证 fixture 验证表单透传、16233、能力响应、scope/跨 owner 拒绝；不调用真实编排。
  - 依赖：T005
  - 覆盖 AC: AC-01, AC-07, AC-16, AC-17, AC-18, AC-19

- [x] **T007**（后端 API）：表单与能力声明
  - 文件：`src/backend/bisheng/app_publish/api/endpoints/deploy.py`
  - 内容：POST release_notes 可选；GET limits data 合并 features.release_notes(version=1,max_codepoints=2000)，不改 package_service 整数返回。
  - 依赖：T006

- [x] **T008**（后端 Domain 测试）：冻结、审批及版本测试
  - 文件：`src/backend/test/app_publish/test_release_notes_snapshots.py`
  - 内容：实际 SQLite session 重载后 record_version；既有审批构建器/handler 与版本查询；终态与权限配对；仅已有 fixtures mock 外部基础设施。
  - 依赖：T005
  - 覆盖 AC: AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-19

- [x] **T009**（后端 Domain）：版本写入与查询
  - 文件：`src/backend/bisheng/app_publish/domain/services/version_service.py`、`src/backend/bisheng/app_runtime/domain/services/app_query_service.py`
  - 内容：原 INSERT 复制字段；原授权后序列化版本增加 release_notes；保留先审批后版本与分页合同。
  - 依赖：T008

- [x] **T010**（后端 Domain）：审批两个快照
  - 文件：`src/backend/bisheng/app_publish/domain/services/publish_approval_service.py`、`src/backend/bisheng/app_publish/domain/services/app_publish_scenario_handler.py`
  - 内容：payload 从 deployment 复制；build_detail 白名单透传；回调与审批引擎不变。
  - 依赖：T008

- [x] **T011**（CLI 测试）：输入、兼容与重传测试
  - 文件：`src/bisheng-cli/tests/test_release_notes.py`
  - 内容：复用 PlatformMock 和 sample_project，校验来源/UTF8/长度/dry-run/旧平台/HTTP 失败/原文重传/空白兼容，先红后绿。
  - 依赖：T007
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-17, AC-18

- [x] **T012**（CLI）：解析与参数
  - 文件：`src/bisheng-cli/bisheng_cli/release_notes.py`、`src/bisheng-cli/bisheng_cli/cli.py`
  - 内容：互斥 flag；文件仅读一次，按 cwd；纯 Python 规范化及新增文案三语言字典。
  - 依赖：T011

- [x] **T013**（CLI）：兼容检查及上传
  - 文件：`src/bisheng-cli/bisheng_cli/packaging.py`、`src/bisheng-cli/bisheng_cli/commands/deploy.py`
  - 内容：Limits 默认字段兼容；一次 GET；有说明严格支持，无说明软降级；相同规范化值重传。
  - 依赖：T012

- [x] **T014**（CLI）：错误映射
  - 文件：`src/bisheng-cli/bisheng_cli/errors.py`
  - 内容：16233 映射 exit 6、给出具体修正指引，不把原文写日志。
  - 依赖：T013、T002

- [x] **T015**（基础设施）：共享错误文案 zh/en
  - 文件：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`、`src/frontend/packages/locales/src/api_errors/en.json`
  - 内容：16233 中文/英文文案；原结构不变。
  - 依赖：T002

- [x] **T016**（基础设施）：共享错误文案 ja 及生成
  - 文件：`src/frontend/packages/locales/src/api_errors/ja.json`
  - 内容：补日文并运行 packages/locales 既有生成器；输出是机械派生物，计入本任务，不手改生成文件。
  - 依赖：T015

- [x] **T017**（前端 Platform）：版本类型
  - 文件：`src/frontend/platform/src/controllers/API/hostedApp.ts`
  - 内容：release_notes?: string|null，兼容旧 backend。
  - 依赖：T009

- [x] **T018**（前端 Platform 测试）：两处版本展示测试
  - 文件：`src/frontend/platform/src/pages/BuildPage/hostedApp/publish/VersionListCard.test.tsx`、`src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/VersionsTab.test.tsx`
  - 内容：mock 原 API/翻译，测试各版本全文/空态/纯文本/分页和过期请求隔离；只渲染目标组件。
  - 依赖：T017
  - 覆盖 AC: AC-09, AC-13, AC-14, AC-15

- [x] **T019**（前端 Platform）：两处说明行
  - 文件：`src/frontend/platform/src/pages/BuildPage/hostedApp/publish/VersionListCard.tsx`、`src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/VersionsTab.tsx`
  - 内容：version_id key；追加 colspan 正文行；纯文本、断行、空态；阻止过期请求串应用。
  - 依赖：T018

- [x] **T020**（前端 Platform）：文案 zh/en
  - 文件：`src/frontend/platform/public/locales/zh-Hans/bs.json`、`src/frontend/platform/public/locales/en-US/bs.json`
  - 内容：hostedApp.releaseNotes.title/empty。
  - 依赖：T019

- [x] **T021**（前端 Platform）：文案 ja
  - 文件：`src/frontend/platform/public/locales/ja/bs.json`
  - 内容：与 zh/en 对齐。
  - 依赖：T020

- [x] **T022**（前端 Client 测试）：审批详情全文和空态测试
  - 文件：`src/frontend/client/src/components/approval/AppPublishDetailPanel.test.tsx`
  - 内容：task/instance 共享展示，忽略 payload 值、保留换行、脚本字面值；旧快照空态。
  - 依赖：T010
  - 覆盖 AC: AC-12, AC-14, AC-15, AC-16

- [x] **T023**（前端 Client）：审批说明分区
  - 文件：`src/frontend/client/src/components/approval/AppPublishDetailPanel.tsx`
  - 内容：仅 detail_snapshot.release_notes；既有分区布局加纯文本，不改设计系统或审批逻辑。
  - 依赖：T022

- [x] **T024**（前端 Client）：文案 zh/en
  - 文件：`src/frontend/client/src/locales/zh-Hans/translation.json`、`src/frontend/client/src/locales/en/translation.json`
  - 内容：approval.app_release_notes.title/empty；现有 key 约定。
  - 依赖：T023

- [x] **T025**（前端 Client）：文案 ja
  - 文件：`src/frontend/client/src/locales/ja/translation.json`
  - 内容：与 zh/en 对齐。
  - 依赖：T024

- [x] **T026**（CLI）：安装版本
  - 文件：`src/bisheng-cli/pyproject.toml`、`src/bisheng-cli/bisheng_cli/__init__.py`
  - 内容：同步 3.0.0.post1（若已占用用下一 post 并改 design），不升级依赖；uv.lock 项目版本是机械派生物。
  - 依赖：T014

- [x] **T030**（CLI）：兼容 post 发行参数
  - 文件：`scripts/pack_cli_wheel.sh`
  - 内容：增加可选 CLI_MIN_COMPATIBLE/PLATFORM_VERSION，post 版本默认使用去掉 .post 后缀的发行基线，完整版本默认原行为；本次保留 3.0.0。
  - 依赖：T026

- [x] **T027**（CLI 测试）：安装件构建和 smoke
  - 文件：`src/backend/bisheng/dev_toolkit/artifacts/manifest.json`
  - 内容：运行 pack_cli_wheel.sh，产物新 wheel 替换旧 CLI wheel（机械产物例外）；不变 sdk。fresh shell version/help/dry-run。
  - 依赖：T026、T030
  - 覆盖 AC: AC-20

- [ ] **T028**（E2E 测试）：本功能 E2E 与验收证据
  - 文件：`src/backend/test/e2e/test_e2e_vibe_release_notes.py`、`features/v3.0.0/112-vibe-release-notes/verification.md`
  - 内容：单应用发布→审批→版本；带说明原文、权限拒绝配对；真实运行与 mock 明确区分。手动两端1440/500px。只在已授权范围使用专用测试环境。
  - 依赖：T007、T009、T010、T019、T021、T023、T025、T027
  - 覆盖 AC: AC-08, AC-09, AC-10, AC-12, AC-13, AC-15, AC-16, AC-19, AC-20

- [ ] **T029**（审查）：定向门禁、L1 与 L2
  - 文件：`features/v3.0.0/112-vibe-release-notes/verification.md`、`features/v3.0.0/112-vibe-release-notes/code-review.md`（逐项机械汇总 `task-review.md`）
  - 内容：按 task-review 逐项记 L1；Ruff/arch-guard/迁移单head/i18n/类型及触及组件，完成后 sdd-code-review；不全量跑测试、不擅自推送或部署生产。
  - 依赖：T028

## L1 审查记录

已对 T001–T027、T030 按声明文件逐项核对，检查矩阵见 [L1 审查](./task-review.md)。T028 已有隔离 API 链路、组件浏览器验证及可选真实 E2E 用例，但未执行真实部署；T029 只有合入前预审，不标完成。

## 实际偏差记录

T030：落实兼容发布基线所需的打包参数及 CI 无参数 post 重建默认值 → design §5 坑 11、§7.3；产品口径未变。

## 交付授权补记

2026-10-27 用户明确要求“提交推送 feat/3.0.0 分支，然后再合并到 release 分支并推送远端”。本次据此先交付代码；真实部署 E2E 及依赖其证据的最终审查继续待完成，不标记通过，不执行 116 更新。
