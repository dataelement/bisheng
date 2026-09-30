# Feature: ETL4LM PDF 图片高清提取

**Feature ID**: `055-etl4lm-image-quality`  
**Status**: Implemented / Verified  
**Mode**: Enhancement / Bug Fix  
**Created**: 2026-07-15  
**Updated**: 2026-07-15  
**优先级**: P1  
**所属版本**: v2.6.0

## 1. 概述

当前 ETL4LM PDF 图片保存路径使用默认倍率渲染完整页面后再按 bbox 裁图，导致高分辨率内嵌图片被压缩到约 72 DPI 的页面显示尺寸。本 Feature 在不修改 ETL4LM 请求和 bbox 语义的前提下，采用“PDF 内嵌原图优先、200 DPI bbox 区域渲染兜底”的混合方案。

详细需求、设计与任务见：

- [requirements.md](./requirements.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)

## 2. 目标

- 普通 PDF 内嵌图片尽可能保持原始像素和压缩数据。
- 无法安全匹配原图时输出默认 200 DPI 的 bbox 区域图片。
- 不增加 ETL4LM 服务请求负载。
- 不改变 bbox、分块、Markdown URL、API、前端和数据库契约。
- 提供策略配置、资源上限、日志、测试和 Legacy 回滚。

## 3. 非目标

- 不修改其他解析器。
- 不自动重建历史文件。
- 不处理图片删除、复制和预解析重复等资产生命周期问题。
- 不修改 MinIO 匿名访问策略。

## 4. 核心验收摘要

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-01 | ETL bbox 唯一匹配普通内嵌图片 | 直接保存原图，尺寸和格式不降级 |
| AC-02 | 组合图、矢量图、扫描页局部或匹配不确定 | 使用 200 DPI bbox `clip` 渲染 |
| AC-03 | 提高输出图片 DPI | 原始 bbox、chunk bbox 和前端定位完全不变 |
| AC-04 | 图片过大 | 自动降低有效 DPI，不突破像素上限 |
| AC-05 | 关闭保留图片 | ETL Loader 和上传 Transformer 均不生成图片 |
| AC-06 | 新策略异常 | 可切换 `legacy` 快速回滚 |

稳定追踪 ID 和验证方法以 [requirements.md](./requirements.md) 为准。

## 5. 架构决策摘要

| ID | 决策 | 结论 |
|---|---|---|
| AD-01 | 图片质量策略 | 原图优先 + 区域渲染兜底 |
| AD-02 | bbox 缩放 | 不修改 bbox，仅放大渲染矩阵 |
| AD-03 | 默认兜底 DPI | 200 DPI |
| AD-04 | 资源上限 | 单图默认 1600 万像素 |
| AD-05 | 回滚 | 配置切换 `legacy` |

## 6. 影响范围

- 影响知识库预解析、正式入库、知识空间解析、文件重试和重建中的 ETL4LM PDF 图片。
- 不影响 ETL4LM 文本识别、其他 Loader、前端、API、数据库、向量库和 MinIO 上传协议。
- 新上传或重新解析的图片体积可能增大；原图匹配成功时 CPU/内存通常下降。
- 历史 MinIO 图片保持不变，除非人工触发重新解析。

## 7. 发布约束

- 先验证 `render_only`，再启用 `original_first`。
- 观察图片尺寸、提取耗时、embedded/fallback 比例和 MinIO 增量。
- 发生坐标、格式或资源异常时切回 `legacy`。
- macOS 可完成单元测试；无需 DM8 或数据库验证。

## 8. 当前状态

- `requirements.md`：已确认。
- `design.md`：已确认。
- `tasks.md`：已执行并验证。
- 生产代码：已实现，验证证据见 `verification.md`。

## 相关文档

- [v2.6.0 Release Contract](../release-contract.md)
