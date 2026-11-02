# F080 设计

## 1. 目标与约束

以 complete visible enumeration 缩小候选集，再经统一权限运行时判定 edit。遵守本版本 release-contract 和 `docs/constitution.md` C1–C8。接口保留全量返回，普通用户可见枚举容量沿用已有 5,000 上限，超过上限明确失败。

## 2. 已确认的范围

用户已确认 visible + edit 的业务口径及批量准备方案。修改知识模块及共享权限批量准备；共享批量入口的其他调用者纳入回归。无数据迁移、权限发布、索引或环境更新。

## 3. 关键决策

| 决策 | 未采用方案及原因 | 何时重新考虑 |
|---|---|---|
| complete visible IDs → edit | 全租户扫描随所有空间增长；edit ListObjects 未被当前策略允许 | 支持经过评审的动作枚举或接口分页契约时 |
| Repository 按 ID 取行并统一 SQL 排序 | Python 排序改变数据库排序语义；新增 DAO 入口违反 C1 | 若需要跨空间分页，统一设计游标与排序 |
| 快照/动作/围栏/标记按批准备 | 单纯换候选来源仍遗留逐资源 SELECT；跨请求正权限缓存增加撤权风险 | 有真实测量显示批量准备仍为主要瓶颈时 |

1. 复用已有完整 `list_visible_objects`；不启用被 DenyListObjectsPolicy 禁止的管理/编辑动作反向枚举。广域超管保留本租户全量业务查询；收窄 token 仍经可见枚举及数据范围过滤。
2. 空间元数据使用可见 ID 有界查询，IN 谓词分组最多 500 个，由数据库统一排序，避免 Python 排序改变 MySQL/DM8 的排序语义。权限快照与动作检查分为最多 100 个目标一批。
3. 业务 adapter 从已加载行批量构造 VerifiedPermissionTarget，复用权限模块的 permission snapshots。状态、类型、tenant、owner 和版本规则仍由原 adapter 验证。
4. edit 通过后再复核 visible；仅为缺少创建者/管理员成员记录的返回项补查 manage_permission，用于展示角色，不能将管理动作变成入选条件。无跨请求的正权限缓存。
5. 非可见动作的批量检查采用 Catalog 一次、每资源类型动作门禁一次、批量围栏；先数据范围过滤再身份捷径，保留不可判定资源关闭与异常传播。单资源检查不变。
6. Redis 批量一致性读取返回整批最高一致性。现有 `amget` 会丢弃缺失项，因此只判断是否存在任意变更标记，绝不按位置映射。sentinel 丢失或 Redis 异常保持 HIGHER_CONSISTENCY；不新增 key。
7. 新查询放在独立的 KnowledgeSpaceListingRepository，不新增 DAO 入口。仓储持有短会话，读取空间行后立即释放连接，再进行权限 I/O；避免为整个授权过程占用业务数据库连接。

## 4. 数据流与模块

`完整 visible IDs → 当前租户业务空间 → 每批快照/目标 → edit → visible 复核 → 角色补充 → 置顶、计数、部门 → 响应`。

### 4.1 数据流

知识服务负责业务编排，KnowledgeSpaceListingRepository 负责 SQL，容器 adapter 负责业务事实验证；permission.application 承接已验证目标，统一决策服务负责 Catalog/围栏/标记和 OpenFGA。权限模块不导入知识 ORM。

### 4.2 字段与内部契约

Outgoing：`GET /api/v1/knowledge/space/managed?order_by=...` 路径和字段不变，入选条件变为 visible + edit。`user_role` 仍是展示角色，按钮权威仍为各动作权限接口。Incoming：完整 visible 枚举、CURRENT Catalog/固定模型、权限模式、成员与部门事实。

新增 `knowledge_space_managed` 服务阶段指标，不含 HTTP 序列化、依赖注入和网关时间。测试中的 SQL/调用次数是确定性预算，不等于真实环境的毫秒或 P95。

### 4.3 关键模块职责

| 模块 | 职责 |
|---|---|
| KnowledgeSpaceService | 可见枚举、可编辑筛选、角色/置顶/统计装饰、终态指标 |
| KnowledgeSpaceListingRepository | 当前租户的有界 ID 查询、数据库排序、短会话 |
| KnowledgeContainerDaoPermissionLoader / adapter | 复用已加载业务行，批量读取权限快照，验证状态/租户/类型后构造目标 |
| business_authorization | 已验证目标的动作批量入口、分批与异常传播 |
| F048PermissionService / RedisConsistencyMarker | Catalog、批量围栏与最高一致性准备，转交既有固定模型决策 |

## 5. 已知坑

| 事实 | 后果与处理 |
|---|---|
| 自定义 manage_permission 不蕴含 edit | 只管理不可编辑的资源不能进入本接口；edit-only 不能被误标成 ADMIN。 |
| 可见枚举可能含已删除或跨租户残留 ID | 业务查询与 adapter 再过滤；不能只相信枚举。 |
| 全范围超管访问不等于真实 Grant | 保留原身份捷径，但始终限定本租户；收窄 token 不走捷径。 |
| `amget` 删除 None | 只做批级存在性判断，否则可能漏掉撤权标记。 |
| Catalog 动作可关闭，投影可能处理中 | 禁用 edit 得到空列表；服务不可用继续报错；投影版本变化提高一致性。 |

## 6. 对外契约、验证与回滚

覆盖普通用户、超管、收窄数据范围、edit-only/manage-only、撤权、无成员直接授权、非法/不完整枚举、状态和租户隔离；对共享批量决策比较原单目标结果。真实部署通过显式 token 和既有测试空间进行只读检查，本次未授权部署。

回滚代码即可，无持久数据变更。用户要求本修复落在 1028 分支；不自动推送或部署。

## 修订历史

2026-11-02：记录本会话已评审并授权的流程和接口口径。
2026-11-02：实现 visible-first/edit、短会话 Repository、批量准备与阶段指标；新增权限矩阵、调用预算和部署后验收清单。
