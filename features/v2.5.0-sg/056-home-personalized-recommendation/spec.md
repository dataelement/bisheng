# Feature: 首页个性化推荐

> **状态**：核心实现与定向验证完成；待集成环境性能、E2E 与 DM8 实库门禁。
>
> Spec Discovery 已由《首页个性化推荐技术方案》及 8 项评审结论完成；用户于 2026-07-15 确认规格，并明确允许第三轮修订后继续实现。
> 本规格把跨门户与 BiSheng 的已确认方案转换为可实施、可测试的 SDD 契约。

- **关联 PRD**: [首页个性化推荐技术方案](../../../../shougang-group-knowledge-portal/docs/specs/2026-07-14-首页个性化推荐技术方案.md)
- **优先级**: P0
- **所属版本**: v2.5.0-sg
- **Owner Feature**: F056-home-personalized-recommendation
- **版本契约**: [v2.5.0-sg release contract](../release-contract.md)

---

## 0. 范围界定

### IN

- BiSheng 既有首钢门户聚合配置扩展：
  - `portal` 配置下新增 `department_business_domain_bindings`。
  - `portal.recommendation` 新增推荐总数、四个算法参数、影子模式和灰度比例。
  - 配置版本由服务端单调递增；聚合配置与规范化绑定表同事务保存。
- MySQL/DM8 兼容的数据模型与迁移：
  - `department_business_domain`。
  - `portal_recommendation_file_projection`。
- 共享候选池、用户兴趣 Top 50、近 90 天浏览状态、行为版本、用户短期 Top N。
- `personalized_v1` 在线召回、动态归一化、浏览扣分、稳定打散、兜底合并和最终权限校验。
- 扩展既有 BiSheng `POST /api/v1/knowledge/shougang-portal/files/browse`。
- 扩展门户搜索和阅读遥测；搜索原始事件仍以 ES 为事实源。
- 文件/ACL 增量投影任务、6 小时聚合、每日增量对账、每周全量对账及双版本池切换。
- 门户管理后台的独立部门业务域绑定界面与推荐参数界面。
- 门户首页 SSE 登录/匿名分流、稳定灰度、影子计算、安全降级。
- “更多”页一次加载完整 Top N、显式搜索上报和准确预览入口。

### OUT

- 不改变 OpenFGA 授权模型，不因业务域绑定新增权限 tuple。
- 不给 `knowledge_file` 新增重复业务域源字段。
- 第一阶段 custom ACL 文件不进入共享推荐池。
- 不提供父部门/子部门业务域继承。
- 不提供管理员置顶或 14+3 轮换豁免。
- 不建设长期 MySQL 用户行为明细表。
- 不建设无限推荐流、游标翻页或模型训练平台。
- 不改变匿名用户的公共推荐算法与公共首页缓存。
- 不改造行业情报等其他首页标签区块，不做协同过滤或用户相似度推荐。
- 不使用 BiSheng 系统角色替代部门或业务域。
- 不在单个门户部署内新增跨 BiSheng 租户的配置切换；一个门户部署由其 runtime admin token 固定绑定一个租户。

### 兼容原则

- 现有 `latest_selected` 及其他浏览模式行为不变。
- 现有 SSE 事件名、分区结构和匿名缓存协议不变。
- 旧门户配置缺少新增字段时由 schema 默认值兼容迁移；非法显式值不得静默回退。
- 灰度比例为 0 时完全回到旧推荐链路，但保留行为数据、投影和共享池。

---

## 1. 概述与用户故事

### US-01：登录用户获得相关且安全的推荐

作为已登录门户用户，我希望首页推荐综合主部门业务域、个人搜索兴趣、热度、新鲜度和最近浏览情况，以便优先看到对我更相关且我确实有权访问的内容。

### US-02：管理员维护精确部门绑定

作为门户管理员，我希望在独立界面为一个部门绑定一个或多个业务域，且父子部门互不继承，以便准确表达组织与业务域关系。

### US-03：管理员安全灰度算法

作为门户管理员，我希望配置推荐数量、算法参数、影子模式和灰度比例，以便逐步验证个性化推荐并可将比例调为 0 快速回退。

### US-04：平台运维保证可恢复性

作为平台运维人员，我希望推荐投影和池由增量事件及周期对账共同维护，并在热度参数变化时原子切换版本，以便在漏事件、缓存缺失和参数变更下保持一致。

---

## 2. 验收标准

### 2.1 配置与部门绑定

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | 在当前租户为同一部门选择多个业务域并保存 | 当前租户的门户配置、BiSheng 聚合配置和 `department_business_domain` 中得到规范化、去重后的精确绑定，不影响其他租户 |
| AC-02 | 管理员 | 分别配置父部门与子部门 | 用户只命中其唯一主部门自身绑定，不向父/子部门双向继承 |
| AC-03 | 系统 | 用户存在主部门和次要部门 | 只读取 `is_primary=true` 的唯一主部门，不读取次要部门 |
| AC-04 | 系统 | 用户无主部门、存在多个主部门或主部门无绑定 | 禁用业务域特征，不回退读取次要部门，其他有效特征继续动态归一化 |
| AC-05 | 管理员 | 清空或删除某部门绑定并保存 | 以全量替换语义删除旧行；未出现在请求中的旧绑定不残留 |
| AC-06 | 管理员 | 保存推荐配置 | `1 <= section_page_size <= home_total_count <= 50` 且四个算法参数、影子开关、0～100 灰度通过校验后生效 |
| AC-07 | 管理员 | 保存非法参数或不存在的业务域编码 | 请求被明确拒绝，旧配置与旧绑定保持不变，不发生半提交或静默回退 |
| AC-08 | 系统 | 同一租户串行或并发成功保存聚合配置 | 每个成功事务获得该租户内唯一且严格单调递增的 `version`；客户端传入版本不能降低、固定或制造重复服务端版本 |
| AC-09 | 系统 | 热度半衰期或首页来源权重变化，且多次重算并发/乱序完成 | 仅最新 desired generation 可原子切换；旧任务晚完成不能把 active pool 回切，重算期间继续使用上一有效版本 |

### 2.2 推荐算法与候选池

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-10 | 登录用户 | 有业务域且相关池可提供足量有权文件 | 第一轮只使用全部业务域池与用户兴趣池，不读取通用兜底池 |
| AC-11 | 登录用户 | 无业务域 | 第一轮使用兴趣池与通用兜底池；业务域权重不进入分母 |
| AC-12 | 登录用户 | 有业务域但第一轮不足 Top N | 合并通用兜底池后对新并集重新统一打分，不把兜底结果直接追加在尾部 |
| AC-13 | 系统 | 多路池命中同一文件 | 按 `(space_id, file_id)` 去重并保留该文件的全部命中特征 |
| AC-14 | 系统 | 轻量候选不超过 10000 | 所有候选参与打分，不执行旧的 30/20/10 前置配额截断 |
| AC-15 | 系统 | 去重后候选超过 10000 | 按业务域轮询和池内顺序熔断到 10000，并记录熔断指标 |
| AC-16 | 系统 | 生成业务域池或通用池 | 热门:新鲜按 3:1 交错取值、去重回填；单路不足由另一路补齐，目标容量默认 500 |
| AC-17 | 系统 | 业务域只关联一个空间且合格文件充足 | 该空间可填满池目标，不受单空间 20 篇限制 |
| AC-18 | 系统 | 同一热门文件连续入池 | 最多连续 14 个自然日，第 15 天进入 3 天冷却；冷却后按当前分重新竞争 |
| AC-19 | 系统 | 计算最终分 | 有效特征按权重 0.30/0.40/0.15/0.15 动态归一化，再叠加浏览扣分 |
| AC-20 | 登录用户 | 最近浏览同一文件 | 取最近一次浏览：0～7 天 -80、8～30 天 -50、31～90 天 -30、超过 90 天或未读 0；文件仍保留在候选中 |
| AC-21 | 登录用户 | 候选分差不超过配置阈值 | 在配置周期内按租户、用户、周期和文件稳定打散；不同用户可不同，超出阈值不得跨组打散 |
| AC-22 | 系统 | 修改稳定打散阈值或周期 | 新配置版本立即使用户短期 Top N 失效，不要求重建共享池 |

