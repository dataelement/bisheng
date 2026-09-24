# 复盘 Retrospective：ETL4LM PDF 图片高清提取

## 做得好的部分

- 先证明模糊发生在默认倍率页面渲染，而不是 MinIO 上传，避免错误修改存储链路。
- 保持 ETL4LM 请求和 bbox 坐标不变，仅改变图片输出路径，降低了回归范围。
- 原图优先与 bbox clip 兜底兼顾质量、兼容性和内存边界。
- Test-First 捕获了端点取整、非 PDF 输入和旋转显示矩阵三个容易被忽略的边界。

## 实施中新增的判断

- 仅 bbox 高重合仍不足以直接提取：旋转、倾斜或镜像的 XObject 必须渲染，才能保留 PDF 显示效果。
- ETL4LM Loader 也用于图片文件；通过非 PDF 强制 Legacy 将变更约束在确认的 PDF 范围。
- PyMuPDF 的 clip 像素尺寸由转换后端点取整，测试应允许 1–2 像素误差，不能简单只按宽高四舍五入。

## 后续建议

- 灰度期统计 `embedded/rendered/legacy` 比例、平均图片大小、P95 提取耗时和 fallback reason。
- 在真实文档集确认 200 DPI 的 OCR 图、截图和小字号图表效果后，再决定是否调整默认 DPI。
- 单独修复 MinerU/PaddleOCR 测试中的开发者绝对路径，恢复 `test/knowledge/rag` 无排除全绿。
- 历史文件重解析、MinIO 孤儿图片清理和资产生命周期应使用独立 Feature 处理。
