# F118 之外的后续优化

2026-11-10按用户“先完成功能，再整体测试；无关优化后续排期”记录。本清单不构成F118发行前置，也不代表已批准具体实施方案。

| 项目 | 已知背景与后续边界 | 排期 |
| --- | --- | --- |
| 分享链接签发授权加固 | 用户已明确移出，沿[原独立待办](./share-link-issuance-authorization.md)评估，不混入可见代use。 | 待排期 |
| Worker在途外部IO与用户配置修改的竞态治理 | 用户已排除；另行设计跨资源/索引世代并发一致性，当前仅保正常冲突、幂等和配置过期检查。 | 待排期 |
| 通用权限Projection大批STAGE/FAILED_CLOSED恢复扩展 | 本轮模型共享仅复用既有COMMIT-only有界批；通用状态机/重试扫描平台另评估。 | 待排期 |
| 普通知识处理多kind列表与缓存的通用性能改造 | 原四kind结果/执行内核保持；本轮新move分页缺陷须就地修正，不借机改所有任务查询/缓存框架。 | 待排期 |
| 旧knowledge endpoint静态问题整理 | 本次旧删除适配涉及knowledge.py，按同一Ruff规则对HEAD和工作树比对均为10条既有诊断、无新增；包括旧QA同名handler/闲置局部变量及旧可选类型/标点。保持无关QA行为，另行整理。 | 待排期 |
| 旧v2 filelib跨模块API依赖整理 | 既有filelib从knowledge.api.dependencies导入仓储依赖，当前arch-guard RULE5输出与f06ee9889a父提交逐字相同；本次上传只新增application纯适配，不引入该跨API依赖。后续统一梳理原DI导出边界。 | 待排期 |

## 整体回归发现的既有测试维护（2026-11-10）

以下仅在共同祖先9eef0016de的同依赖/同环境中复现后外列；不是新功能失败的排除名单，不影响本次对真实功能及环境E2E继续验收。

| 项目 | 具体证据与范围 | 排期 |
| --- | --- | --- |
| 旧MCP hosted-app测试接缝 | test/open_mcp/test_app_tools 15节点在祖先同节点同AttributeError；生产与测试对应叶无需求diff。保本次知识/MCP真实入口验收，不顺手改既有App测试框架。 | 待排期 |
| 客户端旧静态/环境断言 | useFileManager源码拆文件3、Square桌面环境2、unifiedRoutes引号/组件归属3、TXT请求AbortSignal匹配5；共13节点在祖先同配置精确复现。实际页面和API结果仍在本次E2E验证。 | 待排期 |
| 平台旧权限组件断言 | f048PermissionDialog旧button角色1、knowledgeSpaceGrantSubjects旧externalId期望1、ModelAccessDialog旧button角色1，在祖先同真实workspace/锁定图标环境复现；不改变本次纯可见保留/可撤销验收。 | 待排期 |
| 本地前端依赖环境补齐 | 当前已有node_modules与锁不齐（dnd缺失、原图标0.2.28对锁0.2.37、部分源码包解析）；临时映射真实源码/已校验图标仅用于取证，不改依赖/锁或以fake组件造绿。原生typecheck缺口与真实构建分别报告。 | 环境维护 |

正式停服后冻结、实际权限转换/引用回填/Coverage启用、知识及模型删除保护、两端必要页面均仍属本次功能。新代码产生的功能缺陷、权限漏洞或明显重复全量读取不得用本清单豁免。整体回归、升级演练和E2E在功能齐备后统一执行，必要定点开发验证保留。
