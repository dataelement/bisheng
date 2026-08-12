# 任务拆分 Tasks: 专家问答上传资源持久化

## 阅读摘要
- 本计划覆盖问题/回答的图片与附件，按 codec、转正组件、创建/更新、读取、历史修复和 staging 门禁分阶段实现。
- 不得把 `related_docs` 或 opaque attachment ID 当作 MinIO 对象。
- 不修改全局 `tmp-dir` lifecycle，不自动执行生产 apply。

## 元信息 Metadata
- Feature ID: `054-qa-uploaded-asset-persistence`
- Status: `in-progress`
- Related requirements: `specs/054-qa-uploaded-asset-persistence/requirements.md`
- Related design: `specs/054-qa-uploaded-asset-persistence/design.md`
- Created: `2026-08-11`
- Updated: `2026-08-12`

## 阶段 1：回归保护与基础组件

- [x] T001 建立 QA 上传资源生命周期回归测试
  - Done when: 修复前主路径稳定红灯；测试覆盖问题/回答、图片/附件、create/update/read、URL/key/opaque ID、失败补偿和日志脱敏的独立结果。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-02, AC-REQ-003-04, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: EG-001, EG-002, EG-003, EG-004, EG-006_
  - _Depends: none_
  - _Boundary: `test/qa_expert/test_asset_persistence.py`_

- [x] T002 实现 storage object metadata contract
  - Done when: BaseStorage/MinioStorage 可异步读取 object size/content-type，不下载内容、不修改对象；相关 fake storage 可测试。
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-02_
  - _Verification: V-AC-REQ-006-02_
  - _Depends: T001_
  - _Boundary: `core/storage/base.py`, `core/storage/minio/minio_storage.py` metadata only_

- [x] T003 实现字段感知 `QaAssetCodec`
  - Done when: 五个目标字段可分类完整 URL、相对 URL、tmp/permanent key、opaque ID 和 invalid URL；外部 host/bucket/穿越拒绝；序列化保持字段分隔格式。
  - _Requirements: REQ-003, REQ-006_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-04, AC-REQ-006-01, AC-REQ-006-04_
  - _Verification: V-AC-REQ-003-02, V-AC-REQ-003-04, V-AC-REQ-006-01, V-AC-REQ-006-04_
  - _Depends: T001_
  - _Boundary: `qa_expert/domain/asset_service.py` codec/redaction only_

- [x] T004 实现资源验证、转正与 promotion journal
  - Done when: 图片执行数量/metadata/真实格式校验，附件保持现有产品格式策略；tmp 对象复制到确定性 private permanent key；部分失败和重试补偿正确。
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-002-01, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-002-01, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04_
  - _Depends: T002, T003_
  - _Boundary: `qa_expert/domain/asset_service.py` validation/promotion only_

## 阶段 2：创建与更新集成

- [x] T005 集成问题 create/update 资源生命周期
  - Done when: `image_url/file_url/attachments` 在 create/update 中转正；update 仅处理新 tmp 项，保留 permanent key/opaque ID；DB 失败补偿且原行不变；无资源零 I/O。
  - _Requirements: REQ-001, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-04, AC-REQ-004-03, AC-REQ-004-05_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-04, V-AC-REQ-004-03, V-AC-REQ-004-05_
  - _Depends: T004_
  - _Boundary: Question create/update in `qa_expert/domain/services.py` and endpoint tenant context_

- [x] T006 集成回答 create/update 资源生命周期
  - Done when: `images_url/attachments` 在 create/update 中转正；update 显式传递 `images_url`；DB 失败补偿；无资源/opaque ID 路径不触发 copy。
  - _Requirements: REQ-002, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-04, AC-REQ-004-03, AC-REQ-004-05_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-04, V-AC-REQ-004-03, V-AC-REQ-004-05_
  - _Depends: T004_
  - _Boundary: Answer create/update in `qa_expert/domain/services.py` and `qa_expert/api/endpoints.py`_

- [x] T007 补充上传 canonical reference 响应
  - Done when: `/qa_experts/upload` 继续返回 `file_path`，同时返回无 host/query 的 `relative_path`；当前前端不使用新字段时行为不变。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01_
  - _Verification: V-AC-REQ-003-01_
  - _Depends: T003_
  - _Boundary: QA upload endpoint only_

## 阶段 3：读取与 schema

- [x] T008 集成问题和回答全部读取路径的动态签名
  - Done when: question list/detail/create/update 与 answer create/update/list/by-expert 均对 permanent key 生成新 URL；opaque ID 不变；坏 legacy 项隔离；签名不回写 ORM/DB。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-03, V-AC-REQ-003-04_
  - _Depends: T005, T006_
  - _Boundary: QA response mapper/resolver only_

- [x] T009 对齐 request/response schema 与模型字段说明
  - Done when: 所有资源字段在 schema 中显式存在且保持兼容类型/分隔格式；模型描述改为持久化引用语义；尚未部署的 `f083` 扩容三个多值资源字段且不改动 related_docs。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-03, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-03_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-003-03_
  - _Depends: T008_
  - _Boundary: `qa_expert/domain/schemas.py`, QA model descriptions, existing unshipped `f083`_

## 阶段 4：历史修复

- [x] T010 建立双表历史修复脚本测试
  - Done when: 覆盖默认 dry-run、双表五字段分类、copy-before-update、opaque ID 保留、字段级失败保值、batch 和二次运行幂等。
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-006-04_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-006-04_
  - _Depends: T004_
  - _Boundary: `test/scripts/test_migrate_qa_uploaded_assets.py`_

