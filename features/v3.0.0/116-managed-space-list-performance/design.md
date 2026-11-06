# F116 主线设计与分支适配

遵守 `docs/constitution.md` C1–C8。来源修复 `a8602ada9`；主线起点 `368894d9a45f265a47903e2b6d08a90f5418b607`。

## 1. 背景

旧 managed 路径扫描全租户空间，再逐目标准备权限和补充展示数据。普通用户只看少量空间时也承担与租户总空间量相关的开销。采用已评审的可见 ID → edit 批量判断方案。

## 2. 范围

只迁移 managed 编排、独立只读仓储、容器目标批量构造、统一已验证动作入口及共享批量准备。源分支的其它提交、COFCO 评审材料和部署证据不作为主线代码合并。

## 3. 决策与差异

| 选择 | 原因/未采用项 | 何时重评 |
|---|---|---|
| complete visible IDs → edit → visible 复核 | 避免全租户扫描；不启用当前策略禁用的动作反向枚举 | 引入正式分页契约或经过评审的动作枚举时 |
| Repository 单次 SQL、IN 分组 500、统一数据库排序 | C1 禁止新增 DAO 入口；Python 排序会改变数据库 collation | 需要跨请求游标分页时 |
| 权限目标/快照/围栏每批 100，Redis 一次 MGET | 仅替换候选来源仍有逐资源 I/O；不引入正权限缓存 | 实测证明批准备仍是瓶颈时 |
| manage_permission 仅补展示角色 | edit-only 不能被管理动作误排除或误标成管理员 | 产品正式改变列表口径时 |

主线差异逐项保留：

- 主线没有 COFCO `/info` 优化带来的 `contextmanager` 导入，本次只补该依赖，不同步 `/info` 逻辑。
- `get_space_info`、广场有效可见性和退出后重新申请的主线实现保持原样。
- 公开 workflow/assistant 的 guest-link 校验保留；统一动作入口只追加已验证目标批量方法。
- 主线容器错误码仍为 25022，文件 adapter 的 `rollback_created` 和跨资源类型父子 ID 校验修复保留；不恢复中粮专有的部门 owner/退出来源方法。
- 性能补丁不改 `runtime.py` 的主线服务账号删除例外、权限发布和生命周期逻辑；共享 decision 批量准备复用现有 runtime 分发。最终整合另外保留并行提交 `f13c29489` 的成员来源版本解析调用。
- 真实 E2E 使用主线命名与显式 `tenant_id`；旧 `/user/info.tenant_id` 可能为空，不能据此误判返回行跨租户。

## 4. 当前实现

### 4.1 数据流

`actor → 完整 visible IDs → 当前租户 Repository → 批量快照/业务目标 → edit → visible 复核 → 角色补充 → 置顶/计数/部门 → 响应`。

全范围超管保留当前租户业务查询。租户管理员即使动作存在身份捷径，也不能跳过个人 visible 范围；收窄 token 继续受统一运行时数据范围约束。

### 4.2 字段与内部契约

HTTP 路径、参数、响应封装和字段不变。列表入选为 visible ∩ edit；manage_permission 只影响无成员记录时的角色显示。可见枚举上限 5,000，超限报错，不能截断。`knowledge_space_managed` 阶段计时不含网关、依赖注入或响应序列化。

### 4.3 模块职责

| 模块 | 职责 |
|---|---|
| KnowledgeSpaceService | 范围编排、edit/visible 交集、展示装饰和终态指标 |
| KnowledgeSpaceListingRepository | strict tenant 自动过滤、数据库排序；查询后立即释放连接 |
| KnowledgeContainerDaoPermissionLoader / adapter | 已加载业务行与权限快照组成已验证目标；状态、类型、租户规则不放进权限模块 |
| business_authorization | 分批、动作缺失处理及错误传播，不重复按 ID 查业务行 |
| F048PermissionService / RedisConsistencyMarker | 批量门禁、围栏与最高一致性；固定模型及发布门禁保持 |

### 4.4 uploadable 性能修复（2026-11-02）

`/knowledge/space/uploadable` 复用完整 visible ID 校验、strict tenant 只读仓储和批量业务目标准备。普通用户先枚举可见空间，再以 `upload_file` 精确批量检查；不要求 `edit`，不读取成员角色代替鉴权。既有 F048 普通动作授权带有 visible 投影。与 managed 的个人管理列表不同，未收窄的租户管理员仍扫描原有候选范围并经统一运行时检查，未收窄超管保留原有快捷路径；收窄身份仍枚举并检查。

仓储新增可选 `keyword`，名称或描述使用数据库 LIKE，与旧扫描一致；按 update_time、id 降序，获准结果最多 200 条。可见枚举与 managed 共用 5,000 上限和完整性校验，异常、超限或服务不可用不回退扫描或假装空结果。请求和响应结构不变。SQL 会话在权限 I/O 前释放，IN 每组最多 500，不新增表、缓存或依赖。

仅替换逐资源查询不足以消除慢请求：116 只读对照中 SQL 从 772 降为 36 后仍需检查 370 个候选，耗时约 4.5–4.8 秒；进一步收敛可见候选后才降至 14 次 SQL、约 0.32–0.35 秒。后续若需要大于 5,000 个可见空间，应单独设计分页协议；不能静默截断。

## 5. 已知坑

| 事实 | 忽略的后果与处理 |
|---|---|
| patch clean 不表示跨分支依赖齐全 | COFCO 已存在的 contextmanager 未出现在来源 diff；主线显式导入并运行真实 service/ASGI 测试。 |
| Redis amget 丢弃缺失项 | 不按位置对应资源，只判断是否有任一变更标记；异常/缺 sentinel 保持 HIGHER_CONSISTENCY。 |
| visible 与管理身份不同 | 租户管理员不替代可见枚举；超管仅在全范围且当前租户分支保留旧特权列表。 |
| 本地主线已有检索修复与远端重复 | 仅一处注释冲突，采用最新主线注释；整合提交代码树与远端起点完全一致，并保留双方历史。 |
| uploadable 不等于 managed | 复用性能实现时不能把 edit 或个人 visible 门禁套给租户管理员，导致原本可上传空间丢失；本次分别保留动作语义与管理身份范围。 |

## 6. 对外契约与验证

Outgoing：managed 列表响应；Incoming：当前权限 Catalog/Store/model、完整可见枚举、权限快照、业务行与展示数据。没有新依赖、数据库对象或共享本地状态。

基线与适配后在相同环境运行知识/权限/guest/退出重入/检索回归，另有主线 opt-in E2E 和手动清单；真实部署验收单列，不复用 COFCO 的耗时当作主线测量。回滚本修复提交即可。

## 修订历史

2026-11-02：按用户授权迁移既有方案，记录主线差异、显式依赖与验证边界。

2026-11-02：合入时保留并行成员来源重新激活修复 f13c29489，联合回归 351 通过、3 跳过。

2026-11-02：复用已验证的候选枚举与批量准备修复 uploadable 扫描放大；只读运行对照与定向验证见 uploadable-performance-verification-20261102.md，未部署运行服务。
