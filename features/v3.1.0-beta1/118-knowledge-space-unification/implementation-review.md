# W0/W1实施集成与L1任务审查

**日期**：2026-11-05 · **当前源码快照**：`9300b557cfbac985a51421272b80ad931a011575`  
**状态**：W0/W1核心已合流，86/273项完成；整体仍在开发，本记录不等于整特性L2、E2E或发行验收。
**组合受测提交**：`4932d120de0381870d672588f0d14fdfaf6d16fe`；其后`9300b557c`仅删T270文件尾空行，无语义变化。

## 基线与Owner

主工作区`feat/3.1.0-beta1`保持原状；功能分支`codex/3.1.0-beta1/118-knowledge-space-unification`以文档checkpoint`0b80802ae`保留原内容，合入远端`9eef0016de`为`a1b1a2387`。三个lane从冻结合同`ed03fd07de`创建，按依赖快照合流，未推送或部署。

| 责任 | 独立路径/交付边界 | 本轮集成 |
| --- | --- | --- |
| INT/MIG主agent | 基线、合同、错误/HTTP、tenant登记、既有表DDL、统一验证 | W0及公共装配已完成本地验证 |
| REF agent | 引用类型、Repository、Owner核验/收据、失效解析、覆盖Port | `ac5e8739a`由PROC复核，合流`64490b9bb` |
| PROC agent | 默认解析、事务CAS、job/item租约与retry收据 | `ff2672e983`由REF复核，合流`e93ecfb6a` |
| PERM agent | 全平台use退役、目标化纯可见快照、Catalog持久链 | `c970545d3`经REF/PROC分阶段复核，合流`4932d120de`；纯可见/完整性/正常startup接缝均闭合 |

## 已闭合的交叉审查问题

| 问题 | 修正与回归 | 状态 |
| --- | --- | --- |
| 调用方自报Owner已核验目标/伪造receipt | Verifier实际调用注册Owner，登记本事务原对象；Bindings/共享反查同Verifier消费，替换字段/跨Verifier/旧事务拒绝 | 已闭合，T253–T256；独立39项通过 |
| DELETING目标仍可改变来源集合，干扰原删除计划续跑 | 完整旧/新receipt任一删除中即10999；业务/refs/root整笔回滚；正式删除后部分修复保持 | 已闭合，T257–T258；增补8项，独立组合47项通过 |
| 当前字符分隔符空串fallback被新DTO拒绝 | 保留既有合法规则，空列表/类型/长度限制保持 | 已闭合，T233–T234 |
| 公共KnowledgeBase不应携带内部版本/迁移字段 | 字段移到实体Knowledge，不扩大旧公共DTO | 已闭合，结构与旧模型序列化回归 |
| item完成被误当业务完成 | item只计数，Owner业务切换后显式finalize，配置失配先持久提交再报obsolete | Repository已闭合；Owner接线待后续任务 |
| 创建前DTO不按目标、marker临时加动作后丢来源 | target-scoped prospective与post-create一致，types/level持续作为provenance，真实Catalog两轮保存后Source REMOVE成功 | 已闭合，T247–T250/T259；REF固定77901ab05复核3项 |
| SQL Scope损坏仍ready/静态回退、startup会改坏合法窄scope | 按正式发布算法核对canonical，去静态fallback；启动删除自动补CURRENT的调用与死helper | 已闭合，T251–T252/T269–T270；PROC两次固定快照8项、11项复核 |
| 编码+7/空白7路径漏管理租户pin | 真实ASGI缺header400/不匹配409/匹配200；普通文件/v2范围不扩 | 已闭合，T265–T266 |
| 原始ORM经旧create Any envelope输出私有字段 | 六字段统一exclude JSON，真实旧create序列化与SQL回读双验证 | 已闭合，T267–T268；REF与管理pin等定向31项通过 |
| 通用10995提示误导无force场景、旧Skill注入fixture本身已坏 | 三语中性提示；基线归档复现后仅Skill断言改用现存runtime接口，其他9类校验保留 | 已闭合，T261–T262/T273 |


