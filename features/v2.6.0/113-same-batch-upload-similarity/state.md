# 113 同一次上传文件的相似互判

- 需求：`requirements.html` 0.2，2026-11-03 确认。
- 设计：`design.html` 0.1，2026-11-03 确认。
- 实现：已落地。解析提交函数未改。新表 `knowledge_upload_batch`、`knowledge_upload_batch_file`。登记可选 `upload_batch_key`。解析提交成功后刷新当前文件，并往默认 Celery 队列投递同批补算。
- 偏差：补算任务使用默认 `celery` 队列，不使用 `knowledge_celery`，避免占用解析工人。与现有自动发布任务同一队列。
- 开发测试：`src/backend/test/knowledge/test_same_batch_upload_similarity.py` 12 项通过。隔离 SQLite，相似打分是真实函数，全文检索和 Celery 未连接。
- 未跑：客户端 Jest。本机 jsdom 缺少 canvas 原生模块，测试套件未能启动。未跑真实 MySQL、真实队列和页面。
- 代码审核：作者自查，不是独立审核。
- 状态：研发实现完成，待独立验收。
