# Feature: F040-rebac-read-path-perf-rollout（ReBAC 读路径性能范式收尾：频道详情 / 空间广场列表 / 工作台列表）

> **本文档定位 — 纯 What（需求口径，不随代码漂移）**
> spec 只回答 **做什么 / 验收标准 / 不做什么**。所有 How（上下文复用怎么传、batch_check 怎么拼、cursor 怎么编、fetch-while-filter 循环怎么写）一律写在 [design.md](./design.md) 与 [tasks.md](./tasks.md)。
>
> **前置步骤**：已完成 Spec Discovery。本特性源于线上体感排查（详见根因记录 `knowledge_space_slow.md` / `knowledge_files_slow`）：
> 频道广场预览弹窗、知识空间广场列表（`/joined` / `/department`）、工作台/应用高频列表在数据或人数一多时显著变慢，
> 实测归因为**同一类反模式的三处残留**——逐项 N+1 权限检查 + 每请求重建整套 ReBAC 上下文 + 先全量加载再 Python 过滤再切片。
> 这三类病灶在 [F027](../027-rebac-list-perf-optim/spec.md)（cursor 分页解决"扫多少项"）、[F036](../036-rebac-eval-cost-optim/spec.md)（继承快速通道解决"每项多贵"）、[F037](../037-knowledge-space-pin-decouple/spec.md)（频道权限上下文一次构建跨频道复用）中**已被验证修复**，本特性把这些范式铺到尚未覆盖的读路径接口。

**关联 PRD**: 2.6 性能优化（OpenFGA / ReBAC 读路径）；承接 F027 / F036 / F037 同一性能主线
**优先级**: P0（频道详情、空间广场、应用列表均为日常最高频读操作，随租户数据/人数增长持续劣化）
**所属版本**: v2.6.0（合入 `feat/2.6.0-beta4` 分支）
**模块编码**: 复用 190(`channel`)、180(`knowledge_space`)、105(`flow`/app)、`workstation` 现有模块；**不新增错误码**（cursor 化复用 F027 既有 `AppInvalidCursorError`(10550) / `KnowledgeSpaceInvalidCursorError`(18070)）；**新增 1 个对外 API** `GET /channel/manager/{id}/unread-counts`（子频道未读数从详情接口拆出，按用户懒加载）
**依赖**: F004（ReBAC core）、F008（resource-rebac-adaptation）、F027（cursor 协议 INV-6 + `common/cursor.py`）、F036（细粒度评估优化范式）、F037（频道权限上下文复用 `_build_channel_permission_context`）