### 2.3 权限、安全与在线预算

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-23 | 匿名用户 | 打开首页 | 继续使用 `latest_selected` 公共链路；公共空间正常文件对所有门户用户可见 |
| AC-24 | 登录用户 | 请求 `personalized_v1` | 先对最多 10000 个轻量候选评分，再按最终顺序每批 10 篇执行权限校验 |
| AC-25 | 系统 | 校验公共空间正常文件 | 沿用既有公开快速路径；删除、违规、非主版本或非成功文件仍不得返回 |
| AC-26 | 系统 | 校验非公共空间文件 | 复用请求级权限上下文并执行完整 `view_file` 校验，不以空间可见、投影或池命中代替 |
| AC-27 | 系统 | 文件存在 custom ACL | 不进入共享池；若投影滞后或权限刚撤销，最终权限校验仍阻止返回 |
| AC-28 | 系统 | 高分候选连续被拒绝 | 继续检查后续候选，直至取得 Top N、累计检查 200 篇或用尽 700 ms |
| AC-29 | 系统 | 权限服务对单文件或本次选择整体异常 | 单文件失败关闭并继续；权限上下文/选择整体异常固定返回 HTTP 200 的已确认文件或空列表，不尝试弱化权限检查 |
| AC-30 | 系统 | 任何候选未通过权限 | 返回实际数量或空列表，不用无权文件补足；响应和普通日志不泄露无权元数据 |
| AC-31 | API 客户端 | 获取 `personalized_v1` | 响应固定 `has_more=false`、`next_cursor=null`，数量不足时返回实际数据 |
| AC-32 | 系统 | 命中用户短期 Top N 缓存 | 仍实时复核权限；任一缓存文件失权时丢弃缓存并在剩余预算内重算 |

### 2.4 行为、门户和灰度

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-33 | 登录用户 | 回车、点击搜索按钮或点击首页热门词 | 仅一次上报 `portal_search`；筛选、排序、分页、重试和重渲染不重复上报 |
| AC-34 | 系统 | 接收搜索事件 | 规范化查询写入 ES，递增行为版本并异步重算该用户兴趣 Top 50；Redis 不保存原始搜索词 |
| AC-35 | 登录用户 | 从首页推荐、推荐列表或搜索结果预览 | 阅读事件携带准确 `entry_point` 与 `recommendation_scene`，同步更新近 90 天浏览 ZSET 和行为版本 |
| AC-36 | 系统 | 聚合热度 | 近 30 天按 `user_id + file_id + 自然日` 去重；自然入口权重 1，首页推荐及其“更多”列表入口使用配置权重，时间按配置半衰期衰减 |
| AC-37 | 门户 | 登录用户请求首页 | 账号稳定哈希命中灰度时请求 `personalized_v1`，否则返回旧逻辑；登录用户完整首页不进入公共缓存 |
| AC-38 | 门户 | 影子模式开启 | 影子模式优先于灰度：登录用户始终返回旧结果，同时在不改变响应内容的后台链路计算并记录个性化指标 |
| AC-39 | 门户 | 个性化调用发生传输异常、HTTP 5xx 或非成功业务响应 | 使用当前用户 token 降级请求 `latest_selected`；权限选择返回的安全 200 空/部分列表不视为调用失败，禁止使用系统账号代取 |
| AC-40 | 门户 | 默认得到有权 Top 20 | BiSheng 缓存完整 Top 20；首页 SSE 只输出前 6，“更多”页一次展示相同顺序的全部 20 |
| AC-41 | 门户 | 最终只有 13 篇有权推荐 | 首页展示 `min(section_page_size, 13)`，“更多”页展示全部 13，不继续分页 |
| AC-42 | 管理员 | 将灰度比例依次设为 0/10/50/100 | 稳定哈希人群按比例启用；调回 0 立即回退旧推荐且不删除投影或行为数据 |

### 2.5 投影、任务与兼容

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-43 | 系统 | 文件发布、删除、移动、状态、版本、业务域或 ACL 变化 | 只刷新受影响文件/子树投影与池成员，任务幂等且不触发无关租户全量扫描 |
| AC-44 | 系统 | 定时任务运行 | 每 6 小时重算热度和共享池；每日 watermark 增量对账；每周分页全量对账 |
| AC-45 | 系统 | Worker 执行 | 恢复发布时的 `tenant_id` 上下文，Redis/DB/ES 均保持租户隔离并使用 `knowledge_celery` |
| AC-46 | 系统 | Redis 行为状态缺失 | 作为冷启动，按业务域或通用兜底继续；不让在线请求同步聚合 ES |
| AC-47 | 系统 | Redis 共享池缺失 | 从推荐投影做有界最新内容补偿并异步补建池，不扫描完整文件表 |
| AC-48 | 系统 | ES 暂时不可用 | 继续使用最近有效共享池；搜索兴趣重算可重试但首页请求不等待 ES |
| AC-49 | 系统 | 执行数据库升级 | MySQL 与 DM8 均可创建/回滚两张表、唯一约束和索引 |
| AC-50 | 系统 | 运行性能验收 | 10000 轻量候选、最多 200 次权限检查下推荐 P95 < 800 ms，首个首页 SSE 区块 P95 < 1 s |
| AC-51 | 系统 | 未携带当前租户管理员 token 调用 `/config/internal` | 返回既有 401/403 响应，不返回未脱敏聚合配置；合法管理员只读取其 token 对应租户 |
| AC-52 | 系统 | 运行搜索事件保留任务 | 只删除当前租户 `portal_search` 中 timestamp 早于当前 UTC 时间 90 天的 ES 事件，其他事件和其他租户不受影响 |

---

## 3. 边界情况与失败语义

| ID | 场景 | 预期行为 |
|----|------|---------|
| E-01 | 同一用户没有主部门 | 业务域集合为空，禁用业务域权重 |
| E-02 | 同一用户有多个 `is_primary=true` 记录 | 视为组织数据异常，记录无敏感信息告警并禁用业务域权重 |
| E-03 | 部门绑定含大小写混合或重复编码 | 保存时统一大写、去空白、去重并按编码稳定排序 |
| E-04 | 绑定引用不存在或已禁用业务域 | 整次保存失败，旧配置与绑定表不变 |
| E-05 | `home_total_count` 小于首页展示数 | 整次保存失败并返回字段级错误 |
| E-06 | 用户兴趣池为空 | 动态移除兴趣权重，不按 0 分稀释其他特征 |
| E-07 | 热门 P95 样本过少或为 0 | 回退租户级 P95；仍无有效分母时热门分为 0 |
| E-08 | 同一文件同时来自热门、新鲜、业务域和兴趣池 | 只保留一份候选并合并全部特征 |
| E-09 | 时间预算在一个权限批次中到达 | 完成本批已发起校验的安全收敛，只返回已确认文件，不发起新批次 |
| E-10 | 文件详情在权限通过后被删除 | DTO 组装跳过该文件并记录投影滞后指标 |
| E-11 | 权限校验异常或返回不确定结果 | 失败关闭；不得把不确定视为允许 |
| E-12 | 搜索事件 ES 写入暂时失败 | 进入既有 telemetry 重试/失败观测；不把原始查询转存 Redis |
| E-13 | 浏览 Redis write-through 失败 | 不阻断文件预览，但记录失败指标；后续可由 ES 事实数据修复 |
| E-14 | 双版本池重算失败 | active version 不切换，继续使用上一有效池并发出告警 |
| E-15 | 灰度哈希所需用户标识缺失 | 视为未命中灰度，走旧推荐 |
| E-16 | `personalized_v1` 携带 cursor 或超大 limit | 服务端忽略 cursor，实际目标数取配置 Top N 且最大 50 |
| E-17 | 所有业务域池、兴趣池、通用池均为空 | 从推荐投影按实时可见空间补入最多 500 个最新候选并统一打分，同时触发池补建；仍无结果才返回空，不回退系统账号 |

