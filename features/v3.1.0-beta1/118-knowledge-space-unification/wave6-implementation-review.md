# W6 持续集成记录（2026-11-06，未最终收口）

从 `2364add1bb80a7fef670d42a99b2833558dc3231` 的原137项待办继续。先冻结 [W6分批合同](./wave6-completion-contract.md)，再由三个 agent 独立工作树按依赖实施，主 agent 负责共享结构、固定提交合流、复查和验证。本文是滚动交付记录，未表示完整特性通过。

## 本次账本快照

截至功能主树 `001c0b0b9d743e4fa4a373c65f34cf5af4fbe22d`，原137队列完成18项：T063–T066、T077–T082、T159/T160、T175/T187、T192–T195，原队列剩119项。为完成同一需求实际前置登记68张接缝卡 T605–T672，其中62张已完成、6张仍待办。因此历史672编号 = 545已完成/历史交付 + 125当前待办 + 2外移；范围内670张复选框卡。接缝卡是测试、事务/身份/存储接线的拆分，不是新增产品需求。

已勾选接缝卡T605–T666。T655/T656的秘密字段问题已由 `36556cab2` 闭集修复并独立复核，57项配对绿，原复现拒绝；不是只加一个key黑名单。T616–T619已由 `dad4dca7b` 接通实际API/Celery/Beat，当前只装配真实embedding handler。T111/T112完整的按权限来源展示、公开删除协调尚未交付，不能用内部计数核心代替。T667–T672已冻结、由KN独占实施，尚未计完成。

## 已合入的真实能力

| 范围 | 固定提交与主树证据 | 本阶段边界 |
| --- | --- | --- |
| 平台API/缓存范围 | `f64645169`；六实际路径63绿 | T175/API与Mock合同，不代表页面已接真实API；scope变更隔离迟到响应和确认计划 |
| 客户端API | `3ba2d5892`；API20绿 | 保旧API调用；approval auth_type已补真实类型回归；页面、任务面板另验 |
| 高级命令管理头 | INT `b800304c2`、`339e5cc16`；32绿 | 仅与后端原T221相同的四类高级写路径，普通上传/rename/move/delete和v2不加管理头 |
| 两端纯可见授权 | client `2278e202e`、platform `ae3922f28`；主树组合60/57绿 | 只补只读DTO和真实组件测试；保原level、Source、撤销及各管理动作，不增加可授visible/use |
| PROC接收前置 | `e98867c6f` | 持久确认、分页/投递仓储、原凭据恢复、真实Owner/R2 finalize、域内一次收据、整版本精确JOIN、原始accepted R；真实重建worker与endpoint见下一行，多kind仍待接 |
| 真实重建/恢复与API | `e1f62939c`、`dad4dca7b` | 逐file实际重建、租约/重试fence、持久失败、成功项不重跑/drop、零item仅finalize恢复；API/Celery/Beat实际装配；不是文件重新解析/元数据/move handler |
| KN生命周期/创建/清单 | `86f7574ec`；17路径232绿，独立scope复核38绿 | 原创建资格与管理员清单分开；具体管理租户的真实超管身份已修；普通清单100/1000预算seek，空拒绝页仍推进游标；不扩大文件edit |
| 检索成功态隔离 | 同KN提交 | 保失败ES正文便于重试，实际候选与post-filter排除处理中/失败文件；目录/预览/下载沿原资格，完整active-job gate待接 |
| 模型影响核心 | `32c369fd7`；root七路径101绿、独立新四路径64绿 | 完整Owner目标、四键来源JOIN、seek200、Coverage缺失fail closed、隐藏来源只计数；确认身份闭集已修复；完整按权限来源展示和公开删除尚待接 |
| MIG台账 | `2bab664bb`；主树六路径90绿，原缺模块36error及后续3项行为红已记录 | 同原run/descriptor/hash冻结，阶段/检查点CAS和失败恢复；只读/错误请求不偷flush；不自动发布Coverage ready，不执行转换 |
| mock上游 | `2e214a65e`；53绿，独立关键19绿 | 真实SDK base64/float32、chat stream/usage、合法PDF ETL、TXT/MD本地、一次失败；严格畸形参数拒绝；仅E2E辅助 |

