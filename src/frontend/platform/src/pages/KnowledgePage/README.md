# 知识库文件上传模块设计概要
页面： filesUpload

## 核心状态对象说明
- uploadConfig[filesUpload]：上传配置
- resultFiles[filesUpload]：已上传文件列表，自动同步到rules.fileList
- strategies[FileUploadStep2]：文件切分规则配置（含默认值），自动映射到rules.separator和separatorRule
- rules[FileUploadStep2]：全部处理规则配置（含默认值）
- cellGeneralConfig[FileUploadStep2]：单元格通用设置，自动同步到rules.fileList（用于更新表格文件配置）
- applyRule[FileUploadStep2]:预览时存储当前的rules和cellGeneralConfig配置
- chunks[PreviewResult]:文件分段结果数据
- partitions[PreviewResult]:所有分段的边界框(bbox)信息
- fileViewUrl[PreviewResult]:预览时当前选中文件的URL
- needCoverData[useKnowledgeStore]: 记录当前分段标注覆盖数据
- selectedBbox[useKnowledgeStore]: 记录当前分段标注框数据

- labelsMap[PreviewFile]: 用于直接渲染视图的标注框数据（由selectedChunkIndex和chunks计算得出）

## 交互流程说明
- 1.直接上传文件[FileUploadStep1] -》 提交上传文件[filesUpload]
- 2.下一步到第二步[FileUploadStep1] -》 更新resultFiles状态[filesUpload] -》 进入第二步[FileUploadStep2]
- 3.编辑规则[FileUploadStep2] -》 更新strategies、cellGeneralConfig、rules
- 4.点击预览分段[FileUploadStep2] -》 展示分段结果[PreviewResult]（applyRule.rules.fileList->文件选择select）
- 5.选择文件[PreviewResult] -》 更新chunks状态和partitions状态和fileViewUrl[PreviewResult] -》 渲染分段结果[PreviewParagraph]（chunks）
- 6.点击下一步[FileUploadStep2] -> 更新uploadConfig状态（rules -> uploadConfig）->展示文件预览[PreviewFile]（fileViewUrl、chunks、partitions）和分段结果[PreviewParagraph]
- 7.选择标注框[PreviewFile] -》 更新labelsMap和selectedBbox
- 8.覆盖分段[PreviewFile] -》 更新needCoverData 变更触发更新-> 保存updatePreviewChunkApi[PreviewResult]

## 数据流说明
文件列表数据: resultFiles → rules.fileList

切分规则: strategies → rules.separator & rules.separatorRule

单元格配置: cellGeneralConfig → rules.fileList

标注数据: selectedChunkIndex + chunks → labelsMap (计算属性)