以上收据问题是内部应用合同的绕过复现，未声称存在已暴露HTTP入口或线上利用。

## L1检查口径

按项目`task-review`的七项检查执行，按任务类型选择适用项。当前constitution/AGENTS优先于旧清单示例：Repository接受外部Session；SELECT自动tenant过滤，bulk写显式可信tenant；ORM从SQLModelSerializable继承；当前两端状态栈保持各自AGENTS约定。新表已登记tenant自动注入和模型发现；不可变retry收据也保留create_time/update_time。

| 检查 | 当前结论 | 证据/限度 |
| --- | --- | --- |
| 1 架构分层 | PASS | REF不导入业务ORM，Verifier经Port；业务SQL在Repository；公共注册不反向导入业务Service |
| 2 命名 | PASS | sync/async配对、错误码及字段按冻结合同；旧文件命名保留兼容 |
| 3 序列化 | PASS | 内部dataclass无HTTP裸露，ORM继承统一基类，旧KnowledgeBase字段不扩展；公开Endpoint待后续任务 |
| 4 数据库 | PASS_WITH_NOTES | 外部Session无内部commit，SQLite事务/唯一约束和MySQL DDL编译通过；真实双库行锁/DDL未验证 |
| 5 前端约定 | PASS/N/A | 仅三语api_errors变更，i18n检查通过；未实现两端页面 |
| 6 信息泄漏 | PASS | actor仅可信引用与收窄摘要，未存token；共享引用查询Port不公开客户端tenant/bypass；返回裁剪待Owner接线 |
| 7 设计同步 | PASS | design §15、contracts V1.1、升级说明§10及HTML当前进度同步；产品94 AC不变 |

测试任务仅采用命名、AC格式及适用i18n检查；其余N/A。基础定义采用1/4/6/7，其他实现采用全套适用检查。本地验证不替代集成环境门禁。

## 已完成任务元数据审查

文件范围、配对测试、依赖逐项校验；当前完成 86/273。列出的源文件均存在，依赖DAG无环，每卡最多2路径。新增卡编号不代表拓扑顺序。

