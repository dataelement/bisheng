# 设计

## 共用生成

从 `pdf_artifact_generation_service.py` 提取转换、校验与上传到 `knowledge/pdf/artifact_builder.py`。知识库保留自己的 generation/Repository/Celery 编排；问答复用生成函数，避免绑定知识库外键。

新增 `qa_expert/domain/pdf_preview_service.py`：原附件读取成功后，以版本号、租户、桶、对象路径、源内容 SHA-256 和扩展名计算不可混用的键。基础 PDF 存储于 `knowledge/pdf-artifacts/qa/`（不属于问答下载接口接受的原文件路径），不存用户水印。读取时校验 PDF；未命中或损坏时，通过现有 Redis 连接获取按产物键隔离的所有权锁，锁内二次查缓存，再调用共用生成函数保存结果。

同步生成及持锁在同一工作线程完成，HTTP 协程取消后线程可继续完成，锁不会提前释放。等待及转换共享 120 秒截止时间，锁租期 300 秒；上传前验证仍持有锁，避免过期持有者发布。源文件内容变化会改变键，不覆盖原附件。跨请求复用依赖 MinIO，不依赖浏览器内存或进程缓存。

`watermarked_download.py` 的两条入口通过同一个附件基础 PDF helper：Office 用缓存服务，其他格式沿用原逻辑；拿到基础 PDF 后再打当前用户水印。接口和前端契约保持。

## 文件计划

- 新增：`knowledge/pdf/artifact_builder.py`、`qa_expert/domain/pdf_preview_service.py`。
- 修改：`knowledge/domain/services/pdf_artifact_generation_service.py`、`qa_expert/domain/watermarked_download.py`。
- 新增回归：`test/qa_expert/test_pdf_preview_cache.py`；复用知识库 PDF 和问答下载测试。

## 风险、生命周期与回退

生成代码为知识库共享路径，使用其现有回归覆盖原 PDF、解析产物、失败与陈旧 generation 清理。派生文件为可重新生成数据，不变更原文件或 DB Schema。依赖不可用时显式失败，不绕过分布式锁降级为重复转换。旧源版本的缓存不再命中；本次不引入自动清理，历史派生 PDF 会占用存储，源删除后接口仍先读取原文件而拒绝缓存。回退代码即可恢复原实时转换，派生产物可留存且不影响原数据。

验收映射：AC-1/2/3 对应缓存服务与下载入口；AC-4 对应共用生成函数与知识库处理器。测试采用外部存储/锁/转换器 fake，实际 PDF 结构校验不 mock；测试环境 Docker/MinIO/LibreOffice 联调另行标注。
