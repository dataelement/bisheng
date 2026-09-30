# 任务拆分 Tasks：ETL4LM PDF 图片高清提取

## 元信息 Metadata
- Feature ID: `055-etl4lm-image-quality`
- Status: `completed`
- Related requirements: `features/v2.6.0/055-etl4lm-image-quality/requirements.md`
- Related design: `features/v2.6.0/055-etl4lm-image-quality/design.md`
- Created: `2026-07-15`
- Updated: `2026-07-15`

## 阶段 1：配置与测试基线

- [x] T001 编写 ETL4LM 图片配置测试（先红）
  - Done when: 覆盖默认值、三种策略和非法 DPI/像素边界。
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-04_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-04_
  - _Depends: none_
  - _Boundary: tests only; `test/knowledge/rag/test_etl4lm_image_extraction.py`_

- [x] T002 实现 ETL4LM 图片配置并传递 `retain_images`
  - Done when: T001 全绿；旧配置可加载；ETL4LM Loader 显式获得文件级图片开关。
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-04, AC-REQ-004-05_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-04, V-AC-REQ-004-05_
  - _Depends: T001_
  - _Boundary: `core/config/settings.py`, `knowledge/rag/base_file_pipeline.py`, ETL Loader constructor only_

## 阶段 2：高 DPI 区域渲染

- [x] T003 编写 bbox 校验、区域渲染和像素上限测试（先红）
  - Done when: 覆盖 200 DPI 尺寸、clip 调用、越界/非法 bbox、旋转页和像素上限。
  - _Requirements: REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-006-03_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-006-03_
  - _Depends: T002_
  - _Boundary: tests only; new `test_pdf_image_extractor.py`_

- [x] T004 实现 `PdfImageExtractor` 区域渲染能力
  - Done when: `render_only` 使用 bbox `clip` 输出 PNG，不生成整页中间图；T003 全绿。
  - _Requirements: REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-006-03_
  - _Verification: T003 test suite_
  - _Depends: T003_
  - _Boundary: new `loader/utils/pdf_image_extractor.py`; no Loader integration yet_

## 阶段 3：原图优先匹配

- [x] T005 编写 PDF 内嵌原图匹配测试（先红）
  - Done when: 覆盖 JPEG/PNG 精确匹配、多图、扫描背景、局部框、特殊 element_id、蒙版/不支持格式降级。
  - _Requirements: REQ-001, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-006-02_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-006-02_
  - _Depends: T004_
  - _Boundary: tests only; generated PDF fixtures, no ETL/MinIO dependency_

- [x] T006 实现原图候选匹配和提取
  - Done when: 高置信度候选保存原始字节；不确定候选稳定降级区域渲染；T005 全绿。
  - _Requirements: REQ-001, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-006-02_
  - _Verification: T005 test suite_
  - _Depends: T005_
  - _Boundary: `pdf_image_extractor.py` only_

## 阶段 4：ETL4LM 集成与兼容

- [x] T007 编写 ETL4LM Loader 集成回归测试（先红）
  - Done when: 覆盖三种策略、Markdown URL、bbox 不变、retain_images、请求 payload 不变和异常传播。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-05, AC-REQ-005-03, AC-REQ-006-01_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-05, V-AC-REQ-005-03, V-AC-REQ-006-01_
  - _Depends: T006_
  - _Boundary: tests only; mock ETL HTTP and MinIO bucket name_

- [x] T008 集成 `PdfImageExtractor` 到 `Etl4lmLoader`
  - Done when: 新策略替换正式图片路径，Legacy 可回滚，原始 partitions 不被修改，T007 全绿。
  - _Requirements: REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-05, AC-REQ-005-03, AC-REQ-006-01_
  - _Verification: T007 test suite_
  - _Depends: T007_
  - _Boundary: `knowledge/rag/pipeline/loader/etl4lm.py`; do not edit legacy `api/services/etl4lm_loader.py`_

- [x] T009 增加图片提取结构化日志测试与实现
  - Done when: embedded、rendered、legacy 和 fallback 日志包含规格字段；异常保留 traceback。
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03_
  - _Depends: T008_
  - _Boundary: extractor/ETL Loader logging and tests only_

## 阶段 5：验证与收尾

- [x] T010 运行专项验证并完成 SDD 记录
  - Done when: 专项 pytest、相关知识测试、Ruff、compileall、git diff check 均有新鲜证据；生成 `verification.md` 和 `retrospective.md`。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: all acceptance criteria_
  - _Verification: verification.md_
  - _Depends: T001-T009_
  - _Boundary: verification and F055 docs only_

## 计划验证命令

```bash
cd src/backend
uv run pytest test/knowledge/rag/test_pdf_image_extractor.py -q
uv run pytest test/knowledge/rag/test_etl4lm_image_extraction.py -q
uv run pytest test/knowledge/rag -q
uv run ruff check \
  bisheng/knowledge/rag/pipeline/loader/etl4lm.py \
  bisheng/knowledge/rag/pipeline/loader/utils/pdf_image_extractor.py \
  bisheng/knowledge/rag/base_file_pipeline.py \
  bisheng/core/config/settings.py \
  test/knowledge/rag/test_pdf_image_extractor.py \
  test/knowledge/rag/test_etl4lm_image_extraction.py
uv run python -m compileall \
  bisheng/knowledge/rag/pipeline/loader/etl4lm.py \
  bisheng/knowledge/rag/pipeline/loader/utils/pdf_image_extractor.py
git diff --check
```

## Coverage Matrix

| Requirement | Acceptance Criteria | Tasks |
|---|---|---|
| REQ-001 | AC-REQ-001-01..03 | T005, T006, T010 |
| REQ-002 | AC-REQ-002-01..04 | T003, T004, T010 |
| REQ-003 | AC-REQ-003-01..03 | T003, T004, T007, T008, T010 |
| REQ-004 | AC-REQ-004-01..05 | T001, T002, T007, T008, T010 |
| REQ-005 | AC-REQ-005-01..03 | T007, T008, T009, T010 |
| REQ-006 | AC-REQ-006-01..03 | T003-T008, T010 |

## Task Quality Gate
- [x] 每个任务引用 requirement ID。
- [x] 每个行为任务引用 acceptance IDs。
- [x] 每个 acceptance criterion 至少由一个任务覆盖。
- [x] 每个任务有可观察完成条件。
- [x] 依赖和文件边界明确。
- [x] 用户已确认进入实现（2026-07-15）。

## 实际偏差记录

> 实现阶段如发现 PyMuPDF 版本差异、fixture 限制或匹配规则需要调整，必须在此记录并判断是否先更新规格。

- 原图匹配增加显示矩阵安全检查：旋转、倾斜或镜像图片降级为区域渲染，避免原图字节丢失 PDF 显示变换。
- 非 PDF 的 ETL4LM 输入继续使用 Legacy 图片路径，防止本 PDF Feature 改变 PNG/JPG 解析行为。
- `test/knowledge/rag` 全量回归存在 2 个既有环境失败：MinerU/PaddleOCR 测试硬编码 `/Users/zhangguoqing/.../test1.pdf`。排除这两个与本 Feature 无关的测试文件后其余 37 项 RAG 测试全绿。
- `settings.py` 的全规则 Ruff/arch-guard 会报告既有技术债；本次使用新增文件全规则检查、全部变更文件 E/F/I 检查，并单独记录架构守卫原有密钥警告。