**明确不支持**：

- 业务域父子部门继承、次要部门合并、管理员置顶豁免。
- custom ACL 文件进入共享池。
- 登录用户无限滚动推荐和跨请求 cursor 翻页。
- 用 Redis 作为搜索原始事实源，或在管理后台展示用户搜索原文。

---

## 4. 架构决策

| ID | 决策 | 结论 | 理由 |
|----|------|------|------|
| AD-01 | 推荐计算位置 | 放在 BiSheng knowledge Domain Service | 复用文件解析、权限上下文、Redis/ES 和 Worker，避免门户 N+1 |
| AD-02 | 配置同步协议 | 只扩展既有 `GET/PUT /api/v1/shougang-portal/config` 聚合接口 | 保持单一事实源；覆盖技术方案旧稿 12.2 的两个独立 BiSheng 同步端点 |
| AD-03 | 门户管理接口 | 新增 `GET/POST /api/v1/admin/config/department-business-domains`；推荐继续既有 `/recommendation` | 管理职责独立，但远端仍整包同步 |
| AD-04 | 用户业务域 | 唯一主部门精确绑定，多业务域去重，无继承 | 对齐已确认业务规则 |
| AD-05 | 文件业务域 | 复用文件编码/`split_rule` 解析并写推荐投影 | 避免三份源字段漂移 |
| AD-06 | 候选存储 | 租户共享池 + 活跃用户兴趣 Top 50，不维护每用户完整长期池 | 降低文件/ACL/组织变化的扇出 |
| AD-07 | 候选结构 | 业务域池、用户兴趣池、通用兜底池；热门和新鲜按 3:1 组装 | 兼顾热门、新内容和冷启动 |
| AD-08 | 最终排序 | 全部相关轻量候选先打分，再渐进权限校验 | 公共池排序不能提前截断个性化结果 |
| AD-09 | 权限边界 | 公共空间复用公开快速路径；非公共空间完整 `view_file` | 与现有权限语义一致且不泄露 |
| AD-10 | custom ACL | 第一阶段从共享池排除 | 降低异步投影与 nearest-binding override 的安全复杂度 |
| AD-11 | 已读处理 | 不排除，按最近浏览时间直接加固定扣分 | 保留高相关已读内容再次出现的可能 |
| AD-12 | 行为事实源 | ES 存原始事件，Redis 存派生在线状态 | 满足 90 天审计与低延迟在线计算 |
| AD-13 | 配置版本 | BiSheng 在成功事务内按旧值 +1 生成，客户端版本只作兼容输入 | 防止门户并发/回放导致版本倒退 |
| AD-14 | 热度配置切换 | versioned pool 双写重算 + active version 原子切换 | 防止新配置读取旧池 |
| AD-15 | 首页缓存 | 匿名公共缓存保留，登录完整首页缓存关闭 | 防止用户间个性化结果串用 |
| AD-16 | 灰度算法 | 对 UTF-8 字符串 `"{tenant_id}:{user_id}:personalized_v1"` 做 SHA-256，取 digest 前 8 字节按 unsigned big-endian 转整数后 `% 100` | 跨语言结果固定，同一用户稳定且无需存灰度名单 |
| AD-17 | 降级身份 | 始终使用当前用户 token 调用 `latest_selected` | 降级不改变权限主体 |
| AD-18 | API 分页 | `personalized_v1` 一次返回完整 Top N，固定无后续页 | 首页和“更多”顺序一致，避免伪无限流 |
| AD-19 | 门户部署与租户 | 一个门户部署使用 runtime admin token 绑定一个 BiSheng 租户；不同租户使用不同部署/token | 兼容现有全局 PortalConfigService，同时保证远端聚合配置和绑定表属于同一租户 |

---

## 5. 数据库、配置与 Redis 模型

### 5.1 `department_business_domain`

该表由 F056 持有，记录“当前租户内某个部门直接绑定某个业务域”的规范化行。

| 字段 | 类型/约束 | 说明 |
|------|-----------|------|
| `id` | bigint PK | 主键 |
| `tenant_id` | int, not null | 由租户上下文自动注入和过滤 |
| `department_id` | int, not null | 精确部门 ID |
| `business_domain_code` | varchar(16), not null | 去空白并统一大写 |
| `create_user` | int, nullable | 最近一次配置操作人 |
| `create_time` | datetime, not null | 服务端默认时间 |
| `update_time` | datetime, not null | 使用 `UPDATE_TIME_SERVER_DEFAULT` |

约束和索引：

```text
UNIQUE (tenant_id, department_id, business_domain_code)
INDEX  (tenant_id, department_id)
INDEX  (tenant_id, business_domain_code)
```

全量保存规范：

1. 校验部门存在于当前租户。
2. 校验业务域存在于同一份聚合配置的 `domains`。
3. 业务域编码去空白、统一大写、去重并排序。
4. 同一 `department_id` 在配置列表中只能出现一次。
5. `PortalAdminConfigRepository` 与绑定 Repository 共享同一 session；在一个 DB transaction 中锁定/读取当前租户配置，计算新版本，flush Config JSON，并全量替换当前租户绑定行，Repository 方法不得自行 commit。
6. 任一步失败时回滚配置和绑定表。

并发版本实现必须兼容 MySQL 和 DM8：已有配置行使用行锁读取后递增；首次并发创建依赖 Config key 唯一约束并做有界重试，确保每个成功事务获得不同版本。

### 5.2 `portal_recommendation_file_projection`

该表是可重建的派生投影，不是文件或权限事实源。

| 字段 | 类型/约束 | 说明 |
|------|-----------|------|
| `id` | bigint PK | 主键 |
| `tenant_id` | int, not null | 租户隔离 |
| `file_id` | int, not null | 租户内唯一文件 |
| `space_id` | int, not null | 所属知识空间 |
| `business_domain_code` | varchar(16), nullable | 复用既有解析函数得到的规范化业务域 |
| `permission_scope` | varchar(16), not null | `inherited/custom/unknown` |
| `recommendable` | smallint, not null | 0/1，是否可进入共享池 |
| `reason_code` | varchar(32), not null | 不可推荐原因，如 `custom_acl`、`not_success` |
| `source_update_time` | datetime, not null | 文件内容更新时间快照；一期复用文件更新时间 |
| `projection_version` | bigint, not null | 单文件投影版本，用于幂等覆盖 |
| `create_time` / `update_time` | datetime, not null | 标准时间字段 |

约束和索引：

```text
UNIQUE (tenant_id, file_id)
INDEX  (tenant_id, business_domain_code, recommendable, source_update_time, file_id)
INDEX  (tenant_id, recommendable, source_update_time, file_id)
INDEX  (tenant_id, space_id, recommendable)
```

`recommendable=1` 必须同时满足：

- 文件类型为普通文件、处理状态成功、当前主版本。
- 未删除、未隐藏、未违规。
- `permission_scope=inherited`，即 lineage 不存在会覆盖空间读取语义的 custom relation binding。

`recommendable=1` 只控制共享池资格；在线返回仍执行最终权限检查。

### 5.3 聚合配置 Schema

在门户与 BiSheng 同构的 `ShougangPortalAdminConfig.portal` 中增加。以下仅展示相关片段，既有 `bisheng`、`unified_auth` 和其他 portal 字段保持不变：

聚合配置按认证后的当前租户持久化。由于既有 `Config` 表没有 `tenant_id`，Repository 使用兼容 key：

```text
tenant_id = 1: shougang_portal_config
tenant_id > 1: shougang_portal_config:t:{tenant_id}
```

`multi_tenant.enabled=false` 时隐式 tenant_id=1，继续读取原 key。所有 GET/PUT、Worker 配置读取和版本递增都先从租户上下文解析同一个 key；禁止回退读取其他租户配置。

