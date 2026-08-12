# 验证记录 Verification: 专家问答上传资源持久化

## 阅读摘要
- 代码实现、字段迁移 contract、历史修复脚本和本地模块回归已通过。
- `T001-T011`、`T013-T017` 已完成；`T012` 需要 staging 的真实 MinIO/数据库与浏览器 smoke，当前本机未执行任何 DDL、对象复制或历史数据 apply。
- `f083` 仍直接衔接 `f082_department_short_name`，未为其他分支 revision 占位。

## 元信息 Metadata
- Feature ID: `054-qa-uploaded-asset-persistence`
- Status: `implementation-verified, staging-pending`
- Related requirements: `specs/054-qa-uploaded-asset-persistence/requirements.md`
- Related tasks: `specs/054-qa-uploaded-asset-persistence/tasks.md`
- Code state: `working tree 2026-08-12`
- Created: `2026-08-11`
- Updated: `2026-08-12`

## 验证摘要 Verification Summary
- Overall status: `MANUAL_VERIFY_REQUIRED`
- Completed tasks: `T001-T011, T013-T017`
- Remaining tasks: `T012`
- Blocked tasks: `none`

## 验证证据 Evidence
| Evidence ID | Code State | Command / Step | Purpose | Result |
|---|---|---|---|---|
| E-054-001 | 当前 worktree | `uv run pytest test/qa_expert/test_asset_persistence.py test/scripts/test_migrate_qa_uploaded_assets.py test/qa_expert/test_answer_images_url_migration.py -q` | codec、转正、补偿、MIME/内联签名、上传响应、ORM resolver、历史修复与 migration contract | PASS (`44 passed`) |
| E-054-002 | 当前 worktree | `uv run pytest test/qa_expert/test_answer_images_url_migration.py -q` | 三个多值字段的 MySQL/达梦类型、upgrade/downgrade 与幂等保护 | PASS (`11 passed`) |
| E-054-003 | 当前 worktree | `uv run pytest test/qa_expert test/test_qa_expert_rich_text.py test/test_tenant_storage.py test/test_tenant_storage_listing.py test/scripts/test_migrate_qa_uploaded_assets.py -q` | QA 与受影响存储模块回归 | PASS (`74 passed`) |
| E-054-004 | 当前 worktree | 新增 Python 实现/测试执行完整 `ruff check`；既有风格文件执行 `--select F --ignore F841` | 新增代码完整静态检查；既有文件排除原有未使用变量基线后检查 undefined-name | PASS |
| E-054-005 | 当前 worktree | `python -m compileall -q ...` | 受影响 Python 文件语法检查 | PASS |
| E-054-006 | 当前 worktree | `uv run alembic heads` 与 `uv run alembic history -r f082_department_short_name:f083_qa_answer_images_url_longtext` | migration graph | PASS；唯一 head 为 `f083`，链为 `f082 -> f083` |
| E-054-007 | 当前 worktree | `git diff --check` | diff 空白错误检查 | PASS |
| E-054-008 | staging | 真实 MinIO/DB 生命周期 smoke | 删除 tmp 来源后复读、DB 仅存 key/ID、dry-run 审计 | MANUAL_REQUIRED |
| E-054-009 | 门户当前 worktree | 隔离编译并执行 `tests/qaAssetPreview.test.ts` 与 `tests/previewWatermark.test.ts` | QA reader 映射、显式下载、预览接线及复用当前用户/部门/日期/配置水印 | PASS (`9 passed`) |
| E-054-010 | 门户当前 worktree | `npm run build` | 门户 TypeScript 与生产构建 | PASS；Vite 提示当前 Node 20.13.1 低于建议版本，但构建成功 |
| E-054-011 | 门户当前 worktree | `npx eslint src/components/QaAssetPreviewModal.tsx src/utils/qaAssetPreview.ts tests/qaAssetPreview.test.ts tests/previewWatermark.test.ts` | 本次新增前端模块及复用水印测试静态检查 | PASS |
| E-054-012 | 门户当前 worktree | `npm test -- --test-name-pattern=...` | 项目聚合测试入口 | BLOCKED；被本次范围外既存测试类型错误阻断，新增用例已由 E-054-009 独立验证 |
| E-054-013 | 修复前 worktree | `uv run pytest test/qa_expert/test_asset_persistence.py::test_committed_orm_asset_resolution_has_independent_state -q` | 复现 clean ORM 深拷贝状态缺陷 | EXPECTED_FAIL；Answer 与 Question 两个参数均抛出 `ObjectDereferencedError` |
| E-054-014 | 当前 worktree | 同一 committed ORM 定向回归 | 验证独立响应 state、签名字段与原 ORM 不变 | PASS (`2 passed`) |

