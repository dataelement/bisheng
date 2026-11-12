# F118 已有结构失效保留与原可见授权兼容审查

基线 cacbec62bb；2026-11-11。用户已明确确认 AC-100–102 与精确失效元数据清理范围。本增量不代表整套F118验收。

| 维度 | 结论 | 证据 |
| --- | --- | --- |
| Boundary Conditions | PASS | 原type3空空间、真实creator.exists=false及SQL零文件数绑定原资源摘要；FAILED space_upload单层缺目录、原行不变且SQL/FGA授权均0才保留。常规转换、父恢复/状态/身份/权限漂移和直接引用失效文件拒绝。 |
| Permission & Auth | PASS | 完整原Store与六类来源闭合证明，不创建用户/创建者授权、目录或继承；现有空间只保留ACTIVE、完整唯一原可见来源和相同等级/allow_same_level，前后可见编译无增删。 |
| Concurrency Safety | PASS | M3在所有租户业务写入前检查；外部FGA读取关闭SQLSession，再开新事务重验SQL及Catalog/pin；续跑相同。原缺失创建者不能被其他来源借用。 |
| Information Leakage | PASS | 只有内部摘要、原ID和事实；没有新HTTP/API、凭据或配置披露。原用户/目标不存在仍如实记录。 |
| Test Coverage | PASS_WITH_WARNINGS | 扩展选集1786 passed / 1既知频道配额no-network基线失败；最终关键95 passed，含完整native M2/M3/M4、续跑、事实漂移拒绝及其他来源借用/直接引用拒绝。 |
| Code Style | PASS | Ruff、diff-check与全部变更Python文件架构guard通过；权限测试夹具经permission.application所有者接口取得模型合同，不反向依赖Core传输。 |
| Docs Sync | PASS | 用户已确认的AC-100–102、design、release-contract、tasks和八列QA TC-KSU-151–157同步；现场清理与未完成升级状态如实另记。 |

SQL查询均为通用SQLAlchemy、有界原生tenant查询；无DDL、新依赖或新授权入口。真实DM8事务未在本机验证；现场MySQL停服升级和访问恢复将另行记录。对遗留坏文件仍可按通常迁移登记V1元数据，文件原行/路径与不可访问性保持；存在直接业务引用时保持阻断。正常type0转空间仍要求真实创建者，既有type3例外不产生owner/成员初始化命令。

运维清理是独立、用户明确授权的既定ID选集：全量读取142855原tuple、逐项原生SQL下游核验，备份1951行、1952原键与8个有效修复上下文并宿主机校验。执行使用原Catalog/model pin、原生ProjectionService和mode版本围栏，336个新增审计操作2777–3112全部FINALIZED后，最终原生事务重验原行并删除1951元数据、修8个level计数。没有FGA WRITE、文件移动、索引/对象业务数据操作或历史Operation/Tuple删除。不能将这些现场证据称为整个环境或物理向量内容备份。

Overall: PASS_WITH_WARNINGS（保留原测试基线与现场尚未完成的发布/恢复验收边界）
