# W2业务写入口集成与复查记录

状态：本波保存、版本、发布及删除接线完成；完整F118仍在开发。spec保持用户已确认的94条AC，不增加文件edit、任务模型绑定或worker在途外部IO治理。此报告记录W2实际实现，W0/W1的424项是[历史记录](./implementation-review.md)，不与本轮数量相加。

## 基线与合流

本波从功能分支9cbb0141de（W1结束）创建三个独立worktree：WF、AS、TARGET。主工作区本轮初始feat/3.1.0-beta1@ac65c2fc5且干净，未纳入本波并发变化或修改其跟踪文件；没有将它称作远端最新SHA。INT负责公共Runtime、legacy Reader、API/worker composition、任务/合同/文档和最终验证。各lane同文件唯一Owner，红测与实现分提交，固定SHA交叉审阅后正常merge，不从别人dirty文件取实现。

| 合同 / 业务 | 实际交付 | 独立复核 |
| --- | --- | --- |
| INT R2准备 | 2a4bea1d2；外部session targets→root→guard/source CAS，旧index缺失拒 | WF/AS实际接线与定向回归；TARGET/AS交叉核验 |
| INT legacy Reader | da2bd3685；同source/target/run/key与冻结descriptor核验 | AS固定快照12项通过，TARGET连composition16项通过 |
| INT composition | 857555b51、750674fb1；实际Owner/共享Reader同Verifier，API/worker注册 | TARGET独立LGTM，真实装配图及两个启动hook隔离测试 |
| TARGET Owner / batch | a07c92c3269；同root全target物理预锁、逐source资格/legacy、完整set盘点 | AS固定快照59项通过/LGTM |
| TARGET撤销共享修复 | 9f1711d2dc0；只原精确槽retain-only，执行/新增拒 | AS固定快照96项通过/LGTM |
| AS业务写入 | a05de576b70；当前配置+三类links增改删、发布/ONLINE、新知识visible | TARGET固定68项；与9f临时组合77项/LGTM，其中9项为一次性实际SQL探针 |
| WF业务写入 | ba4fab0433b9；创建v0/新版本/保存/恢复/current/发布/版本删/根删，新知识visible | AS：cfa1残raw修复64项LGTM；新增visible64项LGTM；自动租户过滤增量66项LGTM，作者最终7路径457项通过 |

所有提交与merge均在本地功能分支，没有push、PR合并、部署或运行数据迁移。临时探针不当作已提交长期覆盖；主agent的组合结果单列于下。

## 业务结果及防错边界

- WF所有未删除保存版本独立维护来源，Flow.data镜像不重复计数；复制及JSON导入的真实后端链复用创建/新版本/保存入口。generic metadata_filter.document_id不是物理文件选择器，不猜ID。模型、RAG、QA、Agent及已保存rerank槽按真实字段稳定提取。
- AS全部本文件实际配置写端共用事务helper。model_name实际为模型ID；明确ID不存在不能回退默认，只有空选择保留原默认行为。知识/工具/flow links的None保留、空列表解除，不互相清其他类别。
- prepare先锁全部旧/新targets，再由业务回调锁真实root/版本，核旧业务配置摘要等于当前索引，最后业务及绑定一次commit。创建投影失败、根删除第二source失败及FGA投影失败均有实际SQL整体回滚回归。新自增leaf为真实ID可先flush，不能先commit。
- 新知识选择仅对完整new-old Spec集合校验可见性；按真实0/1→library、3→space，以原actor及credential窄范围进入唯一Facade。新slot/复制/新version都算新选；旧隐藏/失效同slot保持或移除不加额外visible门槛。不扩文件edit或模型动作。
- 根删除盘点真实全部SQL版本、全部source set与全部raw引用，含inactive、零引用和无set残行。unknown source、缺set、终态残raw、digest/revision不一致在投影前10994，不能自动清理。合法旧已删且无set、无raw保持可删；终态集合原样保留。
- 共享明确撤销时live模型仅可基于同source/version原非legacy记录签new_binding_allowed=False，R2继续核精确slot。原槽可保持、改绑own或解除，newslot/copy/version及执行/发布拒。共享查询异常不伪装deny；deleting继续冻结所有R2写。该资格不持久、不新建状态/动作、不改配置digest。
- 重复ONLINE请求也核当前targets/index/config，失效拒绝，有效noop不重复初始化Agent、写SQL或推进revision。超管选定tenant取可信ContextVar，原JWT身份及scope不改。root_guard缺失但存在同root来源时明确拒绝，不能静默重置counter。

## 主agent组合验证

主agent在411d4f461473组合验证821项通过（35个pytest路径），架构检查56文件无违规，Ruff 56文件通过。

受测源码SHA：`411d4f4614737e844ddc1a790284909ea95640af`。日志`/private/tmp/f118-wave2-integrated-tests.log`，完整路径清单与exit见同名json；静态结果`/private/tmp/f118-wave2-static.json`。全提交`git diff --check 9cbb0141de..HEAD`通过，HTML13SVG/unique IDs/锚点与相对链接通过，342项任务DAG/完成依赖/配对测试/1–2叶子校验通过。

验证使用主工作区已存在Python3.11.13 venv，仅只读配置路径；PYTHONPATH指向功能源码。没有uv sync、改锁文件、修改真实配置或连接生产系统。SQL事务/故障注入使用SQLite，自动租户过滤的定向测试使用生产相同SQLModel AsyncSession及真实listener；FOR UPDATE调用及SQL形状不等价真实MySQL/DM8锁调度。

## Task Review（L1）

