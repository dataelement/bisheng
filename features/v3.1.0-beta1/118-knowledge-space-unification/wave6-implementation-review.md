# W6 持续集成记录（2026-11-06，未最终收口）

从 `2364add1bb80a7fef670d42a99b2833558dc3231` 的原137项待办继续。先冻结 [W6分批合同](./wave6-completion-contract.md)，再由三个 agent 独立工作树按依赖实施，主 agent 负责共享结构、固定提交合流、复查和验证。本文是滚动交付记录，未表示完整特性通过。

## 本次账本快照

首个W6 checkpoint 功能主树 `001c0b0b9d743e4fa4a373c65f34cf5af4fbe22d`，原137队列完成18项：T063–T066、T077–T082、T159/T160、T175/T187、T192–T195，原队列剩119项。为完成同一需求实际前置登记68张接缝卡 T605–T672，其中62张已完成、6张仍待办。因此历史672编号 = 545已完成/历史交付 + 125当前待办 + 2外移；范围内670张复选框卡。接缝卡是测试、事务/身份/存储接线的拆分，不是新增产品需求。

已勾选接缝卡T605–T666。T655/T656的秘密字段问题已由 `36556cab2` 闭集修复并独立复核，57项配对绿，原复现拒绝；不是只加一个key黑名单。T616–T619已由 `dad4dca7b` 接通实际API/Celery/Beat，当前只装配真实embedding handler。T111/T112完整的按权限来源展示、公开删除协调尚未交付，不能用内部计数核心代替。T667–T672在该历史checkpoint尚未计完成；后续已独立复核合入，见最新滚动出口。

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

用户明确使用mock模型/ETL；mock固定已审源码只部署于私有网络，不发布控制端口。新环境当前仍是标准旧版本，已通过旧版真实API创建两个隔离租户、8/16维Embedding和chat模型并配置mock ETL；五份旧版真实上传样本均已处理成功，并从实际索引读取21个Chunk（15/2/2/1/1）及版本信息，准备态摘要在服务器独立evidence目录。尚未部署F118 API、准备完整六来源/授权样本或执行停服/备份/转换/恢复演练；这些准备数据不是正式基线。旧镜像构建使用标准`uv sync --frozen --no-dev`；额外pip check有历史dataclasses backport元数据冲突，未改依赖，不声称pip check通过。健康、登录和单测不替代全链路E2E。

用户本轮明确免除DM8实测。继续遵守C2的SQLModel、JsonType/方言helpers、可移植仓储/DDL及静态检查；真实事务/投影/并发与升级在MySQL执行，报告必须注明DM8未实测。不得访问中粮业务库补证，也不再等待DM8凭据。

当前尚未完成的原115项及新6项见 [当前逐项清单](./pending-tasks.md)。原94条AC、140条QA和13张SVG不变；分享签发T404/T405继续外移。没有push，没有生产部署，没有正式迁移或完整E2E结论。


## 最新滚动出口：实际文件处理与有界盘点

当前历史702编号：579完成/历史交付、121待办、2外移。原137队列新增关闭T067–T070，累计22完成、115待办；接缝T605–T696全部完成，T697–T702按合同继续并行。T157/T158的正式权限迁移、T161/T162完整M2与其他消费者仍不因纯函数或raw仓储可用而整卡勾选。

- PROC固定`32b05a9b09026a8202d21d688b62f96f02d7bca3`已合入。两类文件处理经真实ASGI→Service/Owner→J1→Celery handler装配；只选中版本、失败项重试、原容器edit及原身份，既有Caller显式规则/完整表格不限行快照保留，不重置全索引、不重算空间默认。空/全跳过空间模型保存经真实物理完整链与R2同事务，合法同模型no-op不推进R/G；不等于公开KN模型修改入口已完成。
- 独立复查实际确认并修复：同模型no-op scope刷新后漏CAS；DIR被孤儿Version引用被当成空；单文档400版本primary校验V²。新增4个CAS红→绿和2个坏链/复杂度红→绿，独立原复现通过；400版本is_primary读取160000→400。固定32b独立三路径51绿，未改消费者部分更宽八路径95绿；作者22路径258绿。
- MIG固定`7d4f0322252d4a6bf788a056f3c66a5953625fc8`已合入。13类200+1 PK分页、六来源raw事实、tenant/type/父链完整性、不输出provider配置。独立复查发现逐tenant重复全局孤儿扫描，原两叶修复并冻结global once+tenant once；5租户实际探针为APP 1+CH 1+AS 5，新事务仍重验、不使用cache。paired46绿、作者组合139绿，root窄修复核46绿；raw仓储不签Source授权/legacy证据或ready。
- 权限计划固定`cd575e8dc`已合入：单资源wrap有界批次、Catalog一次派生和Source线性索引。12资源×27模型×20Grant×100Source实测derive12→1、Source过滤48000→0；原始权限快照保旧use/auth pin和坏父拒绝。正式library→space namespace映射与M4仍待集成，不能将原resource不变的pure校验冒充转换后证明。
- 持久artifact固定`3d19c0378`已合入，经独立83绿；新环境实际MinIO put/readback/hash及相同内容幂等通过，证据`/opt/server/f118-e2e/evidence/minio-artifact-smoke.json`。这只证明存储adapter，不代表已冻结SQL正式基线。
- 创建初值固定`50b696b7c`已合入：原创建资格、raw工作台Embedding窄投影和真实系统规则；8个实际404红→首实现59绿1个schema_version夹具不完整→正确夹具60绿。独立真实ModelDefaultReadRuntime/Repository/native Session三项补测全绿，含Root继承与超管home身份保留；独立五路径56绿。不把简单mock用例称SQL证明。

