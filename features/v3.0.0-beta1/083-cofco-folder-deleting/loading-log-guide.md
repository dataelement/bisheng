# 文件列表 loading 排查日志

2026-11-05 已补诊断日志；不改变加载、删除、权限、分页或查询逻辑，不增加数据库查询。尚未在客户环境复现，不代表 loading 根因已查清或性能已修复。

## 复现时提供什么

记录发生时间、空间 ID、目录 ID，以及慢的是 `/children`、`/search` 还是前置 `/info`。请求已经返回时，响应头的 `X-Trace-ID` 可直接串联日志；仍未返回时，先按时间/空间/目录匹配开始日志，再取其 trace_id。无需提供 Cookie、Token、文件正文或含凭据的原始 HAR。

## 怎么查

新日志复用 `BS_METRIC`，domain 为 `knowledge_read_trace`。HTTP 访问日志和原 `knowledge_space_children` 耗时汇总继续保留。

```bash
rg 'domain=knowledge_read_trace.*space_id=142' backend.log
rg 'trace_id=实际追踪ID' backend.log
```

每条新日志带 operation、trace_id、tenant_id、space_id，以及适用的 parent_id/source/page_size。空间根目录的 parent_id 为空，不伪造目录 ID。

- `operation=children`：普通文件列表或目录树请求。
- `operation=search`：搜索结果加载。
- `operation=delete_visibility`：读取尚未完成清理的删除可见性记录。
- `source=file_list/folder_tree/search`：新客户端提供的固定来源提示；不参与权限或业务判断。旧客户端没有该提示时，记录 `children/folders_only/search`，不把推断值伪装成精确页面来源。

每个调用固定记录 `event=start`、各关键阶段 `event=stage_start`、`event=end`；没有逐文件日志。结束日志提供 total_elapsed_ms、各阶段 *_elapsed_ms、status 和失败时 error_type，不记录异常正文。

## 看哪个阶段

- `authorize`：空间/目录访问核验。
- `decode_cursor`：分页游标解析；仅 children。
- `scope_filter/tag_filter/keyword_search`：搜索范围、标签与内容搜索准备/查询；仅 search，按实际分支出现。
- `version_filter`：非主版本排除读取。
- `scan_visible`：候选扫描及可见权限过滤；沿 trace_id 对照既有 permission_visible_list 的 DB/权限细分耗时。
- `version_enrich/extra_info`：版本字段、标签、目录后代状态、审批等附加信息。
- `deletion_status`：本次新增的目录删除状态及范围状态投影。

删除可见性子调用另有 `footprint_query/checkpoint_query/collect_hidden_ids` 阶段，结束时记录 footprint_count、request_count、active_request_count、returned_count。checkpoint_query_elapsed_ms 覆盖该次读取/取回及 JSON 转换所处阶段；不记录 checkpoint 或清单内容，不为计数额外遍历/序列化它们。

只有 start/stage_start 而没有 end：请求尚未结束，先看最后记录的 stage，再检查同 trace 的子调用和数据库日志；不能仅凭该现象认定死锁或资源争用。进程退出、日志采集丢失也可能缺 end。

有 end 且 status=error：error_type 与最后 stage 指明失败位置，原异常继续按既有处理传播。main children 已结束而页面仍转圈时，对照目录树、审批区及前置详情的网络请求，不把主列表耗时当整页完成时间。

## 部署与验证

后端更新后新增日志生效；新客户端额外发送 `X-Knowledge-List-Source` 来精确区分来源。仍复用现有 `X-Trace-ID`，不创建第二套请求编号。

日志遵循现有 `metric_log.enabled` 全局开关（默认 true）及 INFO 日志级别；如果环境已关闭指标日志或过滤 INFO，需要在该环境确认采集配置。本次未修改环境配置，也未部署到 105/客户环境。

配置完整的本地聚焦验证 75 项通过，包含真实空列表/搜索、授权失败、阶段耗时与错误脱敏、真实删除可见性数量及既有 SQL 查询次数预算。Ruff lint/format 和差异检查通过；独立代码复核无实质问题。复核者使用默认环境的重复测试尝试因缺少 BS_MILVUS_CONNECTION_ARGS 未启动，正式结果取使用单元配置的上述 75 项。

前端仅新增三个固定来源请求头，按约定未运行本地前端测试/构建。实际客户日志采集与慢请求定位仍待复现。