```json
{
  "version": 12,
  "portal": {
    "department_business_domain_bindings": [
      {
        "department_id": 10,
        "business_domain_codes": ["PP", "SAFE"]
      }
    ],
    "recommendation": {
      "provider": "tag_feed",
      "home_strategy": "tag+updated_at",
      "detail_strategy": "shared_tags+updated_at",
      "home_total_count": 20,
      "hot_half_life_days": 7,
      "home_entry_source_weight": 0.3,
      "stable_shuffle_score_gap": 5,
      "stable_shuffle_cycle_days": 7,
      "personalized_shadow_enabled": false,
      "personalized_rollout_percent": 0
    }
  }
}
```

字段约束：

| 字段 | 默认值 | 范围 |
|------|-------:|------|
| `home_total_count` | 20 | 1～50，且不小于 `display.home.section_page_size` |
| `hot_half_life_days` | 7 | 1～90 |
| `home_entry_source_weight` | 0.3 | 0～1 |
| `stable_shuffle_score_gap` | 5 | 0～100 |
| `stable_shuffle_cycle_days` | 7 | 1～30 |
| `personalized_shadow_enabled` | false | bool |
| `personalized_rollout_percent` | 0 | 整数 0～100 |

其中 `home_entry_source_weight` 同时应用于首页推荐和由首页进入的推荐“更多”列表；无法识别来源的历史事件也保守使用该权重。搜索、知识空间、直接链接和收藏等可确认自然入口使用 1.0。

旧配置兼容：

- 缺失新字段时补上述默认值并可正常读取。
- 保存时输出完整新 schema。
- 首次保存时服务端版本为 1；已有配置每次成功保存取 `stored_version + 1`。
- 服务端不信任请求中的 `version` 来决定新版本。

### 5.4 Redis key 与 TTL

所有 key 通过统一 Repository 生成，不在 Service 中散落字符串。下列为租户内逻辑 key；
物理 key 必须先经过仓库既有 tenant Redis prefix helper：默认租户保持兼容前缀，
其他租户增加 `t:{tenant_id}:`，再拼接下列包含 tenant 的业务 key：

```text
# pool active version and versioned shared pools
sg:rec:v1:pool:{tenant}:active_version
sg:rec:v1:pool:{tenant}:desired_generation
sg:rec:v1:pool:{tenant}:{pool_version}:domain:{domain_code}
sg:rec:v1:pool:{tenant}:{pool_version}:domain:{domain_code}:hot
sg:rec:v1:pool:{tenant}:{pool_version}:domain:{domain_code}:fresh
sg:rec:v1:pool:{tenant}:{pool_version}:domain:{domain_code}:hot_state
sg:rec:v1:pool:{tenant}:{pool_version}:generic
sg:rec:v1:pool:{tenant}:{pool_version}:generic:hot
sg:rec:v1:pool:{tenant}:{pool_version}:generic:fresh
sg:rec:v1:pool:{tenant}:{pool_version}:generic:hot_state

# per-user derived state
sg:rec:v1:user:{tenant}:{user}:domains
sg:rec:v1:user:{tenant}:{user}:reads
sg:rec:v1:user:{tenant}:{user}:interest
sg:rec:v1:user:{tenant}:{user}:behavior_version
sg:rec:v1:user:{tenant}:{user}:topn:{config_version}:{pool_version}:{behavior_version}

# reconciliation
sg:rec:v1:reconcile:{tenant}:watermark
```

| 数据 | 类型 | TTL/保留 |
|------|------|----------|
| active pool version | JSON/STRING | 常驻，包含 generation、pool_version、热度配置 fingerprint |
| desired generation | STRING integer | 常驻，每次计划重算时原子递增 |
| 共享池、hot/fresh、轮换状态 | ZSET/HASH | 常驻滚动；切换后旧版本延迟清理 |
| 用户业务域 | SET/JSON | 30 分钟，绑定或主部门变化主动失效 |
| 用户最近浏览 | ZSET(`file_id -> last_read_ts`) | 90 天滚动 |
| 用户兴趣 | ZSET(`space_id:file_id -> score`) | 30 分钟，最多 50 |
| 用户行为版本 | STRING integer | 常驻，搜索和浏览原子递增 |
| 用户 Top N | LIST/JSON IDs | 240 秒；版本变化自然换 key |

Redis Repository 必须支持 pipeline/批量读取、缺失降级、原子 `INCR`、版本化批量写，以及带 generation 比较的 active version CAS 切换。

### 5.5 ES 搜索事件保留

`base_telemetry_events` 继续作为搜索原文唯一事实源。新增 tenant-aware Telemetry Repository，只允许：

- 查询当前租户最近 90 天的 `portal_search`。
- 按 `event_type=portal_search AND timestamp < now_utc-90d` 删除当前租户过期事件。
- 使用既有 ES tenant index/prefix 规则和租户字段过滤，不跨租户查询或删除。

每日低峰运行幂等 delete-by-query；删除失败记录告警并按 Celery 重试，不把搜索原文复制到 MySQL 或 Redis 作为补偿。其他 telemetry event type 不应用该保留删除。

---

## 6. API 契约

### 6.1 BiSheng 聚合配置（扩展既有接口）

| Method | Path | 认证 | 变化 |
|--------|------|------|------|
| GET | `/api/v1/shougang-portal/config` | 当前租户管理员 | 返回当前租户脱敏后的完整新 schema |
| GET | `/api/v1/shougang-portal/config/internal` | 当前租户管理员 | 返回当前租户内部完整新 schema；补齐现有端点缺失的 `UserPayload.get_admin_user` 认证 |
| PUT | `/api/v1/shougang-portal/config` | 当前租户管理员 | 规范化、校验并同事务保存当前租户配置与部门绑定；返回服务端新版本 |

不新增以下旧方案端点：

- `/api/v1/knowledge/shougang-portal/departments/business-domain-codes`
- `/api/v1/knowledge/shougang-portal/recommendation-config`

成功响应沿用 `resp_200`；`data.version` 是保存后的服务端版本。校验失败返回现有统一参数错误格式，数据库失败整事务回滚。

聚合保存成功响应（`data.portal` 仅节选本 Feature 字段；实际类型为完整 `ShougangPortalAdminConfigView`）：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "version": 13,
    "portal": {
      "department_business_domain_bindings": [
        {
          "department_id": 10,
          "business_domain_codes": ["PP", "SAFE"]
        }
      ],
      "recommendation": {
        "home_total_count": 20,
        "hot_half_life_days": 7,
        "home_entry_source_weight": 0.3,
        "stable_shuffle_score_gap": 5,
        "stable_shuffle_cycle_days": 7,
        "personalized_shadow_enabled": false,
        "personalized_rollout_percent": 10
      }
    }
  }
}
```

### 6.2 BiSheng 文件浏览（扩展）

```http
POST /api/v1/knowledge/shougang-portal/files/browse
Authorization: Bearer <current-user-token>
Content-Type: application/json
```

请求相关字段：

```json
{
  "recommendation": "personalized_v1",
  "limit": 20,
  "cursor": null
}
```

语义：

- `personalized_v1` 仅对登录用户启用。
- 实际目标数读取当前配置 `home_total_count`，最大 50；调用方 `limit` 不能突破配置。
- `space_ids` 只能用于既有可见范围收窄，不能扩大权限。
- `cursor` 不参与个性化分页。
- 旧 recommendation 值继续走现有实现。

响应继续使用 `ShougangPortalFileSearchResp`：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [],
    "has_more": false,
    "next_cursor": null
  }
}
```

返回数据只包含最终已确认有权文件的既有 `ShougangPortalFileItemResp`，不足 Top N 时不报错。

### 6.3 BiSheng 门户遥测（扩展既有接口）

```http
POST /api/v1/knowledge/shougang-portal/telemetry/events
```

新增搜索事件：

```json
{
  "event_type": "portal_search",
  "source_app": "shougang_portal",
  "scene": "knowledge_search",
  "entry_point": "search_page",
  "query": "安全生产",
  "normalized_query": "安全生产",
  "status": "success"
}
```