> **范围边界**
> - **本次纳入**（三组能力，统一原则：**只改"怎么算/怎么取"，不改"算出什么"**；语义对改造前逐位等价）：
>   - **A. 频道详情预览**（`GET /channel/manager/{id}`）：①权限计算复用 F037 一次构建的频道权限上下文，不在 detail 路径重建整套 ReBAC 上下文；②**详情接口不再计算/返回子频道未读数**——未读拆为**独立懒加载端点** `GET /channel/manager/{id}/unread-counts`：预览弹窗与 in-channel 共用变廉价的详情接口，未读仅在用户进入频道后按需拉取填角标；该未读端点内部把逐子频道 × 逐已读分片的 ES count 合并为**常数级 `msearch` 往返**（`count_articles_batch`）；③去掉重复的 membership 查询；④**频道文章总数**经 Redis 短 TTL 缓存层取数（频道详情 / 广场命中缓存即不查 ES；子频道 per-user 未读数因用户相关不进缓存）。
>   - **B. 空间广场列表**（`/space/joined`、`/space/department`、`list_uploadable_spaces`）：把逐空间 N+1 权限检查改为**批量 + 一次构建跨空间共享上下文**（OpenFGA `batch_check` 算 permission_level、F036 共享上下文算 effective_permission_ids、`list_uploadable_spaces` 并行化）。**保持"一次性返回全部可访问空间"的现有契约不变**（不引入 cursor、不改前端 UX）。
>   - **C. 工作台/应用高频列表**（助手列表 `GET /assistant`、工作台「最近」「常用」「推荐」、知识空间内文件**搜索** `search_space_children`）：消除"先全量加载 → Python 逐条过滤权限 → 切片"反模式，使后端扫描/过滤量由请求页规模与可见集决定、不随租户内该资源总量线性增长。凡保留分页语义的列表遵循 INV-6 cursor 协议（复用 F027 `common/cursor.py` 与既有 `*InvalidCursorError`）。**注**：`/knowledge`、`/workflow/list`、知识空间**浏览** `list_space_children`（`/children`）已由 F027 迁移 cursor，**不在本组**；本组针对的是上述**仍为 fetch-all** 的残留端点（经 2026-06-25 代码核实，5 个端点均仍 `page=0,limit=0` 全量加载后 Python 切片）。
>   - **D. 知识空间侧边栏权限检查懒加载**（client `/workspace` 前端）：打开知识空间界面时**不再**在侧边栏渲染期对全部空间批量发起 `POST /api/v1/permissions/check`（现状 N 空间 × 4 权限 = 数十个并发请求）；改为**用户点开某空间「⋯」操作菜单时**才按需查询该空间权限，决定渲染哪些操作按钮。纯前端改造（后端 `permissions/check` 单查端点不变，懒加载天然规避其无 batch 能力的限制）。
>   - **E. 权限上下文「名册」的版本派生 key 跨请求缓存**（后端）：经 2026-06-25 核实，每个 ReBAC 读请求（典型为知识空间侧边栏逐层展开的 `/children`，service 每请求新建）都重新 **DB 读取 + 全量 JSON 解析 + 重建索引** 整份关系绑定名册（`_get_bindings` → `ConfigDao.aget_config_by_key` 无缓存），并重查用户主体串——展开 N 层即把这套"名册"从头建 N 遍。本组按 **bindings / 关系模型配置行的版本/哈希** 派生 key 缓存"已解析 + 已建索引"的名册、按**用户主体版本**派生 key 缓存主体串，跨请求复用。采用 F036 design §8 背书的「读侧从数据版本派生 key」解耦路径：配置/组织关系一变 key 自然失效，**不**在授权/部门/组织同步写路径挂失效钩子。
> - **本次明确排除**：
>   - **侧边栏 `/children` 的前端重复并发去重 + N 个文件夹 LIKE 计数合并不做**：属另案，本期不纳入（避免与已发布优化重叠）。注：`/children` 的**逐项评估**成本已由 F036 解决；其**每请求重建名册**的成本由本特性 **E 组**解决（见上）。
>   - **不引入 F036 否决的那类跨请求缓存**：即**不**提升 `permission_cache` TTL、**不**在授权/部门/组织同步写路径挂失效钩子来跨请求复用权限上下文（F036 design §3 决策 4 就其跨域失效耦合代价做出否决，本特性沿用）。E 组引入的是**另一种**缓存——按数据版本派生 key、读侧自然失效、零写路径耦合（F036 design §8 明确背书的路径），与被否决方案不同。
>   - **不改变任何权限语义 / 不放宽可见性**：可见结果、permission_ids、订阅态、未读数必须与改造前逐项计算逐位等价（含 INV-7）。
>   - **/joined、/department 不加分页 / 不改前端**：用户确认保持全返回契约。
>   - 不改 OpenFGA 模型、relation-model / binding 数据模型、授权写入 UI（归 F004/F008/资源授权页）。
>   - 不做 OpenFGA / DB 扩容、worker 数调整等运维侧动作（另议）。
>   - 频道授权用户列表（`list_channel_grant_users`）**已是 SQL 层分页 + 批量 enrich**，无需改动。

---

## 1. 用户故事

**故事 A（业务用户 · 频道广场）**：
作为 **频道广场的浏览者**，
我希望 **点开频道预览弹窗时详情秒级出现**，
以便 **快速判断要不要订阅，而不是对着转圈等待**。

**故事 B（业务用户 · 知识空间）**：
作为 **加入了多个知识空间 / 处在大部门的用户**，
我希望 **打开"我加入的空间""部门空间"列表时首屏不再卡顿**，
以便 **空间一多也能正常进入工作**。

**故事 C（业务用户 · 工作台）**：
作为 **租户内应用 / 文件众多的使用者**，
我希望 **应用列表、工作台「最近 / 常用」、空间内文件搜索在内容多时仍然快**，
以便 **列表速度不随数据增长变得不可预测**。

**故事 D（运维 / SRE）**：
作为 **负责 OpenFGA / 后端 / ES 容量的运维**，
我希望 **这三类高频读接口对 ReBAC、DB、ES 的开销不随"可访问对象数 / 子频道数 / 租户资源总量"线性放大**，
以便 **同样机器扛住更高并发，P99 不抖**。