- [x] T011 实现双表 dry-run/apply 历史修复脚本
  - Done when: 脚本支持 table/record/batch/limit 过滤；默认零写；apply 按字段先复制后更新；缺失/非法保留原值；输出脱敏报告；重复运行零重复写。
  - _Requirements: REQ-005, REQ-006_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-006-04_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-04, V-AC-REQ-006-04_
  - _Depends: T010_
  - _Boundary: `scripts/migrate_qa_uploaded_assets.py`; no automatic production apply_

## 阶段 5：预览修复与发布门禁

- [x] T013 修复 QA 对象 MIME 与内联签名
  - Done when: QA 上传透传可信 MIME；octet-stream 图片可按真实内容校验并在转正时修正 MIME；读取签名按受控扩展名设置响应 MIME 和 `inline`，不改变其他模块默认 storage 行为。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02, EG-008_
  - _Depends: T002, T004, T007, T008_
  - _Boundary: QA upload/promotion/signing and optional backward-compatible storage arguments only_

- [x] T014 实现门户 QA 图片与自上传文件站内预览
  - Done when: 问题/回答图片和问题自上传附件点击打开复用 `DocumentPreview` 的弹窗；支持格式按扩展名选择 reader；不支持/失败状态不自动下载且提供显式下载；知识库关联文档链接保持不变。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: V-AC-REQ-007-03, V-AC-REQ-007-04, EG-008_
  - _Depends: T013_
  - _Boundary: portal QA preview util/component/detail page only_

- [x] T015 为 QA 预览接入现有用户水印
  - Done when: QA 预览弹窗使用当前登录用户创建 `PreviewWatermarkProvider`；图片、PDF、DOCX、表格、Markdown、HTML 与文本继续复用现有 reader overlay；未复制或改写系统水印内容、布局和后台配置逻辑。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-05_
  - _Verification: V-AC-REQ-007-05, EG-008_
  - _Depends: T014_
  - _Boundary: portal QA preview modal and its focused regression test only_

- [ ] T012 完成 staging 真实 MinIO/DB 生命周期 smoke
  - Done when: 问题与回答各验证图片/附件 create、update、list、detail；确认 DB 只存 key/ID；删除 tmp 来源后重新读取仍可访问；dry-run 报告可审计；证据写入 verification.md。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-03, AC-REQ-004-05, AC-REQ-005-01, AC-REQ-006-03, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05_
  - _Verification: EG-007_
  - _Depends: T009, T011, T015_
  - _Boundary: staging + `specs/054-qa-uploaded-asset-persistence/verification.md`; production mutations excluded_

- [x] T016 建立 clean ORM resolver 回归测试
  - Done when: 使用实际 Session 提交后的 Question/Answer 复现 `model_copy(deep=True)` 状态缺陷，并断言 resolver 输出与原 ORM 隔离。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02_
  - _Verification: V-AC-REQ-008-01, V-AC-REQ-008-02, EG-009_
  - _Depends: T008_
  - _Boundary: `test/qa_expert/test_asset_persistence.py` resolver regression only_

- [x] T017 修复 Question/Answer 响应对象构造
  - Done when: 两个 resolver 不再调用 ORM `model_copy(deep=True)`，改用纯字段快照构造独立响应对象；原 ORM 永久 key 不变。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02_
  - _Verification: V-AC-REQ-008-01, V-AC-REQ-008-02, EG-009_
  - _Depends: T016_
  - _Boundary: Question/Answer resolver in `qa_expert/domain/services.py` only_

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | T001, T004, T005, T008, T009, T012 | V-AC-REQ-001-01..04 |
| REQ-002 | AC-REQ-002-01..04 | T001, T004, T006, T008, T009, T012 | V-AC-REQ-002-01..04 |
| REQ-003 | AC-REQ-003-01..04 | T001, T003, T007, T008, T009, T012 | V-AC-REQ-003-01..04 |
| REQ-004 | AC-REQ-004-01..05 | T001, T004, T005, T006, T012 | V-AC-REQ-004-01..05 |
| REQ-005 | AC-REQ-005-01..04 | T010, T011, T012 | V-AC-REQ-005-01..04 |
| REQ-006 | AC-REQ-006-01..04 | T001, T002, T003, T004, T010, T011, T012 | V-AC-REQ-006-01..04 |
| REQ-007 | AC-REQ-007-01..05 | T013, T014, T015, T012 | V-AC-REQ-007-01..05, EG-008 |
| REQ-008 | AC-REQ-008-01..02 | T016, T017 | V-AC-REQ-008-01..02, EG-009 |

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] Tasks sharing one behavior or command use a verification batch instead of duplicate verification tasks.
- [x] Test work covers distinct outcomes/risks and does not duplicate the same behavior across test layers.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes
- Scope update：原 T001-T010 的回答图片计划已替换为 T001-T012 的 QA 全资源计划，旧 task IDs 不再有效。
- `attachments` 的 opaque 业务 ID 兼容是强制边界；实现不得把所有字符串无差别解析成对象 URL。
- spec 053 最初负责 `qa_answer.images_url` 扩容；因 `f083` 尚未部署，本 spec 将同一 migration 扩展为三个多值资源字段，不新增 revision 占位。
- 全局 lifecycle 与富文本内嵌 URL 均保留为明确 follow-up，不得在实现时顺手扩大范围。
