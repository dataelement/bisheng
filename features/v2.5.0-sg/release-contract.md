# Release Contract — v2.5.0-sg

> 本文件是首钢定制版本 v2.5.0-sg 的领域归属与全局约束权威来源。
> 本版本继承 [v2.5.0 release contract](../v2.5.0/release-contract.md) 的全部不变量；
> 本文件仅补充首钢定制功能新增的对象、依赖和不变量。
> 所有 v2.5.0-sg 的 `spec.md` 在编写和评审时必须同时对照两份契约。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为。
其他 Feature 只能读取、引用，或调用 Owner Feature 的 Service。

### 本版本新增或扩展对象

| 领域对象 | Owner Feature | 说明 |
|---------|---------------|------|
| DepartmentBusinessDomainBinding | F056-home-personalized-recommendation | 部门与一个或多个业务域的精确绑定；不包含父子部门继承语义 |
| PortalRecommendationFileProjection | F056-home-personalized-recommendation | 文件业务域、空间、推荐资格、权限范围和投影版本的在线推荐投影 |
| PortalRecommendationPoolState | F056-home-personalized-recommendation | Redis 中租户级业务域池、通用兜底池、热门轮换状态及 active pool version |
| PortalUserRecommendationState | F056-home-personalized-recommendation | Redis 中用户兴趣 Top 50、近 90 天浏览状态、行为版本和短期 Top N |
| ShougangPortalAdminConfig（扩展） | F056-home-personalized-recommendation | 在既有聚合配置中增加部门绑定、推荐数量、算法、影子模式和灰度参数 |
| PortalTelemetryEvent（扩展） | F056-home-personalized-recommendation | 新增 `portal_search`；阅读事件增加推荐场景和入口来源 |

### 复用对象（Owner 不变）

| 领域对象 | 现有 Owner | F056 使用方式 |
|---------|------------|--------------|
| Department / UserDepartment | department 模块（F002） | 只读取唯一主部门及部门 ID，不修改组织树和用户部门关系 |
| Knowledge / KnowledgeFile | knowledge 模块 | 读取文件、空间、版本和状态；文件写入事件只触发投影刷新 |
| PermissionTuple / AuthorizationModel | permission 模块（F004） | 最终文件权限检查统一调用既有权限服务，不新增或修改授权元组 |
| Config | config 模块 | 通过既有首钢门户聚合配置 Service 读写，不新建第二配置事实源 |
| BaseTelemetryEvent | telemetry 模块 | ES 继续保存原始浏览和搜索事件；F056 只扩展门户事件类型和派生状态 |

**规则**：

- 部门业务域绑定不得写 OpenFGA tuple，也不得扩大可见空间或文件范围。
- 推荐投影与 Redis 池是派生数据，不能成为权限事实源。
- F056 不得为 `KnowledgeFile` 增加重复业务域源字段，必须复用现有文件编码/`split_rule` 解析。
- 新增领域对象或改变 Owner 前必须先更新本表。

---

## 表 2：跨 Feature 不变量

除继承 v2.5.0 的 INV-1～INV-15 外，v2.5.0-sg 新增：

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|------------|--------------|-----------|
| INV-SG-1 | 用户业务域只取唯一主部门直接绑定的业务域；不读取次要部门，不向父部门或子部门继承 | DepartmentBusinessDomainBinding, UserDepartment | F056 |
| INV-SG-2 | 业务域匹配只参与推荐打分，不授予 `view_space` 或 `view_file`，也不改变 `visible_space_ids` | DepartmentBusinessDomainBinding, PermissionTuple | F056 |
| INV-SG-3 | 已读文章不从候选中排除，只根据最近浏览时间施加可配置算法中定义的固定四档扣分 | PortalUserRecommendationState | F056 |
| INV-SG-4 | 个性化候选必须先轻量打分，再对最终返回候选做权限检查；非公共空间执行完整 `view_file` 校验 | PortalRecommendationFileProjection, PermissionTuple | F056 |
| INV-SG-5 | 公共空间仅复用已确认的公开快速路径；非公共空间不能以投影、池命中或业务域匹配替代权限检查 | PortalRecommendationFileProjection, PermissionTuple | F056 |
| INV-SG-6 | 无权文件的 ID、标题、摘要、标签和路径不得出现在响应或普通日志中；权限异常默认失败关闭 | KnowledgeFile, PortalRecommendationFileProjection | F056 |
| INV-SG-7 | 第一阶段 custom ACL 文件不得进入共享池；投影滞后时仍由最终权限校验阻止越权 | PortalRecommendationFileProjection | F056 |
| INV-SG-8 | 搜索原文和浏览原始事件以 ES 为事实源；Redis 只保存近 90 天浏览时间、派生兴趣、版本和短期结果，不持久化原始搜索词 | PortalTelemetryEvent, PortalUserRecommendationState | F056 |
| INV-SG-9 | 所有推荐 Redis key 必须包含租户前缀；Celery 任务必须恢复租户上下文并沿用租户 fan-out | PortalRecommendationPoolState, PortalUserRecommendationState | F056 |
| INV-SG-10 | 首钢门户配置只通过既有 `/api/v1/shougang-portal/config` 聚合接口同步；配置按当前租户持久化，版本由 BiSheng 服务端在租户内单调递增，绑定表和配置同事务提交 | ShougangPortalAdminConfig, DepartmentBusinessDomainBinding | F056 |
| INV-SG-11 | 匿名首页保持现有公共推荐与公共缓存；登录用户失败降级必须携带当前用户 token，禁止使用系统账号代取 | ShougangPortalAdminConfig, KnowledgeFile | F056 |
| INV-SG-12 | 热度参数变更必须使用双版本池重算并原子切换 active pool version；重算完成前继续使用上一有效版本 | PortalRecommendationPoolState, ShougangPortalAdminConfig | F056 |

INV-SG-1 的“不继承”只约束推荐业务域特征，不修改基线 INV-12 中部门管理员的权限继承语义。

**规则**：

- 新增不变量：先在本表追加，再写对应 AC。
- 若修改继承的 v2.5.0 不变量，必须回写上游契约并重新评审受影响 spec。
- spec 中任何验收标准与上述不变量冲突时，评审不通过。

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-------------------|------|
| F056-home-personalized-recommendation | F001-multi-tenant-core | 依赖租户上下文、Redis 隔离和 Celery tenant fan-out |
| F056-home-personalized-recommendation | F002-department-tree | 依赖 Department/UserDepartment 和主部门标识 |
| F056-home-personalized-recommendation | F004-rebac-core, F008-resource-rebac-adaptation | 依赖统一权限服务和知识文件 `view_file` 校验 |
| F056-home-personalized-recommendation | 既有 shougang_portal_config / telemetry / knowledge 模块 | 复用聚合配置、ES 遥测、文件浏览和门户权限上下文 |

```text
F001 ──┐
F002 ──┼──> F056-home-personalized-recommendation
F004 ──┤
F008 ──┘
```

---

## 已分配模块编码（MMMEE）

本 Feature 不分配新模块编码。参数校验使用 schema 校验错误；知识推荐相关业务错误复用既有模块边界，不新增与现有编码冲突的错误码。

| 模块编码 | 模块 | 本 Feature 用途 |
|---------|------|----------------|
| 109 | knowledge | 文件与知识空间既有错误 |
| 170 | telemetry | 门户遥测既有错误 |
| 180 | knowledge_space | 首钢门户文件浏览既有错误 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-07-15 | 建立 v2.5.0-sg 契约，登记 F056 对象、依赖及推荐权限不变量 | F056 |