INT统一结构补充链：`f118_metadata_schema → f118_processing_acceptance → f118_finalize_retry`，当前唯一head为后者。分别只加私有metadata schema修订、nullable原始接受模型修订、识别已知旧约束后允许窄场景0-item finalize retry。无业务数据转换，未知约束失败；新结构及旧guard组合通过。保留一致备份恢复要求，不提供有损自动downgrade。

## 复查与验证限制

独立交叉复查实际发现并闭合三类问题：KN超管home tenant与具体管理pin混淆；MIG查询隐式autoflush；mock stream_options非法空值和include_usage类型。LLM开放身份字典的秘密字段问题已在原T655/T656内修复并由发现者复核；未开放公开写端。PROC固定e1由非作者9相关路径120绿复核，dad追加API由主agent逐段审实际入口，20路径265绿，路由命名原1失败由2364同选集复现，未扩大白名单。

主树在MIG新增两叶合入前的源码 `5e82e376c73fd063e7201c709fe3a481462fe2b4`，整个 `test/knowledge_unification` **2025 passed**、25832 warnings、50.65秒，日志 `/private/tmp/f118-w6-integrated-interim.log`、JUnit同名前缀。该次收集不含随后合入的MIG两叶；主树 `32b19783c` 再验证MIG及五个实际相关路径 **90 passed**，日志 `/private/tmp/f118-w6-main-ledger.log`。不将这两次相加为独立用例数。

最新主树源码 `001c0b0b9` 的整个F118目录加六个真实旧知识/权限路径，**2232 passed**、31162 warnings、58.24秒，无fail/skip；日志 `/private/tmp/f118-w6-integrated-api.log` 和同名前缀JUnit。之前同组合4例因旧夹具patch已删除的ES清理函数而在断言前失败（其余2189绿），T666只移除该patch及未用import，原部分失败/整体异常/来源拒绝断言全部保留，先五路径67绿再进入本组合。没有恢复失败清ES行为。

平台typecheck仍是已对照基线的22条既有诊断，客户端145条；本轮没有修复无关构建/依赖问题。组件测试使用现有本地依赖和临时测试配置指向当前工作树源码，无锁文件/依赖修改。Canvas可选原生依赖缺失及扩展旧回归的原失败单列，不能宣称两端全套构建和测试全绿。

## 独立环境与用户确认

用户撤回109:3005后，主 agent 仅在109新建 `/opt/server/f118-e2e`、独立Compose网络/容器/卷；原3005保持不动。使用标准历史基线 `a1b1a2387949950eafe17679810f2df8eabae10b` 构建旧版本API（31860）和worker，MySQL/Redis/OpenFGA/ES/Milvus/MinIO均独立。API健康与真实首管理员注册/登录已验证，随机凭据只保存在服务器600权限文件。新空库关闭原生验证码配置供自动化使用，不修改认证代码。

用户明确使用mock模型/ETL；mock固定已审源码只部署于私有网络，不发布控制端口。新环境当前仍是标准旧版本，已通过旧版真实API创建两个隔离租户、8/16维Embedding和chat模型并配置mock ETL；尚未部署F118 API、准备完整迁移样本或执行停服/备份/转换/恢复演练。旧镜像构建使用标准`uv sync --frozen --no-dev`；额外pip check有历史dataclasses backport元数据冲突，未改依赖，不声称pip check通过。健康、登录和单测不替代全链路E2E。

用户本轮明确免除DM8实测。继续遵守C2的SQLModel、JsonType/方言helpers、可移植仓储/DDL及静态检查；真实事务/投影/并发与升级在MySQL执行，报告必须注明DM8未实测。不得访问中粮业务库补证，也不再等待DM8凭据。

尚未完成的原119项及新6项见 [当前逐项清单](./pending-tasks.md)。原94条AC、140条QA和13张SVG不变；分享签发T404/T405继续外移。没有push，没有生产部署，没有正式迁移或完整E2E结论。
