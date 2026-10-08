# F062 逐模型额度修订与验收

> 历史记录：2026-09-09 用户后续取消 UNKNOWN 冻结及部门同步/筛选；当前语义以 [0.3.0 修订](./usage-and-search-revision.md) 和 design.md 为准。本页旧测试结果不代表修订后的验证结果。

日期：2026-09-09。依据用户本轮确认：每用户可配置多个模型，各用户/模型组合独立月额度；一期不支持限流；配置对象须定义字段含义；毕昇新增业务不手写 SQL，Gateway 沿用现有 Mapper 风格并审查 DM 兼容性，DM 实机本轮暂缓。改动留在两仓指定开发分支，未提交、推送或部署。

## 当前实现

| 边界 | 已落实行为 |
|---|---|
| 主配置 | `Settings.dsh: DshSettings`，模型能力为 `ChatCapabilities`，API/Worker共用；字段类型、描述、边界、默认关闭及密钥脱敏均有检查 |
| 用户配置 | 管理 GET/PUT 的 `models` 为 `DshModelQuotaConfig[]`，每项仅 `model_id`（正整数、用户内唯一）与 `monthly_token_limit`（非负 int64、token/月，0仅禁该模型新调用）；没有顶层共享额度或 RPM/TPM/并发字段 |
| 持久化与审计 | 已由 2026-09-10 [单行授权修订](./model-policy-row-revision.md) 替代：每个用户模型一条记录、独立 CAS；JSON 仅用于操作审计及恢复证据，不用于额度配置存储 |
| 准入与结算 | Lua按所选模型已实际入账用量判断，额度不可互借；在途可超额并如实结算，移除模型不删历史；UNKNOWN仍按用户保守阻断 |
| 恢复 | 新月证明、恢复摘要/回执、SQL epoch CAS均绑定完整逐模型配置；旧聚合证明拒绝，冻结至SQL提交后才READY |
| 视图 | 每模型显示使用量、额度、剩余；缺失计数为不可用，显式0才展示0。汇总remaining为各模型非负剩余之和；管理用量的计数与额度取同一快照 |
| 客户端 | 契约从0.1.0升至 **0.2.0**，config/管理解析器/两仓契约fixture同步。`GET /api/v1/dsh/usage?model=bisheng:<id>` 返回单模型范围；无参数仅汇总展示。读取策略失败返回503，未授权模型403，缺少模型计数返回不可用 |
| SQL边界 | 毕昇业务查询使用ORM，DDL默认值/约束及方言适配保留；Gateway DM设备名列扩到400字节，席位短事务READ_COMMITTED＋首条EXCLUSIVE表锁；MySQL保留SERIALIZABLE |

## 实际验证

下列是不同命令的真实范围，有重叠，不相加为整套总数。

- 策略/管理集成初跑80通过、10失败；失败为并行实施时Redis适配器仍使用旧参数。迁移适配器后对应10项全部通过，实际MySQL/Redis验证逐模型100/200及信息总和300；没有将失败初跑描述为全绿。
- 配额、恢复、Worker、跨进程及独占Redis生命周期联合 **68通过（40.47秒）**；随后逐模型文件 **7通过（1.26秒）**，后者含3项新增SQL/新月/移除模型回归。包含真实MySQL/Redis/MinIO与10,001请求恢复，见 [配额记录](./python-quota-progress.md)。
- 最终API/管理视图/基础契约/类型配置/SQL可移植性范围 **41通过、2跳过（4.42秒）**：`test_models_api.py`、`test_admin_api.py`、`test_foundation.py`、`test_sql_portability.py`、`test_config_contracts.py`。两项跳过为未安装真实DM SQLAlchemy编译器，不是通过。另类型配置/运行时专项此前39通过、3未选。
- 真实MySQL8.0.46用户版本迁移 **1通过（0.32秒）**；两次升级、旧行默认0、非空BIGINT、降级保留版本7及默认值均验证。独占测试库前后表数均0，见 [数据库验收](./database-acceptance.md)。
- 契约升级后Gateway `Dsh*Test,LicenseStatusHolderTest,LicenseExpiredGlobalFilterTest` 排除scale执行package，**57通过、0失败/错误/跳过，BUILD SUCCESS**。其中9项SQL兼容检查覆盖DM分页/CLOB/字节容量及锁分支；使用真实MySQL/Redis的用例没有跳过。既往独立五万席位scale结果保留，未重新计入57项。
- 契约升级后的Platform API及DSH管理目录 **6文件30测试通过**，Platform typecheck与定向ESLint通过。此前逐模型UI改动已运行全前端lint/typecheck/check-i18n通过；缺失计数修复单独9项通过。没有宣称执行真实Desktop联调。
- 新DSH、Worker、测试、配置对象、资料Repository、迁移及错误码Ruff检查通过；修改/新增源码152文件Architecture Guard为0 VIOLATION、2既有WARNING。扩大到已触及的全部旧后端文件时有122条存量Ruff告警，同文件HEAD为159条，按文件/规则计数无新增；不宣称全后端lint通过。最终修改/新增Python格式检查、两仓diff检查通过；JSON、HTML本地链接/唯一锚点及客户端七张时序图结构检查通过。

## SDD 增量复核

按sdd-review设计24项清单复核本轮变更并修复：页首仍宣称未实现；DM范围锁假设及设备名容量落后于代码；旧共享额度/审计快照字段；客户端语义改变却沿用版本；任务DM实机门禁未反映用户豁免。Design当前状态、决策D9/D10、表结构、接口表、部署准备、客户端附件与HTML均已同步。

- 目标与约束（1–4）：逐模型额度及一期无限流明确；遵循Constitution C1–C8，C2兼容性保留，DM实机按用户授权暂缓。
- 决策（5–8）：记录共享额度备选被用户明确否定、对象列表/CAS的原因；DM锁选型说明依据、代价与重评触发。
- 现状与字段（9–12）：当前两仓接线、typed对象、模型准入/汇总职责及0.2.0契约一致。
- 坑与依赖（13–18）：未知计数不为0、不能从共享额度猜各模型限额、旧证明拒绝、客户端版本影响与旧License外部证据明确。
- 验证与一致性（19–24）：真实存储结果与跳过单列；部署步骤、历史修订及T117–T122映射齐全。此为已确认范围内实现修订，不重复请求既有授权。

增量设计结论：LGTM。该结论不等于旧发行二进制、DM实机或真实部署验收通过。

## 客户端交接与剩余外部验收

交付 [客户端接口文档及七张时序图](./client-api.md)、[0.2.0契约](./contracts/client-0.2.0.json) 和 [联调清单](./desktop-handoff-checklist.md)。选择/切换模型、调用正常结束和月额度拒绝后查询对应模型；不按汇总remaining禁用全部模型。旧0.1.0 JSON仅供差异审阅，不支持旧共享池运行时。客户端接收确认、版本适配及真实联调仍待执行，本任务未向外部团队发送消息。

DM实机本轮暂缓且不阻塞本轮开发。目标旧Gateway已发行制品/发行工具与授权密文样本、真实Nginx/Desktop/供应商联调及部署负载/切换仍缺现场证据；旧License新Loader回归已通过，但不冒充所有历史二进制的双向兼容验证。
