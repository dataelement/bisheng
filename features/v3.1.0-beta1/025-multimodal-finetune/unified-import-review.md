# 统一数据集导入调整复核

基线 d74536f3f6。用户明确调整：仅保留“导入数据集”按钮，QA 合并到导入弹窗，停止旧格式新导入。历史旧数据保留及显式转换不变。

本地验证：336 项后端/隔离 HTTP/core 对象路径与迁移 head 检查通过；40 项关联前端测试通过；全工作区 lint/typecheck/i18n 通过；Platform 生产构建通过。官方 lint:prune 仅将删除的旧 helper 对应 no-explicit-any 抑制数从 29 降至 28。原 BatchTagDraftDialog 的 1 条 unused-disable 警告仍存在。

七维复核：边界、权限、并发、信息泄漏、测试、代码分层与文档同步均 PASS。没有新增表、迁移、错误码、HTTP 路由或第三方依赖；QA 继续调用原受保护 endpoint，沿用知识库可见权限及严格租户过滤；不保存源连接凭据。前端作用域切换撤销旧回调，QA 选择保留分页搜索及错误重试覆盖。旧格式不能通过本地声明 text、远程清单/ZIP 或原本地保存入口绕过限制；显式转换已有旧记录的 HTTP 流程通过。

移除已无调用的 CreateDataSet 与转发文件及 helper；QA 相关测试迁入统一弹窗套件。底层 FinetuneDataset 只作为导入引用/校验快照，未实现版本管理，页面已去掉内部版本 ID 和误导性版本文案。

部署仅更新 /opt/server/bisheng-zgq 走查项目的软件，不再执行迁移/兼容登记，保留上一轮 object 代理签名 Host 修复。实际环境验证记录独立保存；正式 QA 用例状态仍保持待执行。