**故事 E（权限域维护者）**：
作为 **权限域维护者**，
我希望 **这轮优化只改"怎么算 / 怎么取"、绝不改"算出什么"，且不把权限失效逻辑泄漏进其它领域写路径**，
以便 **被单独授权约束的内容不会因优化被越权看到，也不引入跨域耦合**。

**故事 F（业务用户 · 知识空间侧边栏）**：
作为 **侧边栏里有很多知识空间的用户**，
我希望 **打开知识空间界面时不要先把每个空间能做哪些操作都预判一遍**，
以便 **首屏不被几十个权限检查请求拖慢；真正点开某个空间的操作菜单时再判断它的按钮即可**。

**故事 G（业务用户 · 逐层展开文件夹）**：
作为 **在知识空间侧边栏一层层往深展开文件夹的用户**，
我希望 **越往深点开，等待不要越来越久**，
以便 **这个最高频的操作不再每展一层都重新"翻一遍全公司的权限名册"**。

---

## 2. 验收标准

> P0，采用 EARS 句型。AC-ID 本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 2.1 语义等价（最高优先级 — 安全红线，各组能力共用）

- **AC-01** — THE SYSTEM SHALL 对任意 `(user, 资源, 过滤条件)`，A/B/C 各组后端接口优化后返回的对象集合、`permission_ids`、可见性标记与优化前**逐项评估 / 全量过滤**结果**完全一致**（同一组 id、同序、同权限标记）。（D 组菜单按钮的等价性见 AC-20。）
- **AC-02** — THE SYSTEM SHALL 维持 INV-7：列表 UI 不可见的 `file`，其 chunk / 文件名 / 来源不得出现在任何 AI 问答可检索路径（本特性不放宽该子集关系）。
- **AC-03** — IF 任一优化路径无法确定某项是否可见，THEN THE SYSTEM SHALL 回落完整评估（fail-closed），不得放行。

### 2.2 A · 频道详情预览（`GET /channel/manager/{id}`）

- **AC-04** — WHEN 请求频道详情, THE SYSTEM SHALL 用**一次构建**的频道权限上下文（F037 `_build_channel_permission_context`）计算 `permission_ids`，不在 detail 路径重新加载 models / bindings / 用户主体串 / 部门路径。
- **AC-05** — THE SYSTEM SHALL 把子频道未读数从 `get_channel_detail` 中**移除**，改由独立端点 `GET /channel/manager/{id}/unread-counts` 按当前用户**懒加载**提供；频道详情响应**不再含** `sub_channel_unread_counts`（预览弹窗不触发任何未读计算）。WHEN 该未读端点被调用, THE SYSTEM SHALL 把 `S × (1 + ⌈R/1000⌉)` 次 ES count（S=子频道数、R=用户已读文章数）合并为**常数级 `msearch` 往返**（`count_articles_batch`），不随 S × R 线性放大；in-channel 视图（`ArticleList`）进入频道后**独立**调该端点填角标，与详情请求解耦。IF 未读端点失败 / 超时, THEN THE SYSTEM SHALL 角标降级为 0 / 不显示，**不**阻塞文章列表与子频道切换。
- **AC-06** — THE SYSTEM SHALL 在单次 detail 请求内对同一用户的 membership **至多查询一次**（命中即复用于可访问判定与订阅态判定，不再二次 `find_membership`）。
- **AC-07** — WHERE 频道详情 / 频道广场需要**频道文章总数**, THE SYSTEM SHALL 经 Redis 短 TTL 缓存层取数（按 `(tenant_id, channel_id, 主过滤规则)` 缓存频道主计数）：缓存命中时**不**查 ES；未命中或 Redis 不可用时回落实时 ES count 并回填缓存。**子频道 per-user 未读数因用户相关不进缓存。**

### 2.3 B · 空间广场列表（`/space/joined`、`/space/department`、`list_uploadable_spaces`）

- **AC-08** — WHEN 请求 `/space/joined` 或 `/space/department`, THE SYSTEM SHALL 用**单次 OpenFGA `batch_check`** 计算页内全部候选空间的 `permission_level`，不再逐空间发起独立 `get_permission_level`。
- **AC-09** — WHEN 计算各空间的 `effective_permission_ids`, THE SYSTEM SHALL 用**一次构建、跨空间共享**的权限上下文评估（F036 `filter_object_ids_by_permission_async` 范式），不再逐空间重建上下文。
- **AC-10** — WHEN 请求 `list_uploadable_spaces`, THE SYSTEM SHALL 以并行 + 共享上下文评估各候选空间，不再以串行 `for` 循环逐空间 `_get_effective_permission_ids`。
- **AC-11** — THE SYSTEM SHALL 保持 `/space/joined`、`/space/department` 的**现有响应契约**：一次性返回全部可访问空间，不引入 `cursor` / `has_more`，前端不变。