主树受测源码`55e2e3bc459e716c1023dece7d51f3ac547d6000`：完整F118目录加11个原知识/权限路径，**2567 passed**、35693 warnings、73.99秒，无fail/skip；日志`/private/tmp/f118-w6-integrated-file-inventory.log`与同名前缀JUnit。该次已包含本段全部合入生产变更和创建初值；之后只有冻结合同/任务文档变更，不累计前次2395/2347为独立用例总数。

T692两端只读旧表格实际规则镜像通过平台63/client20原API回归、目标lint；strict与各自既有22/145诊断比较新增0。没有改依赖/锁文件或把全构建报为通过。原94AC、140QA及13张SVG不变；本轮DM8实测由用户免除，保持C2静态；标准旧环境、mock/MinIO证明与正式迁移、F118部署、完整E2E分别记录。没有push或生产环境变更。


## 2026-11-07滚动出口：元数据前置、平台表单与正式来源流

当前历史731编号：605完成/历史交付、124待办、2外移；范围内729复选框。原137队列累计23完成、114待办，另10张同需求必要接缝卡未完成。T697–T719、T723/T724与原T178按固定提交独立审及主树验证闭合；T176/T720–T722及T725–T731仍待实际合入和兼容收口。新增叶子只补已有接口遗漏，不增加产品AC；旧121待办是上个checkpoint，不当作当前数字。

- Metadata准备固定147a7cb5a已合入：真实全历史版本/物理链，schema CAS与单事务私有计划，冻结每版本before/after值，不写File值/索引/Model R/G。独立审确认并修复DIR foreign tenant漏检、pending ORM越过CAS及活跃job no-autoflush漏口；24路径361绿，另1001条过期job批量补查预算3次。不是完整Owner/J1接线，T071/T072仍未勾。
- Native metadata索引handler固定5e1af6068已合入：原KnowledgeRag准入，Milvus 10001条11批及真实ES调用形状，保pk/vector/文本、按冻结File业务值替换受影响字段；partial失败、guard、取消及资源close均明确处理。作者配对32绿，独立相关150绿加3项取消/guard补测，无行动项。尚未注册metadata kind，未宣称真实索引E2E通过。
- 原名称索引固定6bb7400d1已合入：模型/知识原目录各线性编译一次，后续slot不重扫。600槽实测原model目录601500读取→编译3000，server2100→3，两个1200槽查询目录读取0；独立70目录1531项差分一致。原目录name显式补齐5173f265d，401行三次分页查询。Root旧数值槽撤共享及失效初始BRR的正式分类/回填仍待下一合同，不把原ID当历史授权证明。
- 精确物理facts固定d5771649a已合入：Knowledge与Model/Server完整global PK存在性，批≤200，不把foreign/offline/退休类型/坏父链误记missing。200目标KN两次/model一次SQL；配对及root25绿，不写BRR或legacy证据。
- 原授权pin读取固定3b14ee02f已合入：SQL CURRENT pin、唯一Store及原模型checksum绑定，完整原共享流、具体tenant/原native TX、无写或在线repin。21配对绿，独立159相关绿；另已在109独立真实MySQL/OpenFGA验证，两次SQL读取、Root空集、tenant2/3各读到共享server1，无SQL/FGA写。证据`/opt/server/f118-e2e/evidence/permission-original-pin-smoke.json`，受测源码archive SHA256 `2565f353cf021a26846e84b2719b19dacca9dce097eba35af89107ac07746802`。这不是正式基线冻结或权限转换。
- 六来源实际消费流固定51697e888已合入：真实13分页/六extractor/原NameCatalog与共享读取/线性解析/物理facts，零版本root不伪造current，历史和disabled来源保留，闭集root/source/slot/retired记录不泄露raw graph或provider配置。配对20绿；独立7路径213绿，大场景1607来源36 SELECT，401唯一目标按4批预检，不按重复slot重扫。全资源/creator预检、artifact正式freeze、资格和初始回填未完成，T161/T162不勾。
- 原T178及受控Editor/Dialog固定92e276174已合入：两个类型完整数字/字面regex校验，合法空regex保留，pending分隔符不丢；关闭/重开/卸载/ABA及共享query读取隔离。独立2个真实红后绿，root八路径132绿。窄基本信息API9c5128da已合入，name/description/is_released显式投影；实际创建和列表入口固定4bc757a2d正在独立审，尚未合主树，不能以组件通过宣称完整页面通过。
- sidebar与入口三语实际locale同步，原keys/其他values逐项保留，check-i18n无新增漂移。旧F064异常标记/筛选在统一列表的兼容缺口已登记W6§23/T725–T731，后端SQL及前端并行补齐，保既有五个测试断言；原b1635e9d34已发布的无预筛导航保持。不能通过删除旧断言或假造前端字段收口。

