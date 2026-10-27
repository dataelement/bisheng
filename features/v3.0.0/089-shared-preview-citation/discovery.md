# F089 文件预览与引用溯源共享调研

2026-10-23；基线 `feat/3.0.0` / `38395b198`。

## 用户已确认

- 文件预览按现有方案共享：Excel/CSV 沿用现有共享实现，继续覆盖 DOCX、Markdown、TXT、HTML、图片、PDF 及音视频。
- client 为展示基准，后台 PDF 框选/切片编辑保留在业务层，两端权限、资源地址获取和页面容器保持各自责任。
- Citation 继续共享引用解析和来源预览，不只共享会话主体。
- ECharts/Mermaid 单份来源维护，分别输出到两端；现有文件已是压缩脚本，输出不需要重新编译。

## 现状及范围

- 两端 Excel 已调用 `@bisheng/file-viewers`，该包同时包含 Excel 图片展示；继续复用。
- platform `KnowledgePage/components/PreviewFile.tsx` 实际调用本地 DOCX、TXT/Markdown/HTML 和 PDF 预览；client `knowledge/FilePreview` 实际调用对应 viewers。
- platform `PlatformChatMarkdown` 与 client `ClientChatMarkdown` 都调用共享 `ChatMarkdown`，但通过各自适配器挂载本地 CitationDocumentPreviewDrawer。
- 两端 citationUtils、引用列表及文档抽屉仍被实际入口使用；client 有非 PDF 引用文字定位和异步地址解析，platform 有后台 PDF/媒体内容组合。不能简单用任意一方整文件覆盖另一方。
- public 根目录的 echarts.min.js、mermaid.min.js 两端内容分别完全一致；图表脚本加载仍由宿主提供，后台看板也使用 ECharts。另有 platform public/vditor 内嵌依赖，应单独追踪引用，不能直接当根目录副本删除。

## 实施前约束

范围是已有前端能力去重，不新增文件格式、不改变数据或授权合同、不做视觉重设计。公共视图与宿主授权/网络能力分离，保留既有使用入口。具体公共包边界、构建/开发复制方式、PDF 编辑接入合同写入 design.md，并经确认后实施。

规格依据：本会话用户“文件预览组件 和 Citation 可以按这个方案做；ECharts、Mermaid用一份，构建时分别输出到两个前端的方案”。
