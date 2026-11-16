# 企业市场与工作台增量设计（F019）

关联：[spec.md](spec.md) · [版本契约](../release-contract.md)。沿用 [F055 架构](../../v3.0.0-beta1/055-enterprise-plugin-market/design.md)，不复制或改写旧发版线的基线要求。

## 当前决策

- 版本 ID 保持稳定身份，同版本明确覆盖时更新 SHA-256、大小、manifest、当前版本及 revision。导入事务重新判断当前摘要，历史 completed 任务不能阻止 A→B→A；失败保留当前版本。
- 删除沿用租户管理员认证与 revision 乐观并发控制，保留版本和审计记录；查询、详情和下载均检查当前可见状态。
- 页面复用单包接口串行处理最多 50 项，以任务 status 判断导入结果。各包独立提交，关闭请求不回滚已提交的包。
- API、domain、前端统一 100 MiB 上限；代理还需容纳 multipart 开销。展开大小、条目数、路径和类型限制继续生效。
- patch 的 config 保留静态配置，不求值 YAML 标签或 JavaScript；唯一允许的表达式及容器深度、节点数限制见 [WB-08](workbench-package-validation.md)。
- 错误保留完整 ApiError，仅对固定的工作台校验契约展示规则和字段；取消请求不提示错误，重新选包清除旧诊断。

## 协议与已知边界

详见 [上传与查询](workbench-upload-query-design.md) 及 [Desktop API](desktop-workbench-api.md)。同版本覆盖使版本号不再足以验证缓存，客户端必须重新取摘要。静态解析成功不等于目标宿主安装或运行验收通过。