主树受测源码7680121ce67081ac878e9d8efa711bbcab7ab5f9：完整F118目录加11个旧知识/权限路径，**2812 passed**、38853 warnings、84.65秒，无fail/skip。日志`/private/tmp/f118-w6-source-metadata-integrated.log`及同名前缀JUnit；包含已合元数据handler与SourceInventory，未包含尚未合入的旧异常兼容修复。历史2760/2567不重复累加。平台主树八路径132绿是基本信息API合入之前的快照；4bc平台候选13路径182绿且strict为原22+旧F064 scope夹具5，已明确未闭合，不报全量绿。

真实旧环境已保留两个版本历史、人工Chunk文本和File元数据值、QA独立数据。旧Chunk PUT曾500后真实GET确认部分已写、旧QA关键词filter偏差均记录在准备证据，未冒称API成功或扩大需求修复。标准旧API仍运行，候选源只在独立临时只读容器验证读取适配；未执行新版API部署、正式停服/备份/盘点冻结/转换/恢复或完整E2E。用户免DM8实测，保C2静态与真实MySQL/中间件验证；3005不操作，无push/生产变更。


## 2026-11-07统一入口兼容收口

当前历史747编号：618完成/历史交付、127待办、2外移；原137队列24完成、113待办，另14个必要接缝待办。T176/T720–T732及T743已完成，完整详情/上传/移动/删除和E2E仍未勾；T733–T742元数据闭环与T744–T747/原T149/T150按先冻结的§24/§25并行推进。§24先做精确执行仓储/Owner/J1四事实，后依赖推进实际runner及原协议桥接；不将先交付helper当完整T072。

- 平台入口固定4bc757a2d独立审无确认问题，独立13路径183绿并补共享reader/PUT ABA迟到2项绿后合入；前端异常恢复固定74a94d94f经另一独立代理11路径178绿（包含6个额外时序/透传验证）复核合入。原F064五项能力断言全部保留，普通cursor/admin page切换筛选均从首段重置，旧query与row action epoch不复活。没有改QA/detail/认证store/请求层或依赖。
- 后端固定a46be00ae经独立实际运行与SQL审后合入：四改动测试叶67绿；扩大组合103绿/5个旧port夹具红，前驱同叶20绿/候选15绿5红，精确缺新增aexists_abnormal_files。T743按登记补空set port及规范False参数后主树该叶20绿，原所有角色、scope、home身份断言保持。独立三项probe覆盖1002 filtered稀疏空页（首1000拒绝/11SQL且零marker、续页继续）、相同/NULL时间cursor和home1/selected101/foreign坏FK。
- root主树a20ae8a48后端组合增加原F064回归，**2867 passed**、38853 warnings、96.69秒；日志`/private/tmp/f118-root-unified-abnormal.log`与同名前缀JUnit。平台14路径**189 passed**，日志/JSON`/private/tmp/f118-root-unified-platform`。这些是实际合流选集，不累计独立代理选集用例数量；未将SQLite索引计划称MySQL实测。
- root执行官方pnpm lint:prune成功，生成仅KnowledgeFile原no-console/exhaustive-deps共8行冻结项移除，提交2c43e234e，未手改suppression或清理其他模块。strict仍报告原22条，精确诊断对照未新增；完整typecheck不是通过。
- 独立旧环境已通过原API保存工作流两版本（1 current/2非current）、助手原模型+legacy/SPACE知识槽及disabled频道同步目标，并GET回读配置/graph摘要。证据`evidence/preparation-saved-sources.json`。第一次助手稀疏PUT因旧代码把省略temperature写NULL报500，保留实际SQL1048及失败记录后，使用原GET temperature完整表单成功；没有改旧产品代码、隐藏失败或将其报为E2E成功。准备样本仍不作为正式基线。

原94AC、140QA及13张SVG不变；当前HTML/设计/升级/任务数字同步。独立环境仍标准旧基线运行，未部署F118、正式停服冻结/转换/备份恢复/完整E2E，无push/生产修改。DM8实库免测继续执行，C2静态和MySQL演练保持。