依据仓库`.claude/skills/task-review/SKILL.md`及其七项清单，按当前constitution/最近AGENTS执行：已有legacy Service仅增量接线，新提取器/Repository/Owner在领域模块；C3 bulk显式可信tenant谓词、SELECT自动过滤；client状态框架按真实AGENTS，未实施UI变更。旧清单中“新DAO放domain/models”等旧说法不覆盖当前constitution的Repository分层规则。

| # | 检查项 | 结果 | 证据 / 适用范围 |
| --- | --- | --- | --- |
| 1 | 架构分层 | PASS_WITH_NOTES | 新源码位于workflow/assistant/knowledge/llm/resource_reference模块；原Service/Router只改真实用例，无新legacy文件/DAO入口；arch-guard见组合验证 |
| 2 | 命名 | PASS | Repository native async前缀、稳定Spec slot及现有Service约定；测试叶子命名test_* |
| 3 | 序列化 | PASS | 既有response envelope保持；新receipt/eligibility仅内部不进HTTP；phase枚举不改SQL列/default；测试卡N/A |
| 4 | 数据库 | PASS_WITH_NOTES | 外部session不commit，业务Owner唯一commit；目标/业务current-read与source CAS；新表/DDL本波无改动；真实双库仍未验 |
| 5 | 前端 | N/A | 本波无两端产品UI变更；HTML为评审文档 |
| 6 | 信息泄漏 | PASS | 无新增凭据/真实环境配置；拒绝不泄露跨tenant资源详情，不提供客户端造receipt入口 |
| 7 | 设计同步 | PASS | design§15.5、contracts W2、upgrade§11与HTML并行进度同步，spec94AC保持 |

元数据校验：342项唯一编号、DAG无环、每卡1–2叶子、完成卡文件存在、前置依赖及配对测试完成、94AC测试索引齐全。166/342项完成（本波新增80项）。任务级清单/逐卡文件与依赖见[tasks.md](./tasks.md)。本表是任务级审查出口，不替代全特性L2或E2E。

### 红绿与首轮即绿的区分

| 卡 | 实际证据 |
| --- | --- |
| T031/T032、T033/T034 | 4c52ffa6d→5e3e0d636；d944237ce→3e578b143 |
| T035/T036、T037/T038、T039/T040 | 7f1c178fc+2774c9959→b838215dc；3ed52e3ed→fbcd65629；b8b9ccb13→c9b452bf3 |
| T043/T044、T045/T046 | 5454f6a3f→db7ee7829；47be96b34及nativeasync/drift/投影故障补红→471f2803a、9589e2681 |
| T274/T275、T276/T277 | b8b83a8b9→4628b681c；6e1116261→a01fa6847 |
| T279/T280、T288/T289 | 3295cea43→2a4bea1d2；b93fc8067→da2bd3685 |
| T282/T302、T284/T285、T286/T287 | ca1e5571e→10a43a3b2；5a216f303等→bf1531a5d；4301faeab→1b0920535 |
| T300/T301、T303/T304、T305/T306 | 35293a6f4→337cb96b6；a6a821155→c888d3902；3922f2787→b26c14bdf |
| T309–T314、T317/T318、T319/T320 | c66b9cc50/79dc35574先红→96e4031b2/b905c593e/4e3f4d0df/9342f831e；9eb1f5d37→3540664ef；2757efad7→a07c92c32 |
| T315/T316、T321/T322 | 23a892255（11fail/2pass）→cae368c0b；091e5c444（4fail/3pass）→a05de576b |
| T323/T324、T326/T327 | 9a912434d→ec74400f9；0b40965fa（6fail）→a68075282 |
| T329/T330、T331–T333、T334–T336 | d3e0aff79（18fail/3pass）→c4cfb645a（21pass）；ef07a7b07→5a129b4b8→9f1711d2d（新28pass）；7ed94d53e（3fail/2pass）→f0e62a30f→cfa1b6934（root19pass） |
| T281、T307/T308 | T280已有行为回归首轮即绿；T307真实tenant pin/default亦首轮即绿，T308只核对无修复提交，不伪造red阶段 |
| T337/T338 | 3fea21d9d（12fail/14pass）→ba4fab043（527378d0a将fixture改为生产SQLModel AsyncSession）；真实C3 listener、缺Context/错pin/bypass/foreign root拒绝及锁语句回归 |
| T290–T292、T293 | 生产装配及ledger阶段/descriptor冻结的基础结构测试/接口验证，不声称业务E2E |
| T296/T297/T325、T298/T299 | 原回归等价适配，不删断言；a42475bf7→900ea6f4b为外部事务名称查询 |

## 未完成与下一波边界

完整F118未完成：WF运行T041/T042、AS共用Agent T283及Info失效原ID/状态T294/T295、其余四类来源写端、真实Coverage adapter、目标删除协调、处理用例/worker、两端页面、正式脚本及全特性验收仍待按依赖实施。下一波先冻结可信SourceExecution/SourceOwner只读scope，再接真实执行enqueue及Info；[实际入口盘点](./execution-entrypoints.md)列出WS任意payload、未保存preview、开放invoke及评测的差异，不能虚构workflow_version来源或改ContextTenant绕过隔离。

非阻断已知限制：助手alist_links尚为非locking SELECT，MySQL RR下root回调不能宣称links current-read；完整协议写会由中央Source/root CAS或业务/index digest保守拒绝并发变化，未发现丢失写路径。后续可用独立红测/任务统一精确冲突分类，不以SQLite证明真实双库并发。线上数据库、FGA、ES/Milvus、Celery执行、正式迁移、CI、E2E及部署均未运行。