### 2.4 C · 工作台/应用高频列表（助手列表 / 工作台「最近」「常用」「推荐」/ 空间内文件搜索）

> 范围与现状：经 2026-06-25 代码核实，本组 5 个端点（`GET /assistant`、工作台 `frequently_used` / `used` / `recommended`、`search_space_children`）**均仍为 fetch-all**（`page=0,limit=0` 全量加载 → Python 权限过滤 → 手动切片）；`/knowledge`、`/workflow/list`、知识空间浏览 `/children` 已由 F027 迁移 cursor、**不在本组**。

- **AC-12** — THE SYSTEM SHALL 使上述列表的后端**不再先全量加载符合条件的全部行、再在 Python 中逐条过滤权限、再切片**；扫描 / 过滤量由请求页规模与可见集决定，不随租户内该资源总量线性增长。
- **AC-13** — WHERE 列表保留分页语义, THE SYSTEM SHALL 采用 INV-6 cursor 协议（响应含 `has_more` / `next_cursor`、不返 `total` / `page_num`，cursor 编解码走 `common/cursor.py`）。
- **AC-14** — IF 提交篡改 / 过期 / 非法 cursor, THEN THE SYSTEM SHALL 返回既有 `*InvalidCursorError`（105 段 `AppInvalidCursorError` 10550 / 180 段 `KnowledgeSpaceInvalidCursorError` 18070），**不**静默 fallback 首页。
- **AC-15** — WHERE 某列表本身无需深翻（如「推荐」这类 capped 小集合）, THE SYSTEM SHALL 至少改为有界拉取 + 共享上下文过滤（可不引入 cursor），不得保留无界全量加载。

### 2.5 D · 侧边栏权限检查懒加载（client `/workspace` 前端）

- **AC-16** — WHEN 用户打开知识空间界面 / 侧边栏首次渲染, THE SYSTEM SHALL **不**对列表中的空间批量发起 `POST /api/v1/permissions/check`（不在 mount 期对全部空间 × 各操作权限预取）。
- **AC-17** — WHEN 用户点开某个空间的「⋯」操作菜单（菜单 `onOpenChange` 为 true）, THE SYSTEM SHALL 此时才查询**该空间**的相关操作权限，并据结果渲染对应操作项（设置 / 成员管理 / 删除 等）。
- **AC-18** — WHEN 同一空间的操作菜单被重复打开, THE SYSTEM SHALL 复用首次查询结果（请求内 / 组件级缓存），不重复发起相同权限检查。
- **AC-19** — WHILE 该空间权限正在查询中, THE SYSTEM SHALL 展示加载 / 禁用态而非过早渲染受限按钮；IF 查询失败, THEN THE SYSTEM SHALL 默认隐藏受权限约束的操作项（fail-closed），与改造前"无权限即不显示"一致。
- **AC-20** — THE SYSTEM SHALL 保持懒加载后菜单**最终呈现的操作项集合**与改造前（渲染期预取）对同一 `(user, space)` **完全一致**；超级管理员短路授予全部操作的现有行为不变。

### 2.6 E · 权限上下文「名册」版本派生 key 跨请求缓存（后端）

- **AC-21** — THE SYSTEM SHALL 跨请求复用"已解析 + 已建索引"的关系绑定名册（bindings）与关系模型（models），缓存 key 由其配置行的**版本 / 内容哈希**派生；命中时不再重新 DB 读取 + 全量 JSON 解析 + 重建 binding_index。
- **AC-22** — THE SYSTEM SHALL 跨请求复用用户主体串（user_subject_strings），按**用户主体版本**（所属用户组 / 部门的变更版本）派生 key 缓存。
- **AC-23** — IF bindings / models / 用户主体发生变更, THEN THE SYSTEM SHALL 在变更可见后**不再**返回旧缓存（版本 / 哈希 key 随数据变更而改变，读侧自然失效）；**不**在授权 / 部门 / 组织同步等写路径挂失效钩子。
- **AC-24** — THE SYSTEM SHALL 保证缓存命中结果与实时构建结果**等价**（同一 `(user, 资源)` 可见性判定不因缓存产生偏差）；IF 版本 / 哈希不可得, THEN THE SYSTEM SHALL 回落实时构建（fail-safe，绝不返回可疑旧名册）。
- **AC-25** — THE SYSTEM SHALL 使缓存按 `tenant_id` 隔离，跨租户不得命中彼此的名册 / 模型 / 主体串。

