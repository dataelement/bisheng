# 客户端管理视图修复发布集成

2026-11-16。用户在本地开发完成后明确授权合并、提交并推送feat/3.1.0-beta1。本记录更新开发交付时“未合并、推送”的阶段状态；实际远端SHA于推送后独立查询，在交付回复确认。

- 远端发布基线：fea131549da2f0fe6e8460dcc868b9cad2fc5ce9。
- 修复来源：e0b99096663c582e248bd4070a2a7eb045345bf6，分支codex/beta1-client-management-scope。
- 通过codex/integrate-client-management-scope-beta1独立工作区正常合并，无冲突。13个修复文件与来源一致，63个上游文件与远端一致，双方无文件重叠。审计引用展示和共享树导航更新全部保留。主目录分支及未提交文件保留。
- 不修改后端、Gateway、数据库结构或历史数据；不部署。

## 合并树检查

| 检查 | 结果 |
| --- | --- |
| 客户端管理租户、审计及敏感词原有定向回归 | 167通过 |
| 上游日常审计引用与运行审计回归 | 15通过 |
| 合并树定向测试总计 | 12个文件，182通过 |
| 标准前端代码检查pnpm lint | 通过 |
| 标准前端类型检查pnpm typecheck | 通过 |
| Git空白、未解决冲突及双方文件完整性 | 通过 |

初次复用的node_modules指向旧工作区，不能验证本次新增共享组件；已仅调整当前隔离工作区的忽略依赖链接，使所有@bisheng工作区包解析本合并树，外部依赖复用已安装版本。未修改锁文件、package.json或其他工作区依赖。

Node 25.6.1原生localStorage在未提供文件时与jsdom全局存储冲突，日常审计两项测试报getItem不是函数；仅对测试进程使用NODE_OPTIONS=--no-experimental-webstorage恢复jsdom浏览器存储，保留原业务断言，未改应用代码及测试用例。

日志位于/private/tmp/client-scope-merge-tests-final.log、client-scope-merge-lint.log及client-scope-merge-types.log。开发阶段发现的6项既有dshRequestCompatibility失败仍单列，不以定向测试结果宣称全仓通过，见[开发交付](client-management-scope-delivery-20261116.md)。

本轮属于源码合并推送，真实Gateway、浏览器双标签及部署后请求验收未执行。QA继续执行TC-MTG-016～018，核对顶部目标与审计及敏感词读写一致、切换丢弃正文及草稿、未知上下文不回落Root、普通管理员主属和原编辑资格保持。
