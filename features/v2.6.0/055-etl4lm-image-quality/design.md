# 设计 Design：ETL4LM PDF 图片高清提取

## 元信息 Metadata
- Feature ID: `055-etl4lm-image-quality`
- Status: `confirmed`
- Related requirements: `features/v2.6.0/055-etl4lm-image-quality/requirements.md`
- Created: `2026-07-15`
- Updated: `2026-07-15`

## Goals
- 在不改变 ETL4LM 请求和 bbox 语义的前提下提高 PDF 图片保存质量。
- 对普通内嵌图片直接保留原始像素和压缩数据。
- 对矢量图、扫描页局部、组合图等场景提供 200 DPI 区域渲染兜底。
- 保持现有 Loader → ImageUploadTransformer → Splitter → VectorStore 架构。

## Non-goals
- 不建设通用多解析器图片资产平台。
- 不处理历史图片迁移和 MinIO 孤儿对象。
- 不改变图片匿名访问策略。
- 不改变 Markdown、bbox JSON 或 vector metadata schema。

## 当前架构

`Etl4lmLoader.load()` 将原始文件 base64 发送给 ETL4LM。返回 partitions 后，`extract_images()` 当前执行：

```text
page.get_pixmap() 默认倍率
→ 保存完整页面 PNG
→ cv2.imread()
→ 按 ETL bbox 数组切片
→ cv2.imwrite(element_id.png)
```

随后 `ImageUploadTransformer` 将本地图片原样上传到 MinIO。质量损失发生在默认倍率页面渲染阶段，而不是 MinIO。

## 目标组件

### `PdfImageExtractor`

新增纯后端工具类，封装 PDF bbox 图片生成策略。它不访问 MinIO、不修改 Document、不知道 knowledge/file ID，只负责把一张图片写到 Loader 临时平铺目录。

```python
@dataclass(frozen=True)
class ExtractedImage:
    filename: str
    source_type: Literal["embedded", "rendered", "legacy"]
    width: int
    height: int
    effective_dpi: float | None
    matched_xref: int | None
    fallback_reason: str | None


class PdfImageExtractor:
    def extract(
        self,
        document: fitz.Document,
        page_number: int,
        bbox: Sequence[float],
        element_id: str,
        output_dir: str,
    ) -> ExtractedImage:
        ...
```

### 策略分派

```text
legacy
  → 保持当前整页默认倍率 + OpenCV 裁图

render_only
  → validate bbox
  → calculate scale with max_pixels
  → page.get_pixmap(matrix, clip=bbox)

original_first
  → validate bbox
  → collect page.get_image_info(xrefs=True)
  → score safe candidates
  → unique high-confidence candidate?
      yes → document.extract_image(xref)
      no  → render_only fallback
```

## bbox 归一化

- 输入必须是 4 个有限数字，满足 `x2 > x1`、`y2 > y1`。
- 页码必须在 `[0, document.page_count)`。
- 使用 `clip = fitz.Rect(bbox) & page.rect` 限制在页面内。
- 交集为空或非有限时抛出 `ValueError`，由现有文件解析失败处理捕获。
- 原 bbox 对象和 partitions 不做原地修改。

## 原图候选匹配

### 候选来源

调用 `page.get_image_info(xrefs=True)`，为每个 `xref > 0` 且 bbox 有效的显示实例构造候选。

### 匹配指标

```text
intersection = candidate_bbox ∩ target_bbox
candidate_coverage = intersection.area / candidate_bbox.area
target_coverage = intersection.area / target_bbox.area
center_distance = normalized distance between centers
```

初始高置信度条件：

- `candidate_coverage >= 0.90`
- `target_coverage >= 0.70`
- 候选中心位于 target bbox 内
- 候选原始像素数不超过 `image_max_pixels`
- 只有一个候选达到阈值，或最高分与次高分有明确差距

阈值保持为代码常量并由 fixture 测试约束，暂不暴露为运维配置，避免产生难以验证的组合。

### 安全提取限制

以下情况直接降级区域渲染：

- `xref == 0`
- 图片显示矩阵包含旋转、倾斜或镜像，直接提取会丢失页面显示变换
- 多个候选共同组成 target 区域
- target 仅覆盖整页扫描图的一小部分
- `extract_image()` 返回 soft mask
- 扩展名不在浏览器安全集合 `png/jpg/jpeg/gif/webp/bmp`
- 原始像素数超过上限
- 提取结果为空或尺寸非法

直接提取使用真实扩展名，文件名由安全化后的 `element_id` 与扩展名组成。图片字节不解码、不重编码。

## 区域渲染

目标缩放：

```python
requested_scale = image_fallback_dpi / 72
requested_pixels = bbox.width * requested_scale * bbox.height * requested_scale
effective_scale = min(
    requested_scale,
    sqrt(image_max_pixels / bbox.area),
)
```

然后执行：

```python
page.get_pixmap(
    matrix=fitz.Matrix(effective_scale, effective_scale),
    clip=clip,
    alpha=False,
)
```

输出为 PNG。`effective_dpi = effective_scale * 72` 仅用于日志，不写回 bbox。

## Legacy 回滚路径

`legacy` 策略保留当前整页默认倍率和数组裁剪逻辑。为避免新工具类同时承担两套大型实现，Legacy 方法保留在 `Etl4lmLoader`，新工具只负责 `render_only` 和 `original_first`。待灰度稳定后可在独立 Feature 删除 Legacy。