### 2.7 性能与开销下降（可验证，目标值与基线记 design §7）

- **AC-26** — WHEN 以频道详情压测脚本对 `/channel/manager/{id}` 施压, THE SYSTEM SHALL 使该接口对 DB + OpenFGA + ES 的总往返数较改造前下降（具体阈值记 design §7），且不引入新的失败响应。
- **AC-27** — WHEN 命中频道文章总数缓存, THE SYSTEM SHALL **不**对 ES 发起该频道的 count 查询；频道详情 / 广场对 ES 的文章计数调用数随缓存命中率下降。
- **AC-28** — WHEN 对拥有 N 个可访问空间的用户请求 `/space/joined`, THE SYSTEM SHALL 使 OpenFGA 调用数从 O(N) 降为 O(1)~O(常数批)（`batch_check` 合并 + 共享上下文）。
- **AC-29** — WHEN 打开含 N 个知识空间的侧边栏, THE SYSTEM SHALL 使首屏 `permissions/check` 请求数从改造前的 O(N × 操作权限数) 降为 **0**（仅在用户实际点开菜单时按需产生）。
- **AC-30** — WHEN 同一用户连续展开知识空间侧边栏的 N 层文件夹（N 个 `/children` 请求、其间名册版本未变）, THE SYSTEM SHALL 把名册「DB 读取 + 全量解析 + 重建索引 + 主体串构建」从 N 次降为 1 次（其余 N−1 次命中缓存）。

### 2.8 静态可验证

- **AC-31** — 维护者对改造后代码静态扫描：
  - `get_channel_detail` 调用 `_get_channel_permission_ids` 时**传入** `context`（不再走无 context 的重建分支）；`get_channel_detail` **不再调用** `_calculate_sub_channel_unread_counts`（未读迁至独立端点，该端点内走 `count_articles_batch`/`msearch`）；detail 路径 `find_membership` 调用点合并为 1 处；频道文章总数取数经 Redis 缓存层封装（命中不查 ES）。
  - `_format_accessible_spaces` 内**无**逐空间 `get_permission_level` 循环；改为单次 `batch_check` + 共享上下文过滤。`list_uploadable_spaces` 内**无**串行 `await self._get_effective_permission_ids(...)` 的 `for` 循环。
  - C 组各列表服务内**无** `page=0, limit=0`（全量加载）后接 Python 切片的写法；保留分页的走 cursor（`decode_cursor` / `encode_cursor`）。
  - 客户端侧边栏**不再**在挂载期对空间集合 `map` 出批量 `checkPermission` 调用（原 `useKnowledgeSpaceActionPermissions` 的渲染期预取被移除 / 改造）；权限检查发起点位于「⋯」菜单的 `onOpenChange` 回调内。
  - E 组名册 / 模型 / 主体串缓存 key **由数据版本 / 哈希派生**（grep 可见 key 含版本 / 哈希成分），授权 / 部门 / 组织同步写路径**无**新增缓存失效调用（验证零写路径耦合）。
  - **除（A）频道文章总数短 TTL 计数缓存与（E）版本派生 key 名册缓存外，无其它跨请求权限缓存引入**：单请求内的 `context` / `tuple_cache` 等结构生命周期不超出单次请求；`permission_cache` TTL 未被改动。

---

## 3. 边界情况