服务端规则：

- 用户身份、租户和 timestamp 由认证上下文/服务端补齐，不接受客户端冒充。
- `query` 去首尾空白、合并连续空格并统一英文大小写；中文原文保留。
- ES 事件字段至少包含 `user_id/query/normalized_query/source_app/scene/entry_point/timestamp`。
- 搜索成功后原子递增行为版本，并把本次 normalized query 与 timestamp 传给兴趣重算任务。

阅读事件扩展字段：

```text
entry_point =
  home_recommendation | recommendation_list | search |
  knowledge_space | direct | favorite | other
recommendation_scene = personalized_v1 | latest_selected | null
```

阅读事件接收时同步 ZADD 最近浏览、裁剪 90 天记录并递增行为版本；ES 写入仍沿用既有 telemetry。

成功响应：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "accepted": true
  }
}
```

### 6.4 门户管理 API

保留既有：

```text
GET  /api/v1/admin/config/recommendation
POST /api/v1/admin/config/recommendation
```

新增：

```text
GET  /api/v1/admin/config/department-business-domains
POST /api/v1/admin/config/department-business-domains
```

POST 请求：

```json
{
  "bindings": [
    {
      "department_id": 10,
      "business_domain_codes": ["PP", "SAFE"]
    }
  ]
}
```

门户先用本地同构 schema 校验并更新聚合配置，再由 `RemotePortalAdminConfigStore` 使用完整聚合 PUT 同步 BiSheng；远端失败时沿用配置存储现有的一致性/错误反馈策略，不把本地保存伪装成远端成功。

部门绑定管理接口成功响应：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "bindings": [
      {
        "department_id": 10,
        "business_domain_codes": ["PP", "SAFE"]
      }
    ]
  }
}
```

### 6.5 门户搜索遥测入口

新增登录用户 BFF 入口：

```http
POST /api/v1/knowledge/telemetry/search
Content-Type: application/json

{
  "query": "安全生产",
  "entry_point": "search_page"
}
```

`entry_point` 只允许 `search_page` 或 `home_hot_keyword`。BFF 使用当前会话 token 透传成 BiSheng `portal_search`；匿名搜索不生成用户兴趣事件。

成功响应：

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "accepted": true
  }
}
```

---

## 7. Domain Service 与 Repository 逻辑

### 7.1 分层与依赖

```text
config Router
  -> ShougangPortalConfigService
    -> PortalAdminConfigRepository
    -> DepartmentBusinessDomainRepository
      -> one shared DB transaction

Router
  -> existing shougang portal Endpoint
    -> KnowledgeSpaceService dispatch
      -> PortalRecommendationService
        -> DepartmentBusinessDomainService
          -> DepartmentBusinessDomainRepository
        -> PortalRecommendationProjectionRepository
        -> PortalRecommendationRedisRepository
        -> existing permission/file repositories
          -> DB / Redis / PermissionService
```

- Endpoint 只做认证、schema 和响应包装。
- 配置 Service 只编排两个 Repository；行锁、`with_for_update`、flush 和唯一冲突转换全部封装在 `PortalAdminConfigRepository`，不得在 Service 写 ORM。
- `KnowledgeSpaceService` 只负责识别 `personalized_v1` 并委托新 Service。
- 新 Service 不直接写 ORM 查询。
- DB/Redis 批量读写分别封装在 Repository 接口与实现中。
- 最终授权复用现有请求级权限上下文和文件可见性方法，不查询 `RoleAccessDao`。
- `common/telemetry` 只负责通用事件校验和 ES 写入；行为版本、Redis write-through 和兴趣任务由 knowledge 域的 `PortalRecommendationBehaviorService` 编排，禁止形成 `common -> domain` 反向依赖。

### 7.2 核心方法

| 组件/方法 | 输入 | 输出 | 职责 |
|-----------|------|------|------|
| `ShougangPortalConfigService.save_config` | aggregate config + admin | saved config | 规范化、版本递增、配置与绑定同事务 |
| `PortalRecommendationService.recommend` | request + login user | file DTO list | 整体编排、预算、兜底和观测 |
| `resolve_user_domains` | tenant/user | domain code set | 只读唯一主部门直接绑定 |
| `collect_candidates` | domains, interest, pool version | lightweight candidates | 全量相关池召回、去重、10000 熔断 |
| `score_candidates` | candidates + signals + config | ordered candidates | 动态归一化、浏览扣分、稳定打散 |
| `select_authorized_top_n` | ordered candidates + context | authorized IDs | 10/200/700ms 渐进权限检查 |
| `build_interest_top50` | user + current query | ZSET entries | 聚合 ES 90 天搜索并召回 Top 50 |
| `PortalRecommendationBehaviorService.record_search/read` | typed event + user | none | Redis write-through、行为版本递增和兴趣任务投递 |
| `refresh_projection` | file/subtree event | projection rows | 幂等更新资格、业务域和池成员 |
| `rebuild_shared_pools` | tenant + desired generation + heat config snapshot | pool version | 计算 hot/fresh、3:1 合并并执行防回退 CAS 切换 |

### 7.3 用户业务域解析

1. Repository 查询当前租户、当前用户所有 `UserDepartment` 中 `is_primary=true` 的记录。
2. 恰好 1 条时查询该 `department_id` 的直接绑定。
3. 0 条或多于 1 条时返回空集合并记录原因。
4. 不查询父部门 path，不展开 children，不读取次要部门。
5. 结果去重后缓存 30 分钟；绑定或主部门变化时主动失效。

### 7.4 兴趣候选

- 只为近期发生搜索或访问首页的活跃用户按需维护，不为全部注册用户预生成。
- 从 ES 取近 90 天最多 20 个去重 normalized query。
- 时间权重：0～7 天 1.0，8～30 天 0.7，31～90 天 0.4。
- 次数增强：`recency_weight * (1 + 0.2 * log(1 + count))`。
- ES should 查询字段权重：标题 4、标签 3、摘要 1。
- 当前搜索随任务参数传入并与 ES 结果去重合并，避免 ES refresh 延迟。
- 结果只保存 `space_id:file_id` 与兴趣分，最多 50，TTL 30 分钟。
- 权限与可见空间只在在线请求中按当前状态复核。

### 7.5 热度、新鲜度与池组装

热度使用近 30 天、按 `user_id + file_id + 自然日` 去重后的浏览：

- “自然日”固定按 `Asia/Shanghai` 计算；时间衰减仍按 UTC 时间戳秒差计算，不依赖 Worker 所在主机时区。
- 单次构池固定查询 `[now - 30 天, now]`，以 `timestamp + event_id` 执行 `search_after`；Repository 逐页完成自然日去重，只保留聚合后的事实，避免长期持有全部原始事件。
- 本期以固定查询上界保证分页集合不会持续向未来增长；ES PIT 作为后续的大规模一致性增强，不属于 F056 上线阻断项。

```text
source_weight = 1.0                                      # natural entry
source_weight = recommendation.home_entry_source_weight # home/list recommendation / unknown

decayed_view_count =
  sum(source_weight * 2 ** (-view_age_days / hot_half_life_days))

hot_score =
  min(log(1 + decayed_view_count) / log(1 + P95_decayed_view_count), 1) * 100
