# F025 实施设计

## 已确认目标及评审修订

业务目标来自用户批准的 approved-plan.md。独立架构评审指出两项未完成设计：slot准入的完整性保留、共享意图与接收初始化生产者；以下补实现细节，不改变用户确认的政策。不引入通用恢复框架。

## 1. 默认来源和槽位

保留现有whole-source严格入口不变。新增仅供模型默认owner使用的按槽位执行入口：先由真实owner解析完整payload/完整references；core对完整来源继续检查root_guard、ready、effective、digest、extractor、revision和原身份/事务，二次重读并拒绝漂移；只对该业务选择的已登记槽位所对应目标要求有效。同步/异步一致。调用者只能提交源码静态登记槽位或源中实际配置的模型候选ID，不提交自造目标/来源。完整集合用于索引验证，不重写数据库/旧摘要。标量入口仅返回该槽位ID；需要参数的操作仅返回已准入模型引用与非模型参数，不能传回原整份未准入引用。缺失可选槽位返回None，未知槽位拒绝。沿真实getter消费者逐个接线，元数据展示读与执行准入分开。

移除source read/reference target中的inherited_server_ids授权捷径；继承源的目标资格按请求执行租户核验真实Root共享，不能借源owner为Root获得授权。LLM服务管理候选仅own+真实shared；原继承失效引用在修复诊断单独返回。不要先放宽所有getter，再依靠调用者自觉鉴权。

## 2. 共享权威、接收默认及恢复

新增llm owner独立SQLModel表记录逐提供商共享意图（enabled、version、原操作关联），标准启动只建新表，不回填历史。无记录=历史未知，只保留原实际授权，挂载不推定该提供商已开启。显式开启/关闭通过现有ModelSharingApplication、提供商锁、原actor/command digest和投影台账；完成后记录对应意图，不覆写正在执行的冻结集合。

意图、当前活跃租户、实际共享三者形成可查询覆盖：缺少接收即待补齐，活动计划单独展示；无需另造通用任务系统。新挂载和重新启用读取明确意图，失败保留可重试差异。成员在投影过程中变化不改原计划，原命令完成后新差异由后续原受保护共享命令处理。正在执行的共享保留互斥；失败操作先按下述规则恢复，再允许相反的新命令。

### 2.1 失败操作收尾（2026-11-18）

共享请求失败或取消时，由本次请求持有的确切原计划标识执行机械清理。PREPARING及尚未开始权限I/O的RESERVED共享操作，在提供商锁内将该计划对应的全部PREPARED权限日志和业务预留原子关闭：权限日志转FAILED_CLOSED，业务计划转ABANDONED，保留原actor、command、digest及取消指纹。权限日志的PREPARED→STAGING CAS是外部写入入口，取消成功后晚到Worker无法越过此入口。清理不依赖FGA可用，业务代码不直写权限表。

已有STAGING、COMMIT_UNKNOWN、COMMITTED、FINALIZED或FAILED_CLOSED日志时，不能以失败或超时为由释放围栏。记录retryable_failure，当前有权限的Root超管下一次编辑时按原store/model、原投影日志及冻结AFTER完成权限恢复与SQL收尾，然后执行新命令。原actor和计划摘要不改变，恢复者单独记入ack.recovered_by；恢复不要求原操作者/原凭证仍有效，也不伪造旧身份。FAILED_CLOSED纠正仍要求原业务围栏绑定和权限模块的确认摘要。持续的权限服务故障继续返回实际错误，恢复后可直接重试正常编辑。

进程被终止而未执行清理时，以最后更新时间超过5分钟作为允许检查恢复的条件；它不是删除未知写入的TTL。下一次授权写入先核验日志，未开始的共享/删除准备预留可取消，已开始的共享恢复后收尾。正常模型删除/移除的已交接业务执行计划仍走其原有受保护事务及引用目标校验，不由共享清理器解锁。GET仅返回活动记录的诊断字段，不把历史执行摘要校验作为读取表单的条件；写入时仍进行完整核验。

选择即时失败收尾加按需恢复，而不是给所有围栏统一过期释放：后者无法区分未写入和已经变更的权限。没有新增任务表、后台轮询或Redis锁。已知坑：HTTP失败并不撤销先前已提交的PREPARING记录；只校验原actor/原命令会把历史故障变成永久阻断，在model_operation_recovery和ModelSharingApplication处理。若将来外部执行超过5分钟且需要延长活跃窗口，再增加真实执行心跳，而非扩大盲目解锁范围。

ABANDONED仅是已取消且可供原挂载流程识别的失败回执，不在活动集合中。接纳任意新的共享命令时，在同一提供商事务内将旧ABANDONED标记SUPERSEDED，防止后续重试已被新命令替代的挂载。签名载荷及原取消审计不变。挂载重试须再次验证真实部门/租户挂载关系和当前Root超管，创建新计划；无关或已经替代的历史记录不阻塞新挂载。

接收默认初始化只针对本次冻结的新增接收模型集合；写入在现有SQL事务中、采用接收租户策略锁及唯一约束，仅缺省行可创建，已有管理员限制不覆盖。历史已共享无记录不自动初始化；失败重试仍使用原初始化集合，若管理员中途写了限制，重试跳过该行。新模型创建在同一提供商锁下读取明确共享意图，对已授权接收者的新模型补缺省规则。DSH规则由其公开application/service边界写入，llm/tenant不直写DSH表。