## 配置设计

在 `Etl4lmConf` 增加：

```python
image_extraction_strategy: Literal[
    "legacy", "render_only", "original_first"
] = "original_first"
image_fallback_dpi: int = Field(default=200, ge=72, le=300)
image_max_pixels: int = Field(default=16_000_000, ge=1_000_000, le=100_000_000)
```

`knowledge_conf.etl4lm.model_dump()` 已自动把新配置传给 Loader。`BaseFilePipeline` 额外显式传递文件级 `retain_images`，确保关闭图片时 Loader 和 Transformer 一致。

ETL4LM 同时可处理 PNG/JPG 等单张图片输入，但本 Feature 的坐标与原图匹配设计仅针对 PDF。非 PDF 输入继续使用 Legacy 图片路径，避免默认策略扩大影响范围。

## 错误处理

- 不满足原图条件：记录 DEBUG/INFO 降级原因，进入区域渲染，不视为错误。
- `extract_image()` 异常：记录 warning 并进入区域渲染。
- 区域渲染异常：记录 exception 并重新抛出，沿用现有文件 FAILED 状态。
- 不允许返回本地不存在的 filename，不生成悬空 Markdown URL。

## 日志

成功日志字段：

```text
act=etl4lm_extract_image
page=<int>
element_id=<safe string>
source_type=embedded|rendered|legacy
matched_xref=<int|null>
width=<int>
height=<int>
effective_dpi=<float|null>
fallback_reason=<enum|null>
duration_ms=<float>
```

## File Structure Plan

### 新增
- `src/backend/bisheng/knowledge/rag/pipeline/loader/utils/pdf_image_extractor.py`：原图匹配与区域渲染。
- `src/backend/test/knowledge/rag/test_pdf_image_extractor.py`：工具类单元测试。
- `src/backend/test/knowledge/rag/test_etl4lm_image_extraction.py`：Loader 集成与兼容测试。

### 修改
- `src/backend/bisheng/knowledge/rag/pipeline/loader/etl4lm.py`：接入新提取器、保留 Legacy 回滚。
- `src/backend/bisheng/knowledge/rag/base_file_pipeline.py`：传递 `retain_images`。
- `src/backend/bisheng/core/config/settings.py`：新增带范围校验的 ETL4LM 图片配置。
- `src/backend/test/knowledge/test_version_management_config.py`：补充配置默认值和非法值测试，或使用新的专项配置测试文件。

### 不修改
- `src/backend/bisheng/api/services/etl4lm_loader.py`：检索未发现当前生产路径引用，作为 Legacy 文件留待单独清理。
- 前端、数据库迁移、MinIO、Milvus、Elasticsearch。

## 发布与回滚

1. 专项 fixture 验证 `render_only`。
2. 在测试环境启用默认 `original_first`，统计 embedded/fallback 比例和图片大小。
3. 生产灰度前可临时配置 `render_only`，确认高 DPI 区域渲染稳定。
4. 再切到 `original_first`。
5. 出现坐标或格式异常时切回 `legacy`；配置缓存按项目现有机制刷新。
6. 不自动重建历史文件；仅新上传、重试或人工重建的文件使用新策略。

## 备选方案与决策

| ID | 方案 | 结论 | 理由 |
|---|---|---|---|
| AD-01 | 只把整页渲染提高到 200 DPI | 不采用 | 内存高，仍损失内嵌原图质量 |
| AD-02 | 只使用 `extract_image(xref)` | 不采用 | 无法覆盖矢量图、组合图和扫描页局部 |
| AD-03 | 原图优先 + bbox clip 兜底 | 采用 | 质量、覆盖率和性能平衡最好 |
| AD-04 | bbox 乘 DPI 倍率后写回 | 禁止 | 会破坏前端 PDF 定位和 chunk bbox |
| AD-05 | 高置信度阈值全部配置化 | 暂不采用 | 运维组合复杂且难以稳定验收 |

## Requirements Traceability

| Requirement | Design Elements |
|---|---|
| REQ-001 | `PdfImageExtractor`、候选匹配、安全提取限制 |
| REQ-002 | bbox 校验、区域渲染、像素上限 |
| REQ-003 | bbox 不变约束、现有 URL 和 Pipeline 保持 |
| REQ-004 | `Etl4lmConf`、策略分派、Legacy 回滚、retain_images |
| REQ-005 | 错误处理、结构化日志 |
| REQ-006 | 原图零渲染、bbox clip、像素上限 |

## Test Strategy

- 单元测试以程序生成 PDF fixture 为主，不依赖 ETL4LM、MinIO、数据库、Milvus 或 ES。
- Loader 集成测试 mock ETL4LM HTTP 响应与 MinIO bucket 名，只验证 partitions 合并、URL、bbox 和配置传递。
- 使用 `pytest` 参数化覆盖策略、bbox、页旋转、候选数和配置边界。
- Ruff 与专项 pytest 作为本 Feature 自动化质量门。

## Design Quality Gate
- [x] 所有 requirement 均映射到设计元素。
- [x] 新增和修改文件职责明确。
- [x] 无数据库、API、前端或跨模块架构变更。
- [x] 风险、回滚和历史数据边界明确。
- [x] 用户确认设计（2026-07-15）。