```

新鲜度：

```text
content_age_days = (now - source_update_time) / 86400
fresh_score = 100 * 2 ** (-content_age_days / 45)
```

池组装：

- 业务域池按当前租户、业务域、`recommendable=1` 生成。
- 通用池按当前租户全部 `recommendable=1` 生成。
- 默认目标 500：热门 375、新鲜 125，按“热门、热门、热门、新鲜”交错。
- 重复候选跳过并继续从对应流回填；某一路耗尽后由另一路补齐。
- 轮换状态按业务域池与通用池独立保存，执行连续 14 天 + 3 天冷却。
- 轮换日同样固定按 `Asia/Shanghai` 计算；只为实际进入 hot 子池及仍在冷却的文件保存状态，避免候选全集状态无界增长。

### 7.6 在线打分

特征权重固定：

| 特征 | 权重 | 有效条件 |
|------|-----:|---------|
| 主部门业务域匹配 | 0.30 | 用户业务域集合非空 |
| 搜索兴趣 | 0.40 | 用户存在兴趣信号 |
| 热门 | 0.15 | 始终有效 |
| 新鲜度 | 0.15 | 始终有效 |

```text
base_score = sum(active_weight * feature_score) / sum(active_weight)
final_score = base_score + read_penalty
```

浏览扣分不进入权重分母。稳定打散先按 `final_score DESC, file_id DESC` 得到基础顺序，再以每组最高分为锚点，把与锚点分差不超过 `stable_shuffle_score_gap` 的连续候选划为一组；组内按以下稳定哈希排序：

```text
sha256(tenant_id:user_id:cycle_bucket:space_id:file_id)
cycle_bucket = floor(current_date_ordinal / stable_shuffle_cycle_days)
```

该分组方式不允许相邻差值链式扩张到超过阈值的候选。

### 7.7 权限后置选择

1. 先取当前用户实时 `visible_space_ids`；请求若携带 `space_ids`，只取两者交集，再对投影做空间、状态、推荐资格的低成本收窄。
2. 对最多 10000 条轻量候选完成排序，不加载标题、摘要、标签和路径。
3. 建立一次请求级权限上下文。
4. 按排序每批 10 条处理：
   - 公共空间正常文件走既有公开快速路径。
   - 非公共空间调用既有完整 `view_file` 语义。
   - 单文件权限异常将该文件视为 deny 并继续下一候选。
5. 单请求内可复用已确认 allow/deny 结果，但不跨请求长期缓存文件权限。
6. 收集到配置 Top N、检查达到 200 或耗时达到 700 ms 即停止。
7. 第一轮不足时按 AC-12 合并通用池重新统一打分；池缺失或仍过少时从投影补入最多 500 个最新候选并再次统一打分，请求内复用已完成的权限结果。
8. 只对已确认有权 ID 批量加载详情并组装 DTO。
9. 若命中短期 Top N，仍先逐项复核权限；失效则丢弃缓存并重算。

权限上下文构建失败或权限引擎在本次选择中整体不可用时，选择器捕获该边界并固定返回当前已确认文件或空列表（HTTP 200），不得改用简化判权；Redis/DB/ES 编排、HTTP 传输或未被该权限边界吸收的系统异常才产生 HTTP 5xx，供门户触发 AC-39。

### 7.8 Top N 缓存与首页/更多一致性

缓存 key 包含租户、用户、`config_version`、`pool_version` 和 `behavior_version`。缓存值只保存有序 ID 与生成时间，不缓存 DTO 和权限结果。

- 首页读取完整 Top N 后只截取 `section_page_size`。
- “更多”读取同一完整 Top N。
- 新搜索或新浏览原子递增 `behavior_version`，自然绕过旧缓存。
- 配置保存产生新 `config_version`；热度池切换产生新 `pool_version`。

---

## 8. Worker 与一致性

### 8.1 任务清单

| 任务 | 触发 | 职责 |
|------|------|------|
| `refresh_portal_recommendation_projection` | 文件发布/删除/移动/状态/版本/业务域/ACL 变化 | 幂等 upsert 单文件或分页子树投影，更新受影响池成员 |
| `rebuild_user_interest_top50` | 显式搜索 | 聚合 ES 90 天搜索并合并当前查询，写用户兴趣池 |
| `invalidate_portal_recommendation_user_state` | 主部门或部门绑定变化 | 删除受影响用户业务域和 Top N key，不重建共享文件池 |
| `rebuild_portal_recommendation_pools` | 每 6 小时或热度配置变化 | 重算热度、轮换、新鲜路和共享池 |
| `reconcile_portal_recommendation_incremental` | 每日低峰 | 按 `update_time + file_id` watermark 分页补漏 |
| `reconcile_portal_recommendation_full` | 每周低峰 | 分页重建/核对投影与 Redis 池 |
| `purge_expired_portal_search_events` | 每日低峰 | 删除当前租户 90 天以前的 portal_search ES 原始事件 |
| `fanout_portal_recommendation_maintenance` | Celery Beat | 按既有 active tenant 机制投递租户任务 |

### 8.2 任务约束

- 路由到现有 `knowledge_celery` 队列。
- 发布时把 `tenant_id` 写入 headers；执行前由既有 hooks 恢复 ContextVar。
- 部门绑定变化只失效受影响用户的业务域/Top N 缓存，不重建文件共享池。
- 单文件投影以 `projection_version` 防止旧事件覆盖新状态。
- 子树刷新按固定批次分页，支持重试和重复执行。
- watermark 只有在当前页成功提交后推进。
- 搜索保留任务只删除当前租户的 `portal_search`，使用 UTC cutoff，delete-by-query 可重复执行。
- 全量对账不与在线请求共享大事务，不锁完整文件表。
- 文件变为 custom/不可推荐时先从共享池移除，再提交新投影状态；最终权限检查继续兜底。

### 8.3 双版本池

1. 每次热度参数变化或周期重算计划先对当前租户 `desired_generation` 执行原子 `INCR`，并把 generation、聚合配置版本及两个热度参数的 canonical fingerprint 作为任务不可变参数。
2. `pool_version` 使用该单调 generation；所有 domain/generic/hot/fresh/state key 写入对应版本命名空间。
3. 校验目标池数量、租户一致性、配置 fingerprint 和抽样投影。
4. Redis Repository 用 Lua/事务执行 CAS：仅当 `desired_generation == task_generation` 且 task generation 大于当前 active generation 时写入新的 `active_version`；否则把任务标记为 stale 并禁止切换。
5. `active_version` 同时保存 generation、pool_version 和 fingerprint；在线请求在一次调用开始时固定读取这一快照。
6. 旧任务即使晚完成也不能覆盖新 active version；失败或 stale 任务不改变 active pointer。
7. 旧版本至少保留一个 Top N TTL + 安全窗口后异步删除。
8. 任一构建/校验阶段失败都不切换 active version。

---

## 9. 门户 BFF 与前端设计

### 9.1 首页 SSE

保持 `GET /api/v1/knowledge/home` 的既有 SSE 事件、区块结构和前端消费方式。

登录态分流优先级：

1. 匿名用户：直接使用 `latest_selected`，保留 30 分钟公共首页缓存。
2. 登录用户且 `personalized_shadow_enabled=true`：
   - 立即按旧逻辑生成并返回首页。
   - 使用当前用户 token 在后台计算 `personalized_v1` 并只记录对比指标。
   - 影子模式优先于灰度比例，不向用户返回个性化结果。
3. 登录用户且影子模式关闭：
   - `raw = "{tenant_id}:{user_id}:personalized_v1".encode("utf-8")`。
   - `bucket = int.from_bytes(sha256(raw).digest()[:8], "big", signed=False) % 100`。
   - 桶值小于 `personalized_rollout_percent` 时请求 `personalized_v1`。
   - 未命中时继续旧逻辑。
4. 个性化请求失败：在当前请求内使用同一个用户 token 调用 `latest_selected`。

登录用户完整首页不读写 `PortalHomeCacheService` 的公共结果缓存。BiSheng 用户 Top N 缓存负责首页与“更多”短期顺序一致。首页 BFF 请求完整 Top N，只把前 `display.home.section_page_size` 条写入推荐 SSE 区块。

### 9.2 “更多”页

- 首页推荐区块的“更多”链接携带本次实际使用的 recommendation mode。
- `personalized_v1` 使用 `recommendation.home_total_count` 发起一次请求。
- 返回后直接展示全部结果；关闭无限滚动、后续 cursor 和“加载更多”入口。
- `latest_selected` 及其他列表模式保留现有分页/排序行为。
- 前端不得重新排序或重新计算分数。

### 9.3 独立部门业务域绑定界面

管理后台新增独立配置区，不嵌入现有 Domain 空间绑定卡片：

- 每行一个部门单选和业务域多选。
- 部门选择项来自当前组织树；同一部门不能重复出现。
- 业务域选择项来自当前 `domains` 配置，可绑定 1 个或多个。
- 不展示“包含子部门”开关，不暗示任何继承。
- 支持新增行、删除行、清空某部门全部绑定。
- 保存前显示字段级校验；保存成功后刷新服务端返回的规范化值和版本。

推荐配置区新增：

- 推荐总数。
- 热度半衰期。
- 首页推荐入口来源权重。
- 稳定打散分差阈值。
- 稳定打散变化周期。
- 影子模式开关。
- 0～100 灰度比例。

界面同时校验首页展示数与推荐总数的交叉关系；错误文案明确指出合法范围。

### 9.4 搜索遥测

前端只在三个显式动作调用 BFF 搜索遥测：

- 搜索框回车。
- 点击搜索按钮。
- 点击首页热门词并跳转搜索。

筛选、排序、分页、请求重试、URL 状态恢复和组件重渲染不得调用。上报与搜索请求使用独立的防重复动作 ID/同步 guard，单次用户动作最多提交一次；遥测失败不阻断搜索结果展示。

### 9.5 预览入口

前端和 BFF 将既有预览入口扩展为准确枚举：

| 页面来源 | `entry_point` | `recommendation_scene` |
|---------|-----------------|--------------------------|
| 首页个性化推荐 | `home_recommendation` | `personalized_v1` |
| 首页旧推荐 | `home_recommendation` | `latest_selected` |
| 个性化“更多”列表 | `recommendation_list` | `personalized_v1` |
| 搜索结果 | `search` | null |
| 知识空间/普通列表 | `knowledge_space` | null |
| 收藏 | `favorite` | null |

阅读事件在预览成功建立后只记录一次；预览重试不得重复制造同一自然日热度计数。

### 9.6 门户配置同步文档

门户技术方案 §12.2 和 §18 中原“新增两个 BiSheng 同步端点”的描述必须改为：

- 门户管理接口可以分区维护本地配置。
- `RemotePortalAdminConfigStore` 始终把完整聚合配置同步到既有
  `PUT /api/v1/shougang-portal/config`。
- BiSheng 在该聚合保存事务内规范化并同步部门绑定表。

---

## 10. API 错误与失败响应

本 Feature 不分配新 MMMEE 模块编码，不把推荐降级建模为业务错误。

| HTTP/Body | MMMEE Code | Error Class | 场景 | 处理 | 关联 AC |
|-----------|------------|-------------|------|------|---------|
| 401/403（既有认证响应） | —（复用既有认证错误） | `AuthJWTException` / `HTTPException` | 匿名调用个性化或非管理员修改/读取内部配置 | 沿用现有认证/管理员依赖 | AC-23, AC-24, AC-51 |
| 422（既有 schema 响应） | —（不新增业务码） | `RequestValidationError` | 字段越界、交叉数量非法、重复部门、无效编码 | 拒绝整个请求，不保存 | AC-06, AC-07 |
| HTTP 500 + body `status_code=500` | —（系统异常，不新增业务码） | `Exception` | 配置事务、Redis/DB/ES 编排或个性化传输失败 | 配置回滚；推荐请求由门户按 AC-39 降级 | AC-07, AC-08, AC-39 |
| 200 + 实际列表 | — | — | 单候选拒绝、权限选择整体异常、候选不足或达到预算 | 只返回已确认结果/空，固定无后续页 | AC-28～AC-31 |

任何新增业务错误类若在实现阶段确有必要，必须先更新 release contract 的模块编码表并重新评审；tasks.md 不得自行预造编码。

参数校验失败响应：

```json
{
  "status_code": 422,
  "status_message": [
    {
      "loc": ["body", "portal", "recommendation", "home_total_count"],
      "msg": "Input should be less than or equal to 50",
      "type": "less_than_equal"
    }
  ]
}
```

---

## 11. 文件清单

> 下列是规格阶段可预判的完整落点；迁移 revision 必须在实现时基于仓库全部 Alembic heads 生成，不能复用已存在的 F056 文件名。

### 11.1 BiSheng 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/shougang_portal_config/domain/models/department_business_domain.py` | 部门业务域绑定 ORM |
| `src/backend/bisheng/shougang_portal_config/domain/repositories/interfaces/department_business_domain_repository.py` | 绑定 Repository 接口 |
| `src/backend/bisheng/shougang_portal_config/domain/repositories/implementations/department_business_domain_repository_impl.py` | 绑定查询与同事务全量替换 |
| `src/backend/bisheng/shougang_portal_config/domain/repositories/interfaces/portal_admin_config_repository.py` | 租户化 Config key、锁定读取和非提交写入接口 |
| `src/backend/bisheng/shougang_portal_config/domain/repositories/implementations/portal_admin_config_repository_impl.py` | SQLAlchemy 行锁、flush、唯一冲突转换与共享事务实现 |
| `src/backend/bisheng/shougang_portal_config/domain/services/department_business_domain_service.py` | 绑定规范化、全量替换和只读查询边界 |
| `src/backend/bisheng/knowledge/domain/models/portal_recommendation_file_projection.py` | 推荐文件投影 ORM |
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_repository.py` | 投影、轻量候选和对账查询接口 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_repository_impl.py` | DB Repository 实现 |
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_state_repository.py` | Redis 状态接口 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_redis_repository.py` | 租户化 Redis key、pipeline、版本切换 |
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_telemetry_repository.py` | 近 90 天搜索查询与过期事件删除接口 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_telemetry_repository_impl.py` | tenant-aware ES 查询与 delete-by-query |
| `src/backend/bisheng/knowledge/domain/services/portal_recommendation_service.py` | 在线召回、打分、权限后置选择和缓存 |
| `src/backend/bisheng/knowledge/domain/services/portal_recommendation_projection_service.py` | 投影资格、业务域解析与增量维护 |
| `src/backend/bisheng/knowledge/domain/services/portal_recommendation_pool_service.py` | 热度、新鲜度、轮换、共享池与兴趣池 |
| `src/backend/bisheng/knowledge/domain/services/portal_recommendation_behavior_service.py` | 搜索/阅读派生状态、行为版本和异步兴趣任务 |
| `src/backend/bisheng/worker/knowledge/portal_recommendation.py` | 增量、兴趣、6 小时、每日、每周任务 |
| `src/backend/bisheng/core/database/alembic/versions/*_portal_recommendation.py` | 基于全部当前 heads 接续/合并的迁移；创建两张表和索引并最终保持单 head |
| `src/backend/test/shougang_portal_config/test_personalized_recommendation_config.py` | 聚合 schema、版本、事务和绑定测试 |
| `src/backend/test/knowledge/test_portal_recommendation_algorithm.py` | 算法、池组装、轮换和稳定打散测试 |
| `src/backend/test/knowledge/test_portal_recommendation_permission.py` | 权限矩阵和无泄露测试 |
| `src/backend/test/knowledge/test_portal_recommendation_api.py` | browse 与 telemetry 集成测试 |
| `src/backend/test/knowledge/test_portal_recommendation_worker.py` | 任务幂等、租户、版本和对账测试 |
| `src/backend/test/knowledge/test_portal_recommendation_migration.py` | MySQL/DM8 方言迁移结构测试 |

