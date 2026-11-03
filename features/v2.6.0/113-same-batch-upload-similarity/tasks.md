# 实施任务

设计 0.1 已确认。下列任务已完成。

- [x] T1 新表与迁移。`knowledge_upload_batch`、`knowledge_upload_batch_file`。不改 `knowledgefile`。
- [x] T2 登记接口接受可选 `upload_batch_key`。非法键 422。其他用户或知识库复用键时业务拒绝且不建文件。
- [x] T3 解析收尾只在 `persist_parse_result_with_fulltext_intent` 返回后调用相似。无批次时只刷新自己。
- [x] T4 同批补算按代次写入。已点「不关联」跳过。旧代次不覆盖。
- [x] T5 客户端一次确认传同一个批次键，包括门户按文件夹拆开的登记。
- [x] T6 后端隔离测试 12 项通过。客户端 Jest 因本机 canvas 模块未能启动，未执行。

验收页面、真实队列和真实库留给测试岗位。