实际新增两张独立表：`llm_model_sharing_intent`（server_id、tenant_id、enabled、version、plan_id）与`llm_model_sharing_initialization`（plan_id、tenant_id、server_id、child_ids、model_ids）。意图与原计划COMPLETED在同一SQL事务提交；receipt独立冻结初始化范围，不改变旧metadata/digest。两表通过标准模型发现建表，模块显式登记tenant_filter，缺省tenant由既有before_flush填入；Root仓储仍明确写已验证Root。没有旧结构DDL或历史数据回填。实际覆盖读取join仍存在的Root提供商，删除后的审计记录不成为新挂载来源。

FGA网络读/写不在持有SQL业务事务时发生：原prepared共享使用冻结AFTER；legacy增量新增模型先在事务外读取实际接收者，再在provider锁内复核intent版本，漂移则拒绝重试，不能用过期接收集合发布新模型。

## 3. 图片与价格

图片权威沿用owner的dsh_vision:{owner}:{model}；子租户显式dsh键为收紧override，最终=owner能力 AND 本地限制。旧无dsh键时读取同租户原workbench.models[].visual作为兼容证据；显式dsh false优先，旧visual false视为关闭，未知不默认开启。DSH和非DSH管理及调用统一同一服务解析，不在GET/启动迁移数据。子租户不能把owner false改true。批量读取返回source/effective/can_edit；Root共享价格只读，倍率保留服务端计算，积分设置保持独立。

历史图片键优先级（只读解析，不迁移）：

| owner dsh | owner旧本地visual | 基础能力 |
|---|---|---|
| false | 任意 | false |
| true（历史无版本） | false | false |
| true（历史无版本） | true/缺省 | true |
| 缺省 | true | true |
| 缺省 | false/缺省 | false |

child无本地dsh和visual时继承基础；任一历史显式false作为本地限制；true不能越过owner false。Root/owner明确保存后写`authority_version=1`，该新权威值替代同租户旧visual证据，允许管理员修复历史冲突；child仍与owner基础取AND。GET不会保存或补齐任何键。两模式都由同一vision服务解析，管理元数据不对无关默认槽位执行准入。批量读取仅将已知无权转为行诊断，权限服务异常让整个请求失败。

## 4. 管理诊断与UI

新增管理只读诊断入口，auth沿既有当前租户配置管理员边界；一次返回五栏目引用的slot/model/status与来源，不含密钥。原五GET/POST响应兼容。UI显示当前栏目来源、失效项和恢复继承，保存校验继续后端owner。列表仅真实可用候选，诊断另列不可用原配置。scope变化重挂载页面，查询key含身份和管理租户，图片/定价按页批量，禁止逐行失败弹窗。继承转本地仅保存时发生，草稿标记不掩盖实际来源。工具只在真实可管理范围展示。

`GET /llm/system-settings`诊断修复引用，Root按需`include_impact=true`核对继承且无本地覆盖的活跃子租户共享差异；child不返回其它租户影响。`GET /llm/{id}/sharing-status`仅Root超管查询意图/实际覆盖/原计划。`POST /dsh/admin/model-vision`最多200模型；界面每100模型分块，无逐行请求。恢复继承复用原`/llm/settings/defaults/{key}/inheritance`，只重挂当前栏目。保存成功重读当前来源及诊断/影响，不丢其它栏目草稿；失败不改变来源。Workbench不可用metadata显式移除、image_read_model可修改或清空，禁止自动剔除再保存。

后台新保存的所选现存模型统一校验槽位类型/上线；同源历史tombstone引用仍须原receipt证明才能保留作修复，不能作为新引用或执行资格。运行DTO逐槽位过滤已知失效可选模型，管理DTO仍保留原值。Chat/Work主动选模在真实用户候选中核对显式ID，不用内部摘要等任务的模型权限替代用户可见范围，也不将Chat可见限制套到内部任务。

## 5. 边界、验证和重审

C1：权限tuple只由permission owner写；C2：新表/SQL用通用类型，DM8中央验收；C3：跨租户接收初始化须明确授权目标且事务中绑定原管理身份；C4：只共享事实可授权，不读写role_access。旧计划、旧引用digest、额度及价格公式不变。若需要字段级混合继承、Root统一积分、任意条件共享或自动恢复历史意图，另行确认设计。

后端native SQLite+隔离HTTP覆盖真实owner/身份/事务和相反命令；前端vitest覆盖来源、诊断、只读共享价格和租户切换；lint/typecheck/i18n/build、架构守卫、E2E清单和独立代码审查。真实116/DM8/多进程验收单列，不把mock测试当部署。

## 修订历史

2026-11-18：按用户要求修复失败共享永久占用；增加即时取消、跨授权管理员的冻结计划恢复、过期遗留检查与挂载失败回执，GET不再把旧执行摘要作为表单读取闸。

2026-11-18：用户授权评审通过后开发；独立设计复审PROCEED。实施复查修复Root状态服务实例接线、失效引用修复入口、保存来源/影响刷新、保存槽位检查、运行语音DTO及普通用户显式选模。最终独立代码审查PASS；实际检查与遗留基线见validation.md及quality-baseline.json。