| 任务 | 名称 | 文件/配对/依赖 | L1结果 |
| --- | --- | --- | --- |
| T001 | 开发基线、文件 Owner 与入口清单 | PASS / 按卡适用 / PASS | PASS |
| T002 | 冻结 R1/R2/R3/J1/A1/P1 合同 V1 | PASS / 按卡适用 / PASS | PASS |
| T003 | 来源/目标与替换 DTO | PASS / 按卡适用 / PASS | PASS |
| T004 | 引用明细与零引用集合 SQLModel | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T005 | 目标删除标记 SQLModel | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T006 | 纯可见快照字段和兼容序列化 | PASS / 按卡适用 / PASS | PASS |
| T007 | 分类型默认与任务公开 DTO | PASS / 按卡适用 / PASS | PASS |
| T008 | 任务/子项 SQLModel | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T009 | 既有表字段与 Alembic 唯一编排 | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T010 | 迁移账本 SQLModel | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T011 | 新模块租户注册 | PASS / 按卡适用 / PASS | PASS |
| T012 | 错误码与测试基础 | PASS / 按卡适用 / PASS | PASS |
| T013 | 来源集合与目标反查 Repository：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T014 | 来源集合与目标反查 Repository | PASS / 按卡适用 / PASS | PASS |
| T015 | 同 Session 原子替换与来源 CAS：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T016 | 同 Session 原子替换与来源 CAS | PASS / 按卡适用 / PASS | PASS |
| T017 | 目标失效判定与覆盖就绪：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T018 | 目标失效判定与覆盖就绪 | PASS / 按卡适用 / PASS | PASS |
| T019 | 移除活动 use 与合法纯可见模型：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T020 | 移除活动 use 与合法纯可见模型 | PASS / 按卡适用 / PASS | PASS |
| T021 | 纯可见授权可授予、列表与撤销：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T022 | 纯可见授权可授予、列表与撤销 | PASS / 按卡适用 / PASS | PASS |
| T023 | 可见性编译与 F048 模型发布：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T024 | 可见性编译与 F048 模型发布 | PASS / 按卡适用 / PASS | PASS |
| T025 | 运行协议与旧 use 表达兼容：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T026 | 运行协议与旧 use 表达兼容 | PASS / 按卡适用 / PASS | PASS |
| T027 | 投影运行时快照与 checksum：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T028 | 投影运行时快照与 checksum | PASS / 按卡适用 / PASS | PASS |
| T059 | 默认配置 Repository 与优先级：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T060 | 默认配置 Repository 与优先级 | PASS / 按卡适用 / PASS | PASS |
| T061 | 任务与子项存储：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T062 | 任务与子项存储 | PASS / 按卡适用 / PASS | PASS |
| T214 | PermissionModel持久字段与内部派生结构 | PASS / 按卡适用 / PASS | PASS |
| T215 | GrantSource合法纯可见与目标化快照：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T216 | GrantSource目标化快照与合法空动作guard | PASS / 按卡适用 / PASS | PASS |
| T217 | Catalog持久/当前快照往返：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T218 | Catalog与运行控制层快照接线 | PASS / 按卡适用 / PASS | PASS |
| T219 | 持久确认计划SQLModel | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T220 | 高级管理写可信租户防竞态：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T221 | 高级管理写scope接线 | PASS / 按卡适用 / PASS | PASS |
| T228 | 跨lane结构与DDL集成验证 | PASS / 按卡适用 / PASS | PASS |
| T229 | F118错误HTTP状态：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T230 | F118错误v2状态接线 | PASS / 按卡适用 / PASS | PASS |
| T231 | 错误三语源：中文与英文 | PASS / 按卡适用 / PASS | PASS |
| T232 | 错误三语源：日文 | PASS / 按卡适用 / PASS | PASS |
| T233 | 合法字符切分兜底：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T234 | 保留空分隔符合法能力 | PASS / 按卡适用 / PASS | PASS |
| T235 | 全新安装viewer：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T236 | 新安装标准可见模型初始化 | PASS / 按卡适用 / PASS | PASS |
| T237 | 资源实际权限DTO：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T238 | 资源API目标化模型输出 | PASS / 按卡适用 / PASS | PASS |
| T239 | 当前动作/新安装既有回归适配 | PASS / 按卡适用 / PASS | PASS |
| T240 | 当前inactive来源/可见并集回归适配 | PASS / 按卡适用 / PASS | PASS |
| T241 | 当前FGA模型回归适配 | PASS / 按卡适用 / PASS | PASS |
| T242 | 当前累积模型/预设回归适配 | PASS / 按卡适用 / PASS | PASS |
| T243 | 模型切换业务配置结构 | PASS / 按卡适用 / PASS | PASS |
| T244 | 模型切换fixture结构对齐 | PASS / 按卡适用 / PASS | PASS |
| T245 | 独立重试幂等收据SQLModel | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T246 | 重试收据租户注册 | PASS / 按卡适用 / PASS | PASS |
| T247 | 创建前目标化授权DTO：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T248 | 创建前授权目标快照接线 | PASS / 按卡适用 / PASS | PASS |
| T249 | 受控可见标记动作往返：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T250 | 保留纯可见provenance | PASS / 按卡适用 / PASS | PASS |
| T251 | CURRENT Scope完整性：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T252 | CURRENT canonical完整性校验 | PASS / 按卡适用 / PASS | PASS |
| T253 | Owner核验收据来源：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T254 | 受信Verifier签发同事务收据 | PASS / 按卡适用 / PASS | PASS |
| T255 | 绑定与共享反查消费受信收据 | PASS / 按卡适用 / PASS | PASS |
| T256 | 引用测试接入真实核验链 | PASS / 按卡适用 / PASS | PASS |
| T257 | 删除中目标的同步写围栏：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T258 | 冻结删除计划期间引用写入 | PASS / 按卡适用 / PASS | PASS |
| T259 | 创建前授权Runtime Port签名对齐 | PASS / 按卡适用 / PASS | PASS |
| T260 | 重试收据通用审计字段 | PASS / 按卡适用 / PASS | PASS_WITH_NOTES |
| T261 | 通用引用阻断中英文提示 | PASS / 按卡适用 / PASS | PASS |
| T262 | 通用引用阻断日语提示 | PASS / 按卡适用 / PASS | PASS |
| T263 | CURRENT真实发布hash回归适配 | PASS / 按卡适用 / PASS | PASS |
| T264 | provenance与prospective回归适配 | PASS / 按卡适用 / PASS | PASS |
| T265 | 等价整数URL管理租户pin：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T266 | 高级管理路径范围完整匹配 | PASS / 按卡适用 / PASS | PASS |
| T267 | 旧create原始ORM出站隔离：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T268 | Knowledge内部列统一排除wire输出 | PASS / 按卡适用 / PASS | PASS |
| T269 | 正常启动不改已发布CURRENT：先写测试 | PASS / 按卡适用 / PASS | PASS |
| T270 | 停用启动时在线补CURRENT范围 | PASS / 按卡适用 / PASS | PASS |
| T271 | 既有授权roster显式scope回归适配 | PASS / 按卡适用 / PASS | PASS |
| T272 | 新安装Skill范围与退役helper回归适配 | PASS / 按卡适用 / PASS | PASS |
| T273 | 既有API Runtime注入断言适配 | PASS / 按卡适用 / PASS | PASS |