- **频道无子频道 / 无信息源**：未读数批量查询输入为空时返回空结果，不报错、不发空 ES 请求。
- **用户对频道无任何 membership**：detail 仍按现有逻辑返回（可访问性由权限上下文判定），单次 membership 查询为 None 时不再触发二次查询。
- **空间广场候选集为空**：`batch_check` 输入为空时跳过 OpenFGA 调用，直接返回空列表。
- **同一请求内多空间 / 多项共享祖先**：祖先的 tuple 与决策只取一次、跨项复用（沿用 F036 行为，不得每项重取）。
- **绑定落在更近层级**：项 / 空间存在比继承决策更近的绑定且不授权当前用户 → **必须**走完整评估，不得当继承项放行（沿用 F036 AC-02）。
- **cursor 解析失败**（base64 / json / `v` / `s` / `k` 长度任一不符）→ 抛对应 `*InvalidCursorError`；前端收到后整体 reset 列表回首页（前端契约层，沿用 F027 §3）。
- **OpenFGA / ES 不可用**：沿用现有 `RebacUnavailableError` / ES 失败兜底，不写半页、不误判 `has_more`、不把半失败错当作"无更多"。
- **文章总数缓存 miss / Redis 不可用（A）**：回落实时 ES count 并（Redis 可用时）回填，不报错、不阻塞详情返回。
- **文章刚摄入但缓存未过期（A）**：文章计数存在最长 ≤ TTL 的滞后窗口；因文章摄入为异步 Celery、非实时一致，该滞后可接受（不要求实时反映新摄入文章）。
- **文章总数缓存的租户隔离（A）**：缓存 key 必须含 `tenant_id`，跨租户不得命中彼此计数。
- **名册版本不可得 / 派生失败（E）**：拿不到 bindings/models 配置行版本或主体版本时，回落实时构建并不写缓存（fail-safe），绝不返回可疑旧名册。
- **名册刚变更（E）**：授权 / 关系模型配置一旦更新，版本 / 哈希 key 即不同，下一次读自然 miss 并重建——不存在"旧名册仍被服务"的窗口（区别于纯 TTL 缓存）。用户组织关系（组 / 部门）变更同理使其主体串 key 失效。
- **名册缓存的存储介质（E）**：进程内 LRU 还是 Redis 由 design 定；无论哪种，命中结果都须与实时构建等价、且按 `tenant_id` 隔离。
- **多租户**：沿用现有 `tenant_id` 自动注入，本特性不改该链路、不串数据。
- **菜单快速开合 / 连点（D）**：菜单查询进行中再次开合，不得重复发起相同请求；以 in-flight 去重或组件级缓存保证一个空间至多一次有效查询。
- **空间权限在菜单打开后变更（D）**：懒加载结果为打开瞬间的快照；权限随后被他人撤销不要求实时反映（与改造前预取快照行为一致；真正执行操作时后端仍有鉴权兜底，不构成越权）。
- **超级管理员（D）**：维持现有"短路授予全部操作"逻辑，不因懒加载触发任何 `permissions/check`。

---

## 4. 设计与实现（指针，不复制）

> **本节刻意不写内容。** 需要了解实现时按下表跳转——这些文档才是各自 How 的唯一真相：

| 你想知道 | 去哪看 |
|---|---|
| 三组能力各自的方案对比与取舍（为何复用 F037/F036 范式而非新建缓存层） | design.md §3 决策 |
| 频道详情上下文复用 / 未读拆分独立端点（响应契约变更 + 前端 ArticleList 改造）/ membership 合并 / 文章总数 Redis 缓存（key 规范、TTL、失效策略）的数据流 | design.md §4 / §6 |
| 空间广场 batch_check + 共享上下文的改造点与等价性保证 | design.md §4 / §5 |
| C 组各列表 cursor 化 / fetch-while-filter / accessible-id 预过滤的选型分流 | design.md §3 + §4 |
| D 侧边栏权限懒加载的前端改造点（`useKnowledgeSpaceActionPermissions` 移除/改造、菜单 `onOpenChange` 触发、组件级缓存） | design.md §4（前端） |
| E 版本派生 key 缓存的实现（版本/哈希怎么取、缓存介质进程内 LRU vs Redis、与 F036 否决方案的边界、等价性与 fail-safe 回落） | design.md §3 决策 + §4 + §5 |
| 关键约束（双 DB / 多租户 / 权限 / INV-6 / INV-7 / 错误码复用） | design.md §2 / §6 |
| 等价性如何验证（reference oracle）、已知坑 | design.md §5 |
| 基线与性能验证方法、目标阈值 | design.md §7 |
| 任务拆解、文件清单、执行顺序、踩坑落档 | tasks.md |

---

## 相关文档

- 设计真相: [design.md](./design.md)（接手第一入口，下一步产出）
- 执行与落档: [tasks.md](./tasks.md)
- 版本契约: [`../release-contract.md`](../release-contract.md)（INV-6 / INV-7 / 模块错误码边界；写 spec 前必读）
- 前序特性: [F027 ReBAC 列表性能优化](../027-rebac-list-perf-optim/spec.md) · [F036 ReBAC 逐项评估成本优化](../036-rebac-eval-cost-optim/spec.md) · [F037 知识空间 Pin 解耦（频道权限上下文复用）](../037-knowledge-space-pin-decouple/spec.md)
- 架构文档: `docs/architecture/10-permission-rbac.md`
- 根因记录: `knowledge_space_slow.md`、`knowledge_files_slow`（实测 trace 与归因）
