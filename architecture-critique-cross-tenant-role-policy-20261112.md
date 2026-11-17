**REVISE：交接说明准确揭示了问题，但尚不能作为实施设计；主要缺口是共享语义、行政划分例外及承接事务/重试协议。** 以下红项属于实施准备缺口，不表示交接文件已经批准了错误方案。

| 维度 | 评分 | 判断 |
| --- | --- | --- |
| 1. 需求与质量属性 | 🟡 | 安全、连续可用和最小影响清晰；跨租户共享是否确为产品需求尚未决定。 |
| 2. 边界与耦合 | 🟢 | 正确分开定义、部门资格、人员绑定、管理员身份及资源授权。 |
| 3. 模式克制 | 🟢 | 排除全平台恢复中心、全目录复制等扩大方案，符合最小改动要求。 |
| 4. 数据与状态 | 🔴 | 提出“划分前取原有效策略”，却未定义源事实如何跨清理、主属更新和失败重试存活。 |
| 5. 变化容忍/YAGNI | 🟢 | 可以沿用现有双类型及有效策略入口，无理由引入通用角色继承框架。 |
| 6. 故障与规模 | 🔴 | 当前链路存在提交后失去源绑定及重试提前退出；候选承接尚无具体闭环。 |
| 7. 决策记录 | 🟢 | 明确标注未批准候选、现场证据局限和合同冲突；作为交接材料是合格的。 |

### blocker：实施前必须决定

**1. “行政划分保留策略”是合同变更，不能包装为单纯修Bug。**

- **锚点：**交接 §5 第99、106行；[spec.md 第65行](/Users/zhangguoqing/works/bisheng/features/v3.1.0-beta1/009-managed-tenant-consistency/spec.md:65)；[scope-revision.md 第32行](/Users/zhangguoqing/works/bisheng/features/v3.1.0-beta1/009-managed-tenant-consistency/scope-revision.md:32)。
- **问题：**已确认合同要求主属变化终止旧普通绑定，禁止自动搬迁旧global绑定。当前登录丢角色可能是这个合同的直接结果，不能一概称为实现错误。
- **方向：**先确认是否增加“同一工作部门被行政划为租户”的限定例外，写清触发入口、受影响人员、旧→新策略映射及目标管理员授权；真正调岗、回迁继续按AC-12处理。不能只在通用`sync_user`中按角色类型保留。

**2. 自动承接候选缺少源事实与完成状态协议，直接实现会丢授权或复活撤权。**

- **锚点：**交接 §4-B 第71行、§6 第113～115行；[tenant_creation.py 第38行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/tenant/application/tenant_creation.py:38)先更新挂载关系，随后第46行删除失效绑定；[user_tenant_sync_service.py 第124行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py:124)再次终止绑定，再切Home及发默认角色；[policy_binding_repository.py 第314行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/user/domain/repositories/policy_binding_repository.py:314)确认终止操作独立提交。
- **问题：**“先保存一个列表，最后补角色”不足以成立。进程在两步间失败，源列表消失；把旧列表持久保存后反复补发，又可能恢复期间已撤销的权限。Home切换成功而默认授予失败时，[第95行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py:95)的同Home提前返回也不会续办。
- **方向：**选定承接后，明确由同一Owner控制旧事实读取、拓扑变化、Home和绑定写入的SQL边界；能在一个事务内完成就优先如此。若允许分步，必须明确操作身份、已完成事实和重试终态。不要将新逻辑附加在会再次清空绑定的现有同步步骤之后。

### should-fix

**3. 超管资格正在隐式决定共享范围；应优先消除这个耦合。**

- **锚点：**交接 §5 第91行；[role_service.py 第65行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/role/domain/services/role_service.py:65)、第115行按`is_admin()`自动创建global；[role_schema.py 第13行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/role/domain/schemas/role_schema.py:13)没有共享范围字段。
- **问题：**超管在某租户中代建普通角色，得到的却可能是所有租户可复用定义。操作者权限和目标角色共享范围是两个独立事实。
- **方向：**普通角色归明确目标租户；“该租户全部部门”继续用`department_id=None`表达。若确有集团统一策略需求，另外显式选择现有global类型并标注为“平台共享角色”。可复用现有字段，不需要新角色层级或继承引擎。

**4. 保留共享定义意味着接受集中变更半径，这个代价尚未进入选项比较。**

- **锚点：**交接 §5 第87行；[effective_roles.py 第34行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/role/application/effective_roles.py:34)允许global跨任意租户；[effective_role_repository.py 第12行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/role/domain/repositories/effective_role_repository.py:12)读取同一角色定义菜单；[role_definition_repository.py 第85行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/role/domain/repositories/role_definition_repository.py:85)直接更新定义。
- **问题：**同ID复用意味着一次菜单、额度或作用域调整影响所有使用该定义的租户；“租户只读”并不等于“租户政策独立”。反之，复制角色会产生以后互不联动的副本。
- **方向：**把“集团集中维护、所有引用即时跟随”与“租户独立维护、一次性模板复制”列为产品选择依据。不要为了统一名称再引入自动同步、父子角色继承或版本分叉系统。

**5. 缺少一个更小的候选：预检阻止失去入口，明确配置后再划分。**

- **锚点：**交接 §5 第95～104行主要比较自动承接和模板复制；§7 第126行要求人员有明确承接结果。
- **问题：**自动承接不是避免坏账号的唯一办法。若组织划分操作低频，加入可恢复批量复制/映射机制可能比业务需求更复杂。
- **方向：**补充候选：预览本次真正变Home人员及其目标合法策略，发现无入口人员就不提交；管理员明确选择目标角色或默认配置后重算并提交。只有产品明确要求“划分时自动保留原策略”时，才增加限定的global重归属或选定私有角色复制。

### nit

**6. 登录入口可用性应验证“有可用菜单”，不能仅验证“有角色”。**

- **锚点：**交接 §4-B 第69行、§7 第124行；[user.py 第538行](/Users/zhangguoqing/works/bisheng/src/backend/bisheng/user/domain/services/user.py:538)明确同时存在无角色和无有效入口菜单两类拒绝条件。
- **方向：**验收“角色承接成功”时同时覆盖登录、有效菜单和所选业务入口；保留无角色用户原状，不自动给全员发保底角色。

建议采用的最小结构是：**租户角色默认独立，部门范围与跨租户共享明确分开；共享角色仅在确有集团统一策略需求时显式使用；划分租户先预检，再按选定合同承接。** 历史修正则独立生成有限变更清单，依据可确认授予意图处理，不能从残留Root行推导当前授权。此评审为建议，不是实施门禁。