## 实际验证与待执行

- 主agent最终在4932d120de运行24个pytest路径（含完整F118目录及权限/API/Worker相关回归）：**424 passed，0 failed，0 skipped**，6.33秒；727条依赖/弃用warnings原样保留在日志。此前108/126/136为中间快照，不与本次相加。
- [完整本地日志](/private/tmp/f118-integrated-tests.log) · [受测SHA与路径清单](/private/tmp/f118-integrated-tests.json) · [PERM独立lane交付记录](/private/tmp/f118-perm-delivery.md)。主agent命令为共享venv的`python -m pytest <json.paths> -q --tb=short --disable-warnings`，PYTHONPATH指功能src/backend，config仅引用主工作区既有只读路径，未修改环境或锁文件。
- `alembic heads`唯一输出`f118_knowledge_unification`；没有连接真实数据库执行upgrade。
- `node scripts/check-i18n.mjs`通过；85条既有frontend-only key仅信息提示。
- Knowledge实体/旧错误文件原有ruff诊断已与冻结基线按code/message/源码行比对，新增0；不批量改无关历史代码。最终80个改动Python文件arch-guard无违规，78个文件ruff通过；两旧文件为24/2条既有诊断且新增0。完整提交区间与文档工作区diff-check通过；HTML 13 SVG/唯一ID/本地链接及全部273任务依赖DAG/94 AC索引检查通过。
- **未执行**：真实MySQL/DM8的DDL与并发行锁，OpenFGA投影，ES/Milvus/MinIO/Celery真实链路，六类来源业务接线E2E、迁移回填/备份恢复演练、CI及部署。

## 下一依赖波

已向后续业务Owner发布主集成的V1.1装配签名与目标化权限接口，下一波按任务依赖接入六类来源、处理应用用例及删除协调。热点文件仍唯一Owner；公共router、migration、错误装配由INT/MIG统一。Coverage Port缺少持久adapter时保持不可用，不启用删除保护。

完整性检查的检测点为current_catalog及启动/heartbeat绑定；未新增每个原始SQL loader/每次Check全目录实时校验。现有CURRENT仅经受控发布或停服迁移变更，发布外SQL损坏在后续校验点发现。该限制不用于放宽缺Scope、损坏checksum或未ready时的发布/启动门禁。

本轮三个lane均已交付，未派发未说明的后台任务。主工作区仍干净且未切分支；本地功能提交不等于远端、CI、部署或迁移结果。