## 验收覆盖 Acceptance Coverage
| Acceptance ID | Evidence | Status |
|---|---|---|
| AC-REQ-001-01 | E-054-001 | PASS |
| AC-REQ-001-02 | E-054-001 | PASS |
| AC-REQ-001-03 | E-054-001 | PASS |
| AC-REQ-001-04 | E-054-001 | PASS |
| AC-REQ-002-01 | E-054-001 | PASS |
| AC-REQ-002-02 | E-054-001 | PASS |
| AC-REQ-002-03 | E-054-001 | PASS |
| AC-REQ-002-04 | E-054-001 | PASS |
| AC-REQ-003-01 | E-054-001 | PASS |
| AC-REQ-003-02 | E-054-001 | PASS |
| AC-REQ-003-03 | E-054-001 | PASS |
| AC-REQ-003-04 | E-054-001 | PASS |
| AC-REQ-004-01 | E-054-001 | PASS |
| AC-REQ-004-02 | E-054-001 | PASS |
| AC-REQ-004-03 | E-054-001 | PASS |
| AC-REQ-004-04 | E-054-001 | PASS |
| AC-REQ-004-05 | E-054-001 | PASS |
| AC-REQ-005-01 | E-054-001 | PASS |
| AC-REQ-005-02 | E-054-001 | PASS |
| AC-REQ-005-03 | E-054-001 | PASS |
| AC-REQ-005-04 | E-054-001 | PASS |
| AC-REQ-006-01 | E-054-001 | PASS |
| AC-REQ-006-02 | E-054-001 | PASS |
| AC-REQ-006-03 | E-054-001 | PASS |
| AC-REQ-006-04 | E-054-001 | PASS |
| AC-REQ-007-01 | E-054-001, E-054-003 | PASS |
| AC-REQ-007-02 | E-054-001, E-054-003 | PASS |
| AC-REQ-007-03 | E-054-009, E-054-010 | PASS |
| AC-REQ-007-04 | E-054-009, E-054-010, E-054-008 | MANUAL_VERIFY_REQUIRED |
| AC-REQ-007-05 | E-054-009, E-054-010, E-054-008 | MANUAL_VERIFY_REQUIRED |
| AC-REQ-008-01 | E-054-013, E-054-014, E-054-003 | PASS |
| AC-REQ-008-02 | E-054-014 | PASS |

## staging 手工门禁 Manual Gate
1. 先升级测试库到 `f083_qa_answer_images_url_longtext`，确认三个目标字段为大文本类型。
2. 问题与回答分别上传图片和附件，覆盖 create/update/list/detail，检查 DB 仅保存 `qa-expert/...` key 或 opaque ID。
3. 删除对应 `tmp-dir` 来源，再次读取并访问新签名 URL，确认正式对象不受临时生命周期影响。
4. 先执行 `python scripts/migrate_qa_uploaded_assets.py --table all --tenant-id <tenant> --batch-size 100`，审计 dry-run 聚合结果；备份字段后才允许加 `--apply`。
5. 观察 copy、DB lock、补偿和清理告警；任何字段失败时确认原值保持不变。
6. 在门户详情点击问题/回答图片和 QA 自上传文件，确认站内弹窗、支持格式 reader、不支持格式下载入口与知识库文档原跳转均符合预期；同时核对图片、PDF、DOCX、表格、Markdown、HTML 和文本表面显示当前用户、部门、日期及后台配置水印。

## 已知限制与风险
- 未连接 staging MinIO/数据库，因此真实 SDK、网关签名 URL 和表锁行为仍需 `T012` 验证。
- 历史表没有 `tenant_id` 字段，脚本要求通过 `--tenant-id` 指定目标租户；默认值 `1` 仅适用于根租户数据。
- 本次不修改全局 `tmp-dir` lifecycle，也不处理富文本正文内嵌 URL 和正式对象垃圾回收。
- HTML/SVG 等主动内容的对象响应 MIME 会降级为 `text/plain`；HTML 仅通过站内净化阅读器展示，避免同源对象直链执行脚本。
- `/qa_experts/upload` 路由自身仍未声明登录依赖；本次未在生命周期修复中扩大权限行为，发布前需确认网关/全局中间件已限制匿名上传，否则应单独补充鉴权与限流修复。
- 门户聚合测试入口当前存在本范围外的类型错误；本次新增用例已隔离通过，生产构建也已通过，但应由对应模块后续修复聚合测试基线。
- 当前工作区另有用户自己的 `portal_config_service.py` 与 `celerybeat-schedule.db` 修改，本实现未触碰其业务内容。
