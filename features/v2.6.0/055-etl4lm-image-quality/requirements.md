# 需求 Requirements：ETL4LM PDF 图片高清提取

## 元信息 Metadata
- Feature ID: `055-etl4lm-image-quality`
- Status: `confirmed`
- Mode: `spec-then-implement`
- Created: `2026-07-15`
- Updated: `2026-07-15`
- Version: `v2.6.0`

## 背景

当前 `Etl4lmLoader` 在 ETL4LM 返回图片 bbox 后，使用 PyMuPDF 默认倍率渲染完整 PDF 页面，再通过 OpenCV 按 bbox 裁图。默认倍率下 PDF point 与像素近似 1:1，高分辨率内嵌图片会被降采样到页面显示尺寸，导致上传至 MinIO 的图片放大后模糊。

MinIO 上传本身不转换图片；质量损失发生在 ETL4LM bbox 返回后的本地图片生成阶段。

## 范围 Scope

### Includes
- 仅改造当前 RAG Pipeline 使用的 `knowledge/rag/pipeline/loader/etl4lm.py` 图片提取路径。
- 优先匹配并提取 PDF 内嵌原图。
- 原图无法安全匹配时，以可配置 DPI 对 bbox 区域直接渲染。
- 保持 ETL4LM 文本、表格、公式、bbox 和分块语义不变。
- 同时覆盖知识库预解析、正式入库、知识空间解析与重试链路。
- 修正 ETL4LM Loader 未显式接收文件级 `retain_images` 的问题。
- 增加专项单元测试、配置校验和结构化日志。

### Excludes
- 不修改 ETL4LM 服务端或其识别 DPI。
- 不修改 MineRU、PaddleOCR、Word、PPT、Excel、HTML Loader。
- 不修改 MinIO bucket、对象访问策略和上传协议。
- 不修改前端、API contract、数据库表或向量库 schema。
- 不自动重新解析历史文件。
- 不在本 Feature 解决预解析图片重复、图片删除清理、复制迁移等资产生命周期问题。

## Assumptions

- ETL4LM 返回的 PDF bbox 使用 PDF point 坐标；现有代码与 PaddleOCR 坐标归一化说明均依赖此约定。
- ETL4LM 返回的页码沿用当前实现，为从 `0` 开始的索引。
- PDF 内嵌图片只有在显示区域与 ETL bbox 高置信度一一对应时才能直接提取，否则必须降级渲染。

## Requirements

### REQ-001 原图优先提取

系统应在 ETL4LM 返回 `Image` 分区后，检查该页 PDF 内嵌图片。如果唯一候选与 ETL bbox 高置信度匹配、格式可安全展示、无复杂蒙版且像素数不超过上限，应直接提取该图片，保留其原始像素与压缩数据。

#### Acceptance Criteria
- AC-REQ-001-01：单张普通 JPEG/PNG 的显示 bbox 与 ETL bbox 高置信度匹配时，输出图片来源标记为 `embedded`，像素尺寸与 PDF 内嵌图片一致。
- AC-REQ-001-02：多个候选、整页扫描背景、局部 bbox、无 xref、复杂蒙版或不支持格式不得被错误认定为原图匹配。
- AC-REQ-001-03：原图文件名使用 MinIO/URL 安全名称，并保留浏览器可展示的真实扩展名。

#### Verification
- V-AC-REQ-001-01：使用程序生成的内嵌 JPEG/PNG PDF fixture，断言输出尺寸、扩展名、来源类型与提取字节。
- V-AC-REQ-001-02：使用多图、扫描页、局部框和无 xref fixture，断言进入渲染兜底。
- V-AC-REQ-001-03：使用包含特殊字符的 `element_id`，断言输出文件名平铺且 URL 安全。

### REQ-002 高分辨率区域渲染兜底

当原图无法安全提取时，系统应直接渲染 bbox 对应的页面区域，不得先生成完整高分辨率页面。默认目标 DPI 为 `200`，并受单图最大像素限制。

#### Acceptance Criteria
- AC-REQ-002-01：200 DPI 下，普通未旋转页面输出宽高约为 bbox point 宽高的 `200 / 72` 倍，允许取整误差。
- AC-REQ-002-02：渲染只使用 `clip` 区域，不产生整页中间 PNG。
- AC-REQ-002-03：bbox 超出页面时与 `page.rect` 取交集；空、非有限、页码越界等非法输入必须明确失败。
- AC-REQ-002-04：目标像素数超过配置上限时自动降低有效 DPI，输出不得超过上限的合理取整误差。

#### Verification
- V-AC-REQ-002-01：构造固定 bbox PDF，断言输出像素尺寸。
- V-AC-REQ-002-02：mock/spy 页面渲染调用，断言传入 `clip` 且不写整页文件。
- V-AC-REQ-002-03：参数化测试越界 bbox、空 bbox、非法页码和旋转页。
- V-AC-REQ-002-04：设置较小 `image_max_pixels`，断言有效缩放和输出像素数。

