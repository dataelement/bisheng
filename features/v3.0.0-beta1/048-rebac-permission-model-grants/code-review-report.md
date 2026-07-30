# Code Review Report

**Feature**：F048 ReBAC 权限模型与 Grant 升级
**Review scope**：当前工作区相对 `origin/feat/3.0.0-beta1`
的 F048 文档、后端、两端前端、测试、脚本与 OpenFGA 部署 pin
**Base branch**：`origin/feat/3.0.0-beta1`
（merge-base `b15b330fde4ed5bd72257b12d4010274e51624ee`）
**Changed files**：以当前工作区 F048 scoped diff 为准；未暂存、提交或推送

## Summary

| Dimension | High | Medium | Low | Status |
|---|---:|---:|---:|---|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 1 | PASS_WITH_SCOPE_NOTE |
| Code Style | 0 | 0 | 1 | PASS_WITH_WARNINGS |
| Docs Sync (`design.md`) | 0 | 0 | 0 | PASS |

## Findings

### LOW

- **[Test Coverage / Scope] 真实环境 E2E 未执行。** 本地 394 个 F048 专项、
  913 个变更测试及两端专项/构建均通过，但真实 OpenFGA v1.15.1 的 5 项、
  MySQL/DM8 的 2 项和专用 API E2E 的 6 项均因缺少 disposable 环境而显式跳过。
  正式 BENCH-01 也仍缺 `production_derived=true` 的批准 fixture。用户于 2026-07-30
  明确确认本地不执行 E2E，因此该项不再阻断“功能与迁移脚本开发完成”的结论；
  它仍不能作为生产发布验证证据。

- **[Code Style / Baseline] 存量修改文件仍有 13 条 Ruff `F` 类告警。**
  它们位于本 Feature 未改动的旧代码行（knowledge 端点重复函数名、旧未使用变量、
  workstation 旧未使用 import 等）。本次新增的 127 个 Python 文件已经
  `ruff check` 全绿并全部通过 `ruff format --check`；本次实现引入的告警为 0。

## 7 维审查证据

### 1. Boundary Conditions

- API schema 对 page size、动作、资源类型、版本、idempotency key 和 mutation 数量做边界校验；
  50/51 change、90/91 tuple、BatchCheck 20/50/100 和 ListObjects 结果上限均有合同测试。
- 空 Grant、重复来源、空/未分级动作、无 parent 的 `INHERIT`、归档部门恢复和 cursor 尾页
  均有测试；文件预览无动作、下载只校验 `download`。

### 2. Permission & Auth

- Catalog 端点要求登录且二次限制 platform super admin；Grant/decision 端点统一注入
  `UserPayload`，再通过 business resolver 生成 `VerifiedPermissionTarget`。
- 权限 domain/API 不查询业务资源 ORM；tenant/status/parent 由业务 Service 校验。
- 旧 relation roster、owner transfer、Config 第二 PDP 和旧 check endpoint 已取消注册；
  相关边界/路由/退役测试 45 项通过。

### 3. Concurrency Safety

- Catalog publish、Grant/mode/resource mutation 使用 durable projection operation/tuple ledger、
  version CAS、幂等 checksum、recent marker、`COMMIT_UNKNOWN` reconcile 和 fail-closed。
- 部门手工、SSO/F015、组织 reconcile 的业务状态与 projection operation 在同一 SQL
  事务 bind，commit 后才执行 FGA；归档恢复到相同 parent 仍重建 mirror。
- Alembic 为唯一 head `f048_permission_grants`，revision 仅 DDL；数据迁移 CLI 只有
  `migrate --apply` 与 `verify`，没有预演、清理或回滚子命令。

### 4. Information Leakage

- 新增范围未发现明文 key、私钥、密码或长 token；日志只记录类型、ID、状态、计数和 checksum，
  不记录凭据、主体名称或资源内容。
- 展示名补充失败不改变授权事实；异常已记录，授权判定仍保持 fail-closed/
  higher-consistency。

### 5. Test Coverage

- F048 专项：394 passed / 7 external skips。
- migration coordinator/runtime/verifier/CLI/schema 专项：47 passed；环境门控 DB 合同另为
  2 passed / 2 skipped。
- 本次 backend 变更文件：913 passed / 13 external skips。
- Department + SSO + Org Sync：446 passed。
- Platform：13 files / 57 tests；Client：7 suites / 23 tests；两端生产构建成功。
- 完整 permission：540 passed / 7 skipped / 3 个 F027 既有测试桩失败。
- 真实环境缺口详见 [e2e-test-report.md](./e2e-test-report.md)。

### 6. Code Style

- `scripts/arch-guard.sh`、全部变更 Python `py_compile`、staged/unstaged
  `git diff --check` 通过。
- 新增 Python 127 个文件：Ruff lint/format 全绿。
- 新增 TS/TSX 权限组件均低于 600 行；两端没有组件直连 axios/fetch，也未引入新状态库。
- 审查中修复了新增 observability/display/marker 降级分支静默吞异常的问题。

### 7. Docs Sync

- `spec.md`、`design.md`、`tasks.md`、release contract、constitution 和权限架构文档已同步
  同 Store/单 model、DDL-only + scripts、dashboard、preview/download、业务边界、
  多 owner 与无回滚决策。
- Design §4/§5/修订历史已补 SSO/F015 部门原子 bind 与归档恢复 mirror 的反直觉规则。
- Tasks 共 140 项，已按用户最终范围全部收口；181 个任务目标路径均存在，另 18 个
  缺失路径全部对应明确退役任务，已完成任务无未完成依赖。

## Overall: PASS_WITH_WARNINGS

代码审查未发现 HIGH/MEDIUM 缺陷；功能、DDL 和正式数据迁移/校验脚本开发完成。
真实环境 E2E 未执行，因此本结论**不代表生产部署或发布环境已经验证**。