### 11.2 BiSheng 修改

| 文件 | 变更 |
|------|------|
| `src/backend/bisheng/shougang_portal_config/domain/schemas/portal_config_schema.py` | 同构绑定与推荐配置字段、默认迁移和校验 |
| `src/backend/bisheng/shougang_portal_config/domain/services/portal_config_service.py` | 服务端并发单调版本、同事务写配置和绑定 |
| `src/backend/bisheng/shougang_portal_config/api/endpoints/portal_config.py` | 返回服务端新版本，保持既有路由 |
| `src/backend/bisheng/knowledge/domain/constants.py` | `personalized_v1` 与硬预算常量 |
| `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py` | 个性化/遥测 schema 字段 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | browse 分流、阅读 write-through 与既有权限上下文复用 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_utils.py` | 仅在需要时提取复用的业务域解析 helper |
| `src/backend/bisheng/knowledge/api/endpoints/shougang_portal.py` | Endpoint 委托和 schema 响应，不组装算法 |
| `src/backend/bisheng/common/constants/enums/telemetry.py` | `PORTAL_SEARCH` 枚举 |
| `src/backend/bisheng/common/schemas/telemetry/event_data_schema.py` | 搜索及阅读来源字段 |
| `src/backend/bisheng/common/telemetry/portal_event_service.py` | 仅扩展 portal_search 校验和 ES 事件写入，不反向依赖 knowledge 域 |
| `src/backend/bisheng/user/domain/services/user_department_service.py` | 主部门事务成功后投递用户推荐状态失效任务 |
| `src/backend/bisheng/core/database/tenant_filter.py` | 强制导入两张新租户表模型，确保自动过滤和写入填充生效 |
| `src/backend/bisheng/core/config/settings.py` | 任务路由与 6 小时/每日/每周调度 |
| `src/backend/bisheng/worker/__init__.py` | 注册推荐任务 |

### 11.3 门户新建

| 文件 | 说明 |
|------|------|
| `frontend/src/pages/admin/DepartmentBusinessDomainBindingsPanel.tsx` | 独立部门单选/业务域多选面板 |
| `frontend/src/pages/admin/RecommendationPersonalizationPanel.tsx` | 推荐数量、算法、影子和灰度控件 |
| `backend/tests/test_department_business_domain_config.py` | 门户管理 API 和同步测试 |
| `backend/tests/test_personalized_home.py` | 登录/匿名 SSE、灰度、影子和降级测试 |
| `backend/tests/test_portal_search_telemetry.py` | 显式搜索和预览入口测试 |
| `frontend/tests/departmentBusinessDomainBindings.test.ts` | 独立绑定界面测试 |
| `frontend/tests/personalizedRecommendation.test.ts` | 首页/更多/配置/灰度前端测试 |
| `frontend/tests/searchTelemetry.test.ts` | 显式动作去重测试 |

### 11.4 门户修改

| 文件 | 变更 |
|------|------|
| `docs/specs/2026-07-14-首页个性化推荐技术方案.md` | 配置同步章节改为复用聚合接口 |
| `backend/app/schemas/portal_config.py` | 同构 schema、默认迁移、字段/交叉校验 |
| `backend/app/config/portal_config.py` | 默认配置与兼容加载 |
| `backend/app/api/routes/admin_config.py` | 新增部门业务域管理 GET/POST |
| `backend/app/api/routes/knowledge.py` | SSE 分流、搜索遥测入口和预览来源 |
| `backend/app/services/portal_config_service.py` | 分区更新聚合配置与远端同步 |
| `backend/app/services/portal_admin_config_store.py` | 内部 GET 使用 runtime 配置的租户管理员 token，保存后接受服务端新版本 |
| `backend/app/services/knowledge_service.py` | 透传 `personalized_v1`、Top N 和安全降级 |
| `backend/app/services/portal_home_cache_service.py` | 登录用户绕过完整首页缓存 |
| `backend/app/services/portal_telemetry_service.py` | 搜索及阅读扩展字段透传 |
| `backend/tests/test_portal_config_service.py` | 旧配置迁移、交叉校验、远端聚合同步 |
| `backend/tests/test_portal_admin_config_store.py` | 内部接口认证、租户隔离和服务端版本响应 |
| `backend/tests/test_portal_home_cache_service.py` | 匿名保留、登录绕过 |
| `frontend/src/pages/AdminPage.tsx` / `.module.css` | 挂载独立面板并保持现有页面结构 |
| `frontend/src/pages/HomePage.tsx` | 使用 SSE 给出的实际推荐模式构造“更多”和预览入口 |
| `frontend/src/pages/ListPage.tsx` | 个性化一次加载、禁用后续分页 |
| `frontend/src/pages/SearchPage.tsx` | 三类显式搜索动作上报且去重 |
| `frontend/src/api/content.ts` | 配置、搜索遥测、个性化列表和预览 DTO/API |
| `frontend/tests/latestSelectedRecommendation.test.ts` | 验证旧推荐回归兼容 |
| `frontend/tests/portalConfig.test.ts` | 新字段兼容和校验 |
| `frontend/tests/listPageContext.test.ts` | 个性化列表上下文和一次加载 |
| `frontend/tests/filePreview.test.ts` | 入口与 recommendation scene |

---

## 12. 非功能要求与可观测性

### 12.1 性能硬预算

```text
MAX_LIGHTWEIGHT_CANDIDATES = 10000
PROJECTION_FALLBACK_LIMIT = 500
PERMISSION_BATCH_SIZE = 10
MAX_PERMISSION_CHECKS = 200
RECOMMENDATION_TIME_BUDGET_MS = 700
MAX_HOME_RECOMMENDATION_TOTAL_COUNT = 50
```

目标：

- 最多 10000 条轻量候选打分与排序 < 30 ms。
- 推荐接口 P95 < 800 ms。
- 首页首个 SSE 区块 P95 < 1 s。
- 目标空间规模：1、20、100、200；业务域数量：1、3、10。

### 12.2 安全与隔离

- 遵守继承的 INV-1～INV-15 与本版本 INV-SG-1～INV-SG-12。
- 新表注册租户自动过滤；业务代码不手写 `WHERE tenant_id = ...`。
- Redis 使用既有租户前缀 helper；ES 查询和 Celery 恢复当前租户。
- 不记录搜索原文、文件标题、用户姓名或无权文件标识到普通性能日志。
- 配置管理要求既有管理员认证；推荐和遥测使用当前登录用户。
- 任何权限不确定状态都失败关闭。

### 12.3 结构化日志

新增事件名 `portal_home_recommendation_perf`，至少包含：

```text
trace_id, tenant_id, user_id_hash,
visible_space_count, user_domain_count,
domain_candidate_count, interest_candidate_count, generic_candidate_count,
merged_candidate_count, lightweight_candidate_count,
permission_checked_count, permission_denied_count,
read_penalized_candidate_count, hot_cooldown_filtered_count,
fallback_level, result_count,
signal_ms, candidate_ms, permission_context_ms, permission_ms,
score_ms, total_ms, cache_hit_flags,
config_version, pool_version, shadow_mode, rollout_bucket
```

指标：

- P50/P95/P99、空结果率、降级率。
- 10000 候选与 200 权限检查熔断次数。
- 权限拒绝率、权限服务异常率、投影滞后率。
- 兴趣池命中率、通用兜底读取率、兜底后补足率。
- 3:1 池比例、去重回填、14+3 冷却过滤数。
- 首页推荐来源浏览占比、推荐点击率、近 7/30/90 天已读曝光占比。
- 配置重算成功/失败、active pool 切换和对账修复数。

---

## 13. 上线与回滚

上线顺序固定：

1. MySQL/DM8 数据迁移、投影初始化和池预热。
2. 开启影子模式，首页继续返回旧结果。
3. 关闭影子模式，灰度 10%。
4. 扩大到 50%。
5. 扩大到 100%。

每阶段观察至少包括权限拒绝率、空结果率、P95、降级率、已读曝光和点击率。异常时将 `personalized_rollout_percent` 调为 0；不回滚或删除 ES 行为、Redis 派生状态和 DB 投影，问题修复后可重新预热启用。

---

## 相关文档

- [v2.5.0-sg Release Contract](../release-contract.md)
- [v2.5.0 基线 Release Contract](../../v2.5.0/release-contract.md)
- [首页个性化推荐技术方案](../../../../shougang-group-knowledge-portal/docs/specs/2026-07-14-首页个性化推荐技术方案.md)
- [SDD 模板](../../_templates/spec.md)