### REQ-003 bbox 与文档语义兼容

图片提取不得修改 ETL4LM 原始 bbox、page、indexes、types 及其持久化语义。提高图片分辨率只能作用于图片输出，不得把 bbox 按 DPI 倍率写回 partitions。

#### Acceptance Criteria
- AC-REQ-003-01：解析前后的 ETL bbox 数值完全一致。
- AC-REQ-003-02：`parse_bbox_list()`、chunk bbox 和 `partitions/{file_id}.json` 继续使用 PDF point 坐标。
- AC-REQ-003-03：Markdown 图片 URL 仍指向 `knowledge/images/{knowledge_id}/{document_id}/...`，现有前端无需修改。

#### Verification
- V-AC-REQ-003-01：深拷贝 ETL partitions，执行合并后比较 bbox/page 数值。
- V-AC-REQ-003-02：运行 Loader 到 splitter 的定向测试，断言 chunk bbox 未按 DPI 放大。
- V-AC-REQ-003-03：断言 `build_image_url()` 生成路径契约不变。

### REQ-004 配置与兼容回滚

系统应支持 `legacy`、`render_only`、`original_first` 三种策略，并为 DPI 和最大像素提供带范围校验的配置。旧配置缺少新增字段时必须正常加载。

#### Acceptance Criteria
- AC-REQ-004-01：默认策略为 `original_first`，默认兜底 DPI 为 `200`，默认最大像素为 `16_000_000`。
- AC-REQ-004-02：`legacy` 保持现有默认倍率整页渲染裁图行为，可用于快速回滚。
- AC-REQ-004-03：`render_only` 跳过原图匹配，仅执行高 DPI 区域渲染。
- AC-REQ-004-04：非法策略、DPI 或最大像素在配置解析阶段明确报错。
- AC-REQ-004-05：文件级 `retain_images=0` 时 ETL4LM 不生成、不上传图片。

#### Verification
- V-AC-REQ-004-01：实例化空 `Etl4lmConf` 并断言默认值。
- V-AC-REQ-004-02：legacy 回归测试断言调用原有路径。
- V-AC-REQ-004-03：mock 原图候选并断言 `render_only` 不调用原图提取。
- V-AC-REQ-004-04：Pydantic 参数化校验测试。
- V-AC-REQ-004-05：构造 `FileProcessBase(retain_images=0)`，断言 ETL4LM Loader 与上传 Transformer 均关闭图片处理。

### REQ-005 错误处理与可观测性

图片提取应提供可诊断日志。原图匹配失败属于正常降级；原图与渲染均失败时必须抛出异常，不得生成指向不存在对象的 Markdown URL。

#### Acceptance Criteria
- AC-REQ-005-01：每张成功图片记录 `source_type`、页码、输出尺寸、有效 DPI/匹配 xref 和耗时。
- AC-REQ-005-02：原图不满足条件时记录可枚举的 `fallback_reason` 并继续渲染。
- AC-REQ-005-03：渲染失败时异常向上传播，文件进入现有解析失败路径。

#### Verification
- V-AC-REQ-005-01：捕获测试日志并断言关键字段。
- V-AC-REQ-005-02：参数化不同降级原因并断言日志。
- V-AC-REQ-005-03：mock `get_pixmap` 抛错，断言 Loader 不吞异常。

### REQ-006 性能和资源边界

新实现不得提高 ETL4LM 请求负载；原图成功路径不得渲染页面，兜底路径仅渲染 bbox 区域。实现应避免大文档产生无界内存增长。

#### Acceptance Criteria
- AC-REQ-006-01：发送给 ETL4LM 的请求 payload 与当前实现保持一致。
- AC-REQ-006-02：原图匹配成功时不调用 `page.get_pixmap()`。
- AC-REQ-006-03：兜底渲染的目标像素数受 `image_max_pixels` 控制。

#### Verification
- V-AC-REQ-006-01：Loader HTTP mock 测试比较请求字段。
- V-AC-REQ-006-02：spy `page.get_pixmap()`，断言 embedded 路径零调用。
- V-AC-REQ-006-03：复用 V-AC-REQ-002-04。

## Clarifications

- 用户已确认采用长期混合方案：原图提取优先，高 DPI bbox 渲染兜底。
- 用户已确认 ETL4LM 识别使用原有输入和识别策略，不因图片保存质量提高而增加 ETL4LM 负载。
- 本规格建议默认兜底 DPI 为 200；正式实现前在 SDD 暂停点再次确认。

## Quality Gate
- [x] 每个 requirement 均可观察或测试。
- [x] 每个 acceptance criterion 均有 verification method。
- [x] Includes / Excludes 已明确。
- [x] 不新增数据库、API 或前端契约。
- [x] 用户确认本规格（2026-07-15）。
