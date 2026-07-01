# Feature: F027-rebac-list-perf-optim（ReBAC 资源列表性能优化：Cursor 分页与无限滚动）

> **前置步骤**：已完成 Spec Discovery（架构师提问），PRD 不确定性已对齐；
> 已与产品确认：「无限滚动」的本质诉求是切换为 **cursor-based 分页**以根治翻深页 ReBAC 开销，
> 非纯 UI 改造。

**关联 PRD**: 飞书 wiki [2.6 beta3 PRD](https://dataelem.feishu.cn/wiki/RLZ2wa8GTiXC7FknbfGcaODPnPd) §6 OpenFGA 性能优化、§7 交互优化
**优先级**: P0（直接降低 ReBAC 请求量，影响所有租户的常用列表体验）
**所属版本**: v2.6.0（合入 `feat/2.6.0-beta3` 分支）
**模块编码**: 复用 109(`knowledge`)、105(`flow`)、150(`tool`)、180(`knowledge_space`) 现有模块；本特性新增 3 个错误码（见 §6.3）
**依赖**: F004（ReBAC core）、F008（resource-rebac-adaptation）、F011/F012/F013（多租户）

> **范围边界**
> - **本次纳入**：3 个高频列表接口（`knowledge` / `workflow/list` / `knowledge_space/children`）从 offset 分页改为 cursor-based 分页；`total` / 跳页 / 向前翻能力一并取消；4 个列表的前端改 `useInfiniteQuery` + 触底加载；部门树 `member_count` 字段移除。
> - **本次明确排除**：
>   - 工具列表（`GET /api/v1/tool`）后端结构不变（本来就无分页），只清理前端「共 X 个」文案；
>   - 单个部门 GET（`GET /api/v1/departments/{id}`）保留 `member_count`，PRD 未明示；
>   - 资源授权页部门树（`resource_permission.py`）保留 `member_count`，PRD 未明示；
>   - 其它带 `total` 字段的列表（用户、用户组、租户等）本期不动；
>   - 「跳到第 N 页」与「向前翻页」：cursor-based 天然只支持往后，前端 UI 也不再展现页码。

---

## 1. 概述与用户故事

**故事 A（普通业务用户）**：
作为 **管理后台/工作台的日常使用者**，
我希望 **打开知识库、应用、知识空间文件这些常用列表时，首屏更快出现，并能向下持续滑动而不是翻页**，
以便 **不再被「等待计数」拖慢首屏，也不再被频繁点页码打断思路**。

**故事 B（运维 / SRE）**：
作为 **负责 OpenFGA 集群容量的运维**，
我希望 **常用列表场景对 ReBAC 的请求量与 DB 的扫描量在翻深页时不再线性增长**，
以便 **OpenFGA 在高并发租户场景下不再成为瓶颈，减少 P99 抖动**。

**故事 C（前端研发）**：
作为 **平台/客户端前端研发**，
我希望 **后端列表协议明确返回 `next_cursor` 与 `has_more`、不再返回 `total`/`page_num`**，
以便 **统一切到 react-query 的 `useInfiniteQuery`，`pageParam` 即下一页 cursor，由框架管理翻页状态**。

**故事 D（后端研发）**：
作为 **资源域服务的维护者**，
我希望 **不再为了「算总数」或「跳到第 N 页 OFFSET」而把所有可见项都跑一遍 ReBAC 过滤**，
以便 **删除冗余的 `count` 查询与冗余的扫描循环；翻深页的开销不再随页号线性增长**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 2.1 通用 Cursor 协议（后端）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 任意已登录用户 | `GET /api/v1/knowledge?page_size=20&type=0` 与 `type=1`（文档知识库与 QA 知识库均覆盖） | 响应不含 `total` / `page_num` 字段；响应含 `data: [...]`、`page_size: 20`、`has_more: bool`、`next_cursor: string\|null`；查询不执行 `SELECT COUNT(*)` 或 `acount_user_knowledge` |
| AC-02 | 任意已登录用户 | `GET /api/v1/workflow/list?page_size=14&managed=true` | 同 AC-01 协议；`FlowDao.aget_all_apps()` 不再执行 `count_statement`；不再依赖 `OFFSET` 拉取，而是 `WHERE (排序键) > cursor LIMIT N` |
| AC-03 | 任意已登录用户 | `GET /api/v1/knowledge/space/{id}/children?page_size=20` | 同 AC-01 协议；`_scan_visible_child_items` 改造为：从 `WHERE (排序键) > cursor LIMIT batch_size` 拉批 → ReBAC 过滤 → 累计满 `page_size + 1` 即提前 `break` → 设 `next_cursor` 为本页最后一条 visible 的排序键 |
| AC-04 | 任意已登录用户 | 首次请求（不传 `cursor` 或 `cursor=""`） | 后端从排序起点开始拉取；返回的 `next_cursor` 反映当前页最后一条 visible item 的排序键；`has_more=true` 表示后端在「多取 1 条试探」时确实存在第 `page_size+1` 条可见项 |
| AC-05 | 任意已登录用户 | 携带上次响应的 `next_cursor` 续翻 | 后端解码 cursor → 用 `WHERE (排序键) > cursor` 拉下一段 → 与首页同协议返回；与切片前后位置严格不重不漏 |
| AC-06 | 任意已登录用户 | 后端确认无下一页（扫到 DB 末尾仍未满足试探条件） | `has_more=false`；`next_cursor=null`；`data` 长度可能为 0 或 ≤ `page_size` |

### 2.2 Cursor 编解码契约

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-07 | 后端 | 编码 cursor | 形如 `base64url(json({"v":1, "s":"<context>", "k":[<排序键 1 值>, ..., <id>]}))`；`v` 为 schema 版本号；`s` 为排序上下文签名字符串（编码当前 `sort_by` / `order_field+order_sort`）；`k` 为排序键元组（含主排序字段值 + `id` 兜底唯一） |
| AC-08 | 任意已登录用户 | 提交篡改、过期或非法 cursor（base64 解码失败、json 字段缺失、`v` 不支持、`s` 不匹配当前请求的排序上下文、`k` 长度与当前接口不符） | 返回 HTTP 200 body 含错误码：`KnowledgeInvalidCursorError`(10991) / `AppInvalidCursorError`(10550) / `KnowledgeSpaceInvalidCursorError`(18070)；**不**静默 fallback 第一页 |
| AC-09 | 前端 | 切换搜索关键词 / 排序字段 / filter 时 | react-query 的 `queryKey` 必须包含 `name` / `sort_by` / `type` / `managed` / `permission_id` / `file_type` 等过滤参数 → 参数变化自动 reset `pageParam` 到空（首页） |

### 2.3 ReBAC 请求量降级（静态可验证）

> 改用静态验证：通过 grep / 代码结构断言「关键扫描或计数调用已被移除、且批拉改为 cursor-driven」。
> 理由：PRD 原文是「取消对应接口调用」，本质是移除函数调用 + 拒绝 offset 翻深页；
> 静态验证零代价、不依赖 OpenFGA 版本或索引行为，更稳定。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-10 | 维护者 | 改造完成后对 `knowledge_space_service.py` 静态扫描 | `_scan_visible_child_items` 中 batch 拉取不再使用 `page=scan_page, page_size=BATCH_SIZE` 形式的 OFFSET 分页；改为 `WHERE (排序键) > cursor LIMIT BATCH_SIZE`；循环退出条件包含 `len(visible_page_items) > page_size`「凑够即停」语义并跟随 `break` |
| AC-11 | 维护者 | 改造完成后全仓 grep | `src/backend/bisheng/` 业务路径下 `acount_user_knowledge(` 调用方为 0；`FlowDao.aget_all_apps` 内部不再出现 `count_statement` 或 `func.count(sub_query.c.id)`；`SpaceFileDao.async_list_children` 调用方不再传 `page=N, page_size=BATCH_SIZE` 翻页参数 |

### 2.4 工具列表（前端）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-12 | 管理后台访问者 | 打开 `/build/tools`（或对应工具列表入口） | 工具列表 UI 上不再出现「共 X 个」「合计 X」类文案；后端响应结构保持不变（不动 `/api/v1/tool`） |

### 2.5 部门树 member_count 移除

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-13 | 任意已登录用户 | `GET /api/v1/departments/tree` | 响应中每个节点 **不再含** `member_count` 字段；`UserDepartment` 上的 `GROUP BY COUNT(*)` 查询被移除（`count_result`、`count_map` 等本地变量同步删除） |
| AC-14 | 任意已登录用户 | 「系统管理 → 部门」(`SystemPage/components/Departments.tsx`) 与「部门知识空间」(`DepartmentPage/index.tsx`) | UI 右侧详情面板上不再显示「成员数: N」字样；前端 `Department` 类型不再含 `member_count` |
| AC-15 | 任意已登录用户 | `GET /api/v1/departments/{id}`（单部门详情） | **保留** `member_count` 字段（PRD 未要求移除；保持现状） |
| AC-16 | 任意已登录用户 | 资源授权页部门树（`resource_permission.py` 相关端点） | **保留** `member_count`（PRD 未要求移除；保持现状）。⚠️ **已被 F038 推翻**：5 万部门实测该统计的大 `.in_()` 计数在达梦约 66s（占该接口 ~96%），F038 移除之（提交 `b8e481872`） |

### 2.6 前端无限滚动行为

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-17 | 用户 | 平台「知识库」「应用」、工作台「知识空间文件列表」 | 列表底部不再有页码组件；滚动到末端 ≤ 200px 时自动触发下一页，前端用 `useInfiniteQuery` + `pageParam=next_cursor`；加载中显示骨架/loading；`has_more=false` 后不再触发 |
| AC-18 | 用户 | 列表为空 | 显示空态占位（与改造前一致）；不再展示「总数 0」 |

---

## 3. 边界情况

- **cursor 解析失败**（base64 解码错、json 缺字段、`v` 不支持、排序键个数与接口不符）→ 后端直接抛 `*InvalidCursorError`，HTTP 200 body 含错误码；前端收到此错误码时应整体 reset 列表（回首页），并提示「列表参数已变化，请刷新」。
- **多取 1 条试探**在「凑够 page_size 前已扫光 DB」时 → 返回 `has_more=false`、`data` 长度 < `page_size`、`next_cursor=null`；不报错。
- **OpenFGA 不可用** → 端到端返回 `RebacUnavailableError`（沿用现有），不写半页数据；前端不把这种半失败错认为 `has_more=false`，应保留当前 cursor 并允许用户重试。
- **切换租户上下文**（多租户场景）→ 仍由 SQLAlchemy 事件自动注入 `tenant_id`，本特性不动该链路；切租户后 react-query 因 `queryKey` 含租户上下文自动 reset。
- **排序键 tie-break**：业务排序字段（如 `update_time`、`file_name`）必须接 `id` 做 tie-breaker 进入 cursor，防止同字段值时翻页跳跃/漏条。
- **不支持**：
  - 任意页跳转（`?page=50`）：cursor-based 无此概念；
  - 向前翻页（prev）：无限滚动 UI 无此交互；
  - cursor 跨排序复用：切排序时 cursor 自动失效（前端 queryKey 变化触发 reset，避免后端解析后翻到错位置）；
  - 工具列表分页化（PRD 未要求）。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 翻页协议根本路线 | A: 保留 offset 仅移除 total；B: cursor-based；C: OpenFGA 反向查 + DB JOIN | **B** | 与产品确认「无限滚动」诉求本质是 cursor；A 只优化第 1 页，翻深页仍 O(N×page×ReBAC)；C 需改 OpenFGA 模型且收益依赖权限稀疏度，落地复杂、风险高、本期不做 |
| AD-02 | cursor 编码 schema | A: `base64(json([值, id]))`；B: 同上 + `v` 版本号；C: B + `s` 上下文签名（排序字段语义、排序方向）；D: 不透明 hash + Redis 映射 | **C**（v + s + k 三段） | `v` 让未来换字段/换 hash 时旧 cursor 可识别并报错；`s` 把排序上下文（`sort_by` / `order_field+order_sort`）编进 cursor，防止前端 queryKey 漏含 `sort_by` 时跨排序复用 cursor 导致「k 长度对但字段语义错位」的隐式 bug；D 需服务端存储，超本期所需 |
| AD-03 | `has_more` 判定方式 | A: 多取 1 条试探；B: 单独 EXISTS 子查询；C: `len(data)==page_size` | **A** | 不增加额外查询；与 ReBAC 过滤天然兼容；后端在 `data` 截断前先判断 `len > page_size` 作为 `has_more` 信号 |
| AD-04 | Cursor 失效/篡改处理 | A: 返 400 错误码；B: 静默 fallback 首页；C: 返空页 + `has_more=false` | **A** | 明确报错让前端及时感知列表参数变化；避免「滚动加载结果再次看到首页」的诡异体验；前端收 cursor 错误码统一回首页 |
| AD-05 | `_scan_visible_child_items` cursor 化的实现位置 | A: Service 层；B: DAO 层 | **A** | per-batch 的 ReBAC 过滤在 Service 层，DAO 层不感知权限；保持 Service 集中维护可见性；DAO 仅新增「按 cursor 拉一批」的 `WHERE (排序键) > cursor LIMIT N` 方法 |
| AD-06 | `total` 字段移除策略 | A: 直接删；B: 保留返 -1/null | **A** | 字段保留会让前端类型/兼容代码继续残留；与 `member_count` 删字段保持一致 |
| AD-07 | 前端无限滚动技术选型 | A: react-query `useInfiniteQuery`；B: 自研滚动控制器；C: IntersectionObserver + 手写状态 | **A**（platform RQv3、client RQv5 均原生支持） | `useInfiniteQuery` 用 `pageParam = next_cursor`，`getNextPageParam` 取 `data.next_cursor`；过滤切换通过 `queryKey` 变化自动 reset；IntersectionObserver 仅作触底探测器 |
| AD-08 | `member_count` 移除范围 | A: 全部三处后端接口同时删；B: 仅 PRD 原文范围（`departments/tree`） | **B** | PRD 边界明确；剩余两处后续若做对应优化再扩展 |
| AD-09 | 工具列表处理方式 | A: 改成分页+无限滚动；B: 不动后端只清前端「共 X 个」文案 | **B** | 现有结构是「工具类型分组树」，分页化破坏 UX；PRD 截图把它并列只是因为「列表」语义近，没说要分页化 |
| AD-10 | 新增 `PageInfiniteCursorData[T]` envelope 是否登记为规范扩展 | A: 仅复用 `PageData[T]`；B: 显式登记为版本级响应规范扩展 | **B** | 现有 `PageData[T]` 自带 `total`，与 PRD「取消计数」语义矛盾；新建 `PageInfiniteCursorData[T]` 作为「ReBAC cursor 列表」专用 envelope，后续其他 ReBAC 列表接口改造时直接复用；本特性以版本级规范扩展形式登记，不替代 `PageData[T]` |
| AD-11 | cursor 是否签名/防篡改 | A: HMAC 签名；B: 明文 base64 | **B** | cursor 不携敏感信息，篡改顶多翻到错位置或解码失败抛 400，可接受；签名增加复杂度且需密钥分发，本期不必要 |
| AD-12 | cursor 编解码工具的代码位置 | A: 各 service 自行实现；B: 共享于 `common/cursor.py` | **B** | 4 个接口共用一套编解码逻辑（base64 + json + 版本号 + 上下文签名 + 排序键长度断言）；集中实现降低不一致风险，便于未来加签名/换格式 |
| AD-13 | DM8/MySQL keyset SQL 表达式形式 | A: 元组比较 `WHERE (a, b, id) > (a0, b0, id0)`（语法糖，需 dialect 支持）；B: 展开形式 `WHERE a > a0 OR (a=a0 AND b > b0) OR (a=a0 AND b=b0 AND id > id0)`（最低公约数） | **A，用 SQLAlchemy `tuple_()` 表达式生成**（T001 已验证 MySQL/DM/SQLite 三 dialect 编译通过） | SQLAlchemy 1.4+ `from sqlalchemy import tuple_` 可生成元组比较 SQL；DAO 层应把 keyset 表达式封装成单一 helper（`_build_keyset_where(sort_cols, cursor_values)`），Service 层无感，未来 fallback 不污染上层 |
| AD-14 | `knowledge_file` 表「文件扩展名优先级」(`ext_rank`) 物化方案 | A: 不物化，service / DAO 层运行时用 CASE WHEN 表达式作为 keyset 首列；B: 加 stored generated column `file_ext_rank` + 复合索引；C: MySQL/DM8 functional index | **A** | T002 探查发现 `KnowledgeFile.file_type` 列只存 0/1（文件夹/文件），用户看到的「pdf>docx>doc>...>html」排序是 `SpaceFileDao.order_field_text` 内部 15-WHEN `CASE` 表达式现场算出来的。方案 A 不动 schema，cursor key 编入 service 同步算出的 ext_rank 整数，DAO keyset SQL 用同一个 CASE WHEN 作为排序键首列。**性能代价**：CASE WHEN 无法命中索引、需逐行算；但 `knowledge_file` 查询天然带 `knowledge_id + file_level_path` 复合过滤（结果集多为单个文件夹 ≤ 200 条），CASE WHEN 在小集合上跑无瓶颈。方案 B 长期更稳但需 schema 变更 + 老数据回填，本期不做（可作为后续独立技术债务跟进）；方案 C 双库兼容性风险（DM8 functional index 支持有限）不取 |
| AD-15 | `/api/v1/knowledge` `sort_by=name` 的 cursor 实现 | A: name 排序也走真 keyset cursor（需要 Python 端复现 GBK 排序，不可行）；B: name 排序响应 shape 分流，前端按 sort_by 分支处理；C: name 排序响应 shape 统一为 `PageInfiniteCursorData`，cursor `k` 实际编码 `[page_num]`，后端内部仍走 offset；name 用「多取 1 条」探测 `has_more` 代替 total | **C** | T003 实测：`sort_by=name` 用 dialect-aware 的 `CASE WHEN name REGEXP '^[a-z]'`（中英文分组）+ `CONVERT(name USING gbk)` / `NLSSORT('SCHINESE_PINYIN_M')` 排序；Python 无法复现 GBK 拼音排序值，无法编入 cursor `k` 做 keyset 比较。方案 C 把对前端的 API shape 统一了（前端不需要按 sort_by 分流），代价是后端 service 内部分流：（1）sort_by ∈ (update_time, create_time) → 真 keyset cursor；（2）sort_by = name → 内部 offset + 多取 1 条探测，cursor `k=[page_num]`，对前端是不透明 base64 串。`has_more` 由「`limit + 1` 取多 1 条」探测，不调 `acount_user_knowledge`，与 AC-11 一致 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

**无新增表、无新增列、无 Alembic migration**。本特性仅修改服务层、响应 schema 与错误码。

### 5.1 通用 Cursor 响应（新 envelope）

新增 `PageInfiniteCursorData[T]`，沿用现有 envelope 风格但语义为 cursor-based：

```python
# src/backend/bisheng/common/schemas/api.py
from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class PageInfiniteCursorData(BaseModel, Generic[T]):
    """Pagination envelope for cursor-based infinite-scroll lists.

    `next_cursor` is None when `has_more` is False.
    Frontend uses `next_cursor` as the next page's `cursor` query parameter.
    """
    data: List[T]
    page_size: int
    has_more: bool
    next_cursor: Optional[str] = None
```

> 不复用 `PageData[T]`（带 `total` 字段），避免类型层面的二义性；旧 `PageData` 仍保留供其他模块使用。

### 5.2 Cursor 编解码工具

新增 `common/cursor.py`：

```python
# src/backend/bisheng/common/cursor.py
import base64
import json
from typing import Optional, Sequence

CURSOR_SCHEMA_VERSION = 1


class CursorDecodeError(ValueError):
    """Raised when cursor cannot be decoded; should be caught by API layer
    and translated into module-specific InvalidCursorError."""


def encode_cursor(sort_key: Sequence, *, context: str) -> str:
    """Encode a sort-key tuple (含 tie-breaker id) + 排序上下文签名 为 base64url 字符串。

    context 应包含当前请求的排序语义，例如：
      - "knowledge|sort_by=update_time"
      - "flow|sort=update_time"
      - "space_children|order=file_type_asc,file_name_asc"
    解码时若 context 不匹配，抛 CursorDecodeError → 前端收到 InvalidCursorError 并回首页。
    """
    payload = {"v": CURSOR_SCHEMA_VERSION, "s": context, "k": list(sort_key)}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(
    cursor: Optional[str],
    *,
    expected_key_len: int,
    expected_context: str,
) -> Optional[list]:
    """Decode cursor 字符串为 sort-key 列表；None / "" 表示首页。

    Raises CursorDecodeError on any of:
      - base64 / json 解析失败
      - `v` 字段不匹配当前 schema 版本
      - `s` 字段不匹配 expected_context（前端跨排序复用 cursor 时触发）
      - `k` 长度与 expected_key_len 不一致
    """
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + pad))
        if payload.get("v") != CURSOR_SCHEMA_VERSION:
            raise CursorDecodeError(f"unsupported cursor version: {payload.get('v')}")
        if payload.get("s") != expected_context:
            raise CursorDecodeError(
                f"cursor context mismatch: got {payload.get('s')!r} expect {expected_context!r}"
            )
        key = payload.get("k")
        if not isinstance(key, list) or len(key) != expected_key_len:
            raise CursorDecodeError("cursor key length mismatch")
        return key
    except CursorDecodeError:
        raise
    except Exception as exc:
        raise CursorDecodeError(f"cursor decode failed: {exc}") from exc
```

### 5.3 部门 Schema 变更

```python
# src/backend/bisheng/department/domain/schemas/department_schema.py
class DepartmentTreeNode(BaseModel):  # 现有类型
    id: int
    dept_id: str
    name: str
    parent_id: Optional[int]
    path: str
    sort_order: int
    source: Optional[str]
    status: Optional[str]
    # member_count: int = 0   ← 删除此字段
    children: List["DepartmentTreeNode"] = []
```

> 单个部门详情 schema 继续保留 `member_count`（AD-08 / AC-15 已划定）。

---

## 6. API 契约

### 6.1 端点改动汇总

> 认证：`UserPayload = Depends(UserPayload.get_login_user)`（不变）
> 响应包装：`resp_200(data=PageInfiniteCursorData[T](...))`

| Method | Path | 改动 | 关联 AC |
|--------|------|------|--------|
| GET | `/api/v1/knowledge` | 请求参数 `page_num` 删除，新增 `cursor: Optional[str]`；响应改 `PageInfiniteCursorData[KnowledgeRead]`；移除 `acount_user_knowledge` 调用 | AC-01, AC-04~06, AC-11 |
| GET | `/api/v1/workflow/list` | 同上；`FlowDao.aget_all_apps` 改为「按 cursor 拉一批 + 多取 1 条试探」；移除 `count_statement` | AC-02, AC-04~06, AC-11 |
| GET | `/api/v1/tool` | **不改** | AC-12（前端范围） |
| GET | `/api/v1/knowledge/space/{id}/children` | 请求参数 `page` 删除，新增 `cursor: Optional[str]`；响应改 `PageInfiniteCursorData[...]`；`_scan_visible_child_items` 重构为 cursor + 「凑够即停」 | AC-03, AC-04~06, AC-10 |
| GET | `/api/v1/departments/tree` | 响应每个节点不再含 `member_count`；删除 `GROUP BY COUNT(*)` 查询块 | AC-13 |

### 6.2 各接口排序键 + cursor 上下文签名

| 接口 | 排序键（含 tie-breaker） | cursor `s` (上下文签名) | cursor `k` 示例 |
|------|--------------------------|-------------------------|-----------------|
| `/api/v1/knowledge` `sort_by=update_time` / `create_time` | `(<sort_by> DESC, id DESC)` | `"knowledge\|sort_by=update_time"` / `"knowledge\|sort_by=create_time"` | `["2026-05-28T12:34:56", 42]` |
| `/api/v1/knowledge` `sort_by=name` | 沿用现有 dialect-aware 排序（CASE WHEN 中英分组 + GBK/NLSSORT 拼音）；**不走 keyset，内部 offset**（AD-15） | `"knowledge\|sort_by=name"` | `[3]` —— `k[0]` 是下一页的 `page_num` 整数 |
| `/api/v1/workflow/list` | `(update_time DESC, id DESC)` | `"flow\|sort=update_time"` | `["2026-05-28T12:34:56", 12345]` |
| `/api/v1/knowledge/space/{id}/children` | **混合方向 4-tuple**：`(file_type ASC|DESC, ext_rank ASC|DESC, update_time DESC, id DESC)`。`order_sort` 参数影响前 2 列的方向；`update_time` 和 `id` 始终 DESC（沿用 `order_field_text` 既有行为）。**ext_rank** 是 15-WHEN `CASE` 表达式的输出整数（pdf=1, docx=2, doc=3, xlsx=4, xls=5, csv=6, pptx=7, ppt=8, jpg=9, jpeg=10, png=11, bmp=12, md=13, txt=14, html=15；文件夹/未识别扩展名 → ELSE 999）。WHERE 复合过滤 `knowledge_id == ? AND file_level_path == <exact_path>`（T002 实测；表无 `space_id` / `parent_id` 列）。因为方向混合（前 2 ASC，后 2 DESC 或反之），keyset 必须用 `build_keyset_where` 的展开形式（AD-13 fallback path，per-column direction） | `"space_children\|order=file_type_asc,ext_rank_asc,update_time_desc"`（随 `order_sort` 变化） | `[0, 1, "2026-05-29T12:34:56", 9876]` |

> 用户切 `sort_by` 时：(1) 前端 react-query `queryKey` 包含 `sort_by` 变化自动 reset cursor 到首页（AC-09，前端契约层）；(2) 万一前端 bug 漏了，后端解码 cursor 时 `s` 不匹配新请求的上下文 → 抛 `*InvalidCursorError`（AC-08，后端兜底）。两层防护。
>
> **`ext_rank` 运行时计算**（AD-14）：service 层和 DAO 层共用同一个 `_compute_ext_rank_case_when()` SQLAlchemy 表达式工厂；cursor encode 时 service 在 Python 端用同名 `_compute_ext_rank_python(file_name)` 函数算出整数存入 cursor，DAO 在 SQL 端用 `_compute_ext_rank_case_when()` 作为 keyset SQL 的首列。两者输出值必须严格一致（T013 单测有断言）。

### 6.3 请求/响应示例

**首次请求**:
```
GET /api/v1/knowledge?permission_id=view_kb&page_size=20&type=0

200 OK
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [ { "id": 1, "name": "...", ... }, ... ],
    "page_size": 20,
    "has_more": true,
    "next_cursor": "eyJ2IjoxLCJzIjoia25vd2xlZGdlfHNvcnRfYnk9dXBkYXRlX3RpbWUiLCJrIjpbIjIwMjYtMDUtMjhUMTI6MzQ6NTYiLDQyXX0"
  }
}
```

**续翻**:
```
GET /api/v1/knowledge?permission_id=view_kb&page_size=20&type=0
    &cursor=eyJ2IjoxLCJzIjoia25vd2xlZGdlfHNvcnRfYnk9dXBkYXRlX3RpbWUiLCJrIjpbIjIwMjYtMDUtMjhUMTI6MzQ6NTYiLDQyXX0

200 OK
{
  "data": { "data": [...], "page_size": 20, "has_more": false, "next_cursor": null }
}
```

**Cursor 非法**:
```
GET /api/v1/knowledge?cursor=garbage

200 (body)
{
  "status_code": 10991,
  "status_message": "Invalid pagination cursor",
  "data": null
}
```

> 改造前结构是 `{"data": [...], "total": 137}`。`total` 字段不再出现（任何接口）。

### 6.4 错误码

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | **10991** | `KnowledgeInvalidCursorError`（新增，置于 `common/errcode/knowledge.py`） | knowledge 列表 cursor 解码失败 | AC-08 |
| 200 (body) | **10550** | `AppInvalidCursorError`（新增，置于 `common/errcode/flow.py`） | workflow/app 列表 cursor 解码失败 | AC-08 |
| 200 (body) | **18070** | `KnowledgeSpaceInvalidCursorError`（新增，置于 `common/errcode/knowledge_space.py`） | knowledge space children cursor 解码失败 | AC-08 |
| 200 (body) | 10903 | `KnowledgeViewKbDeniedError` | 无 `view_kb` 权限的知识库被过滤掉（沿用） | 边界 §3 |
| 200 (body) | 10501 | `AppUseAppDeniedError` | 无 `use_app` 权限的应用被过滤掉（沿用） | 边界 §3 |
| 200 (body) | 10010 | `RebacUnavailableError` | OpenFGA 不可用（沿用兜底） | 边界 §3 |

---

## 7. Service 层逻辑

### 7.1 `KnowledgeService.get_knowledge`
**位置**: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:211-270`

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `get_knowledge` | `user, cursor, page_size, name, type, sort_by, permission_id, preferred_ids` | `PageInfiniteCursorData[KnowledgeRead]` | 1) `context = f"knowledge\|sort_by={sort_by or 'update_time'}"`（T003 实测：endpoint Literal 校验保证 sort_by ∈ {update_time, create_time, name}，默认 update_time）；2) **按 sort_by 分流**（AD-15）：<br>　**(a) sort_by ∈ (update_time, create_time)** —— 真 keyset cursor：`decode_cursor(cursor, expected_key_len=2, expected_context=context)` 拿 `[sort_value, id]` 或 None；DAO 用 `WHERE (sort_field, id) > cursor LIMIT page_size+1`；`next_cursor = encode_cursor((last.sort_value, last.id), context=context)`；<br>　**(b) sort_by = name** —— 伪 cursor（内部 offset）：`decode_cursor(cursor, expected_key_len=1, expected_context=context)` 拿 `[page_num]` 或 None（None→1）；DAO 用 `OFFSET (page_num-1)*page_size LIMIT page_size+1`，排序沿用现有 `name_sort_clauses`；`next_cursor = encode_cursor((page_num+1,), context=context)`；<br>3) 两路都按「多取 1 条」探测：`has_more = len(raw) > page_size`，截断到 `page_size`；4) **删除** `acount_user_knowledge` 调用（两路都不再算 total）；5) ReBAC 过滤链路不变 |

### 7.2 `WorkFlowService.get_all_flows`
**位置**: `src/backend/bisheng/api/services/workflow.py:153-232`

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `get_all_flows` | `user, cursor, page_size, name, tag_id, flow_type, status, managed, permission_id` | `PageInfiniteCursorData[FlowRead]` | 1) `decode_cursor(cursor, expected_key_len=2, expected_context="flow\|sort=update_time")` → `[update_time, id]` or None；2) ReBAC 拿可见 app id；3) `FlowDao.aget_all_apps` 改为 cursor-driven，返 `(data, has_more)`；4) **删除** `count_statement` 执行 |

`FlowDao.aget_all_apps`（`src/backend/bisheng/database/models/flow.py:526-605`）签名变化：
```python
# 改造前
async def aget_all_apps(..., page: int, page_size: int, ...) -> Tuple[List[Flow], int]:  # (data, total)
# 改造后
async def aget_all_apps(..., cursor: Optional[List], page_size: int, ...) -> Tuple[List[Flow], bool]:  # (data, has_more)
```

实现要点：`limit(page_size + 1)` + `WHERE (update_time, id) < cursor` 实现 keyset；本批 `len > page_size` → 截断 + `has_more=True`。

### 7.3 `KnowledgeSpaceService.list_space_children`（**ReBAC 优化关键**）
**位置**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:2293-2339`

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `list_space_children` | `space_id, parent_id, file_ids, order_field, order_sort, file_status, file_type, cursor, page_size` | `PageInfiniteCursorData[SpaceFileRead]` | 1) 构造 `context = f"space_children\|order=ext_rank_{order_sort.lower()},file_name_{order_sort.lower()}"`（注：cursor 首列语义是 ext_rank，对应 spec §6.2）；2) `decode_cursor(cursor, expected_key_len=3, expected_context=context)` → `[ext_rank, file_name, id]` or None；3) 校验空间/父目录可读；4) 调用重构后的 `_scan_visible_child_items`；5) 对返回的最后一条 visible item，调 `_compute_ext_rank_python(item.file_name)` 算出 ext_rank，`encode_cursor((ext_rank, item.file_name, item.id), context=context)` 编码 `next_cursor`；6) 返响应 |

`_scan_visible_child_items` 重构要点：
- **DAO 改造**：`SpaceFileDao.async_list_children` 新增 `cursor: Optional[List]` 参数（None 表示首页）；删除 `page` 参数。
  - 用 `_compute_ext_rank_case_when()` 工厂方法生成 ext_rank SQLAlchemy `Case` 表达式（与现有 `order_field_text` 内部 15-WHEN 严格一致）；
  - `keyset_where = _build_keyset_where(sort_cols=(ext_rank_case_expr, KnowledgeFile.file_name, KnowledgeFile.id), cursor_values=cursor)`；
  - `WHERE knowledge_id == ? AND file_level_path == <exact_path> AND <keyset_where> LIMIT BATCH_SIZE`；
  - **注意**：`knowledge_id + file_level_path` 复合过滤先把结果集砍到单文件夹（通常 ≤ 200 条），ext_rank CASE WHEN 在小集合上不构成瓶颈（AD-14）。
- **Service `_compute_ext_rank_python(file_name) -> int`** 工具函数（新建，置于 `knowledge_space_service.py` 或 `SpaceFileDao` 同模块）：
  - Python 端用 `file_name.lower().endswith()` 跑同样的 15-WHEN 顺序匹配；
  - 文件夹（`file_type == 0`）按现有 `order_field_text` 行为映射 ext_rank（具体值见 T013 实现，需与 DAO `Case` 严格对齐）；
  - 该函数仅用于 cursor encode 时算 ext_rank；DAO 端的 SQL 端不用它，用 `Case` 表达式。
  - **单测必须断言**：对一组样本文件名（覆盖 15 个扩展名 + 边界 case），`_compute_ext_rank_python()` 与 `_compute_ext_rank_case_when()` 在 SQLite 上 select 出的整数值**严格相等**（T012 覆盖）。
- **Service 流程**：
  1. 解析 cursor 为 `[file_type, file_name, id]` 元组（首页时为 None）；
  2. `batch_cursor = cursor`；维护本地累计 `visible_page_items: List`；
  3. 循环：DAO 用 `batch_cursor` 拉 `BATCH_SIZE` 条 → ReBAC 过滤 → 追加到 `visible_page_items`；
  4. 每轮结束后 `batch_cursor = (本批最后一条 DB item 的排序键)`（**注意**：是 DB 拉出的最后一条，不是过滤后的最后一条，这样下一批不会重复或漏过）；
  5. 终止条件：`len(visible_page_items) > page_size` **或** 本批 DB 返回数 < `BATCH_SIZE`（DB 拉光）；
  6. `has_more = len(visible_page_items) > page_size`；截断到 `page_size`；
  7. `next_cursor` = `encode_cursor((_compute_ext_rank_python(last.file_name), last.file_name, last.id), context=context)` for last visible item in 截断后的列表。

### 7.4 `DepartmentService.aget_tree`
**位置**: `src/backend/bisheng/department/domain/services/department_service.py:415-503`

| 改动 | 详情 |
|------|------|
| 删除 `count_result` / `count_map` 局部变量 | 包括 lines 461-469 的 `GROUP BY COUNT(*)` 子句 |
| `nodes[dept_id]['member_count']` 整行删除 | 节点字典不再含此键 |
| 单部门 `aget_department` | **不改**（AD-08/AC-15） |

### 7.5 权限检查

不变。ReBAC 过滤仍走 `rebac_list_accessible('can_read', 'knowledge_library')` / `ApplicationPermissionService.get_app_permission_map_async` 等现有路径。本特性只**改翻页协议** + **降频**，不**降权**。

### 7.6 DAO 调用约定

- `KnowledgeDao.acount_user_knowledge` → 调用方移除；若全局 grep 确认无其他引用，作为 tasks 阶段清理项一并删除（避免孤儿）。
- `FlowDao.aget_all_apps` → 改为 cursor-driven `(data, has_more)`，所有调用方一并更新。
- `SpaceFileDao.async_list_children` → **已 grep 确认仅 `_scan_visible_child_items` 一处调用方**（2026-05-28 验证）；本次改 cursor + 多取 1 条试探 + 删除 `page=scan_page` 翻页参数；**无双签名兼容需求**。
- DAO 层新增 `_build_keyset_where(sort_cols, cursor_values)` helper（位置：`SpaceFileDao` 同文件或 `database/utils/keyset.py`），封装 AD-13 决策的 `tuple_()` 表达式生成；为 DM8 fallback 提供单点切换。
- 所有 cursor 编解码统一调 `common/cursor.py`，不在各 service 内联写 base64/json。

---

## 8. 前端设计

### 8.1 Platform 前端（管理后台）

> 路径：`src/frontend/platform/src/`
> 框架：Zustand + react-query **v3** + bs-ui

#### 8.1.1 知识库列表
- API 封装：`src/controllers/API/index.ts:241-250`
  - `getKnowledgeListApi(params)`：删除 `page_num`，新增 `cursor?: string`；返回类型从 `{data, total}` 改为 `{data, page_size, has_more, next_cursor}`
- 消费组件：`src/pages/KnowledgePage/`（确切组件 tasks 阶段定位）
  - 改用 `useInfiniteQuery`（RQv3 支持）：
    - `queryKey = ['knowledge-list', name, type, sort_by, permission_id]`（含所有过滤参数 → 切换时自动 reset）
    - `queryFn({ pageParam }) => getKnowledgeListApi({ cursor: pageParam, ... })`
    - `getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor : undefined`
  - 替换 `<PaginationBs>` 为 `IntersectionObserver` 触底加载
  - 处理 cursor 错误码 `10991`：触发列表 reset + toast 提示
  - 移除「共 X 条」文案

#### 8.1.2 应用/工作流列表
- API 封装：`src/controllers/API/flow.ts:180`
- 消费组件：`src/pages/BuildPage/skills/`（应用列表页，确切组件 tasks 阶段定位）
- 改造方式与 8.1.1 相同；cursor 错误码 `10550`

#### 8.1.3 工具列表
- API 封装：`src/controllers/API/tools.ts:24-39`（不动）
- 消费组件：`src/pages/BuildPage/tools/`（或同等）
  - 只检查 UI 上是否出现「共 X 个 / N 个工具」等文案；如有则移除
  - 列表结构、API 不变

#### 8.1.4 部门树（系统管理 + 部门知识空间）
- `src/types/api/department.ts:10, 33`：从 `Department` 类型移除 `member_count`
- `src/pages/SystemPage/components/Departments.tsx:235`：移除 `{t("bs:department.memberCount")}: {selectedDept.member_count}` 整行
- `src/pages/DepartmentPage/index.tsx:202`：同上
- 翻译键 `bs:department.memberCount`：保留（供单部门详情场景使用）

### 8.2 Client 前端（工作台）

> 路径：`src/frontend/client/src/`
> 路由基础路径：`/workspace`
> 框架：Recoil + react-query **v5** + shadcn

#### 8.2.1 知识空间文件列表
- API 封装：`src/api/knowledge.ts:1253-1290`
  - `getSpaceChildrenApi(params)`：删除 `page`，新增 `cursor?: string`；返回类型改为 `{data, page_size, has_more, next_cursor}`
- 消费组件：知识空间文件浏览页
  - 改用 `useInfiniteQuery`（RQv5）：
    - `queryKey = ['space-children', spaceId, parentId, file_type, file_status, order_field, order_sort]`
    - `pageParam = next_cursor`
  - 替换底部分页器为 `IntersectionObserver` 触底
  - 处理 cursor 错误码 `18070`：reset 列表 + toast
  - 移除「共 X 个文件」文案

### 8.3 i18n

- 不新增翻译键；
- 删除使用：`bs:department.memberCount` 在 `Departments.tsx` / `DepartmentPage/index.tsx` 的使用点；翻译文件键保留。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/common/cursor.py` | `encode_cursor(sort_key, *, context)` / `decode_cursor(cursor, *, expected_key_len, expected_context)` / `CursorDecodeError`；schema `{v, s, k}` 三段，v=1（AD-02, AD-12） |
| `src/backend/bisheng/database/utils/keyset.py`（或同 DAO 文件） | `_build_keyset_where(sort_cols, cursor_values)` helper：SQLAlchemy `tuple_()` 表达式 + DM8 fallback 切换点（AD-13） |
| `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f027_keyset_indexes.py`（**条件性新建**） | 若 §10 索引盘点发现缺索引，创建 alembic migration 补齐 `knowledge` / `flow` / `knowledge_file` 表的 keyset 排序索引 |
| `src/backend/bisheng/common/schemas/api.py`（新增 `PageInfiniteCursorData` 类） | cursor-based 列表响应 envelope（与 `PageData[T]` 并存） |
| `features/v2.6.0/027-rebac-list-perf-optim/spec.md` | 本文件 |
| `features/v2.6.0/027-rebac-list-perf-optim/tasks.md` | 任务清单（下一步） |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/common/errcode/knowledge.py` | 新增 `KnowledgeInvalidCursorError(10991)` |
| `src/backend/bisheng/common/errcode/flow.py` | 新增 `AppInvalidCursorError(10550)` |
| `src/backend/bisheng/common/errcode/knowledge_space.py` | 新增 `KnowledgeSpaceInvalidCursorError(18070)` |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge.py:333-375` | 请求参数 `page_num`→`cursor`；响应类型改 `PageInfiniteCursorData[KnowledgeRead]`；捕获 `CursorDecodeError`→`KnowledgeInvalidCursorError` |
| `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:211-270` | 删除 `acount_user_knowledge` 调用；用 cursor 拉取；多取 1 条试探 |
| `src/backend/bisheng/api/v1/workflow.py:331-350` | 同上风格（响应+错误码） |
| `src/backend/bisheng/api/services/workflow.py:153-232` | 适配 `FlowDao.aget_all_apps` 新签名（cursor + has_more） |
| `src/backend/bisheng/database/models/flow.py:526-605` | `aget_all_apps`：参数 `page/page_size`→`cursor/page_size`；改 `(data, has_more)`；删除 `count_statement` |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py:263-289` | 请求参数 `page`→`cursor`；响应类型改 `PageInfiniteCursorData`；捕获错误 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:2239-2339` | 重构 `_scan_visible_child_items` 为「cursor + 凑够即停」；删除 `total` 累计 |
| `src/backend/bisheng/knowledge/domain/repositories/...`（`SpaceFileDao.async_list_children`） | 新增 `cursor` 参数，用 keyset (`WHERE (file_type, file_name, id) > cursor`) |
| `src/backend/bisheng/department/domain/services/department_service.py:415-503` | 删除 lines 461-469 的 COUNT 子句和 `count_map`；节点字典不再写 `member_count` |
| `src/backend/bisheng/department/domain/schemas/department_schema.py:95` | 删除 `DepartmentTreeNode.member_count` |
| `src/frontend/platform/src/controllers/API/index.ts:241-250` | `getKnowledgeListApi` 参数/返回类型适配 |
| `src/frontend/platform/src/controllers/API/flow.ts:180` | `read_flows` 参数/返回类型适配 |
| `src/frontend/platform/src/pages/KnowledgePage/`（确切文件 tasks 阶段定位） | `useInfiniteQuery` + 触底加载；cursor 错误处理；移除分页器与「共 X」文案 |
| `src/frontend/platform/src/pages/BuildPage/skills/` | 同上 |
| `src/frontend/platform/src/pages/BuildPage/tools/` | 仅移除「共 X」文案 |
| `src/frontend/platform/src/types/api/department.ts:10, 33` | 移除 `member_count` 字段 |
| `src/frontend/platform/src/pages/SystemPage/components/Departments.tsx:235` | 移除「成员数」展示行 |
| `src/frontend/platform/src/pages/DepartmentPage/index.tsx:202` | 同上 |
| `src/frontend/client/src/api/knowledge.ts:1253-1290` | `getSpaceChildrenApi` 参数/返回类型适配 |
| `src/frontend/client/src/`（工作台知识空间文件列表组件，tasks 阶段定位） | `useInfiniteQuery` + cursor + 触底加载 |
| `features/v2.6.0/release-contract.md` | F027 已登记；INV-6 措辞同步为「cursor-based」（tasks 阶段一并改） |

### 测试（新建）

| 文件 | 说明 |
|------|------|
| `src/backend/test/common/test_cursor.py` | `encode_cursor` / `decode_cursor` 单测（AC-07/AC-08） |
| `src/backend/test/knowledge/test_knowledge_list_cursor.py` | 验证 AC-01、AC-04~06、AC-08、AC-11 |
| `src/backend/test/api/test_workflow_list_cursor.py` | 验证 AC-02、AC-08、AC-11 |
| `src/backend/test/knowledge/test_knowledge_space_children_cursor.py` | 验证 AC-03、AC-08、AC-10 |
| `src/backend/test/department/test_department_tree_no_member_count.py` | 验证 AC-13 |
| `src/frontend/platform/src/test/knowledgeListInfiniteScroll.test.tsx` | 验证 AC-17、AC-18 + cursor 错误 reset（AC-09） |
| `src/frontend/platform/src/test/departmentTreeNoMemberCount.test.tsx`（或更新 `departmentTreeCounts.test.tsx`） | 验证 AC-14 |
| `src/frontend/client/src/test/spaceFilesInfiniteScroll.test.tsx`（或同等） | 验证工作台 cursor + 无限滚动 |

---

## 10. 非功能要求

- **性能**：
  - **前置条件（强依赖任务，tasks 阶段第一步必须完成）**：cursor-based keyset 性能强依赖排序键有覆盖索引。T002 探查已确认三表均无 keyset 复合索引；本 feature 须在 alembic migration 中补齐以下两表的索引（`knowledge_file` 表按 AD-14 方案 A 不加复合索引——CASE WHEN 表达式天然无法命中索引；保留单文件夹 ≤ 200 条天然过滤即可）：
    - `knowledge` 表：`(update_time DESC, id DESC)`、`(create_time DESC, id DESC)`（**注**：AD-15 决定 sort_by=name 不走 keyset，内部仍 offset，因此**不需要** `(name, id)` 复合索引）；
    - `flow` 表：`(update_time DESC, id DESC)`；
    - `knowledge_file` 表：**不加 keyset 复合索引**（AD-14 方案 A 的代价；查询天然带 `knowledge_id + file_level_path` 过滤把结果集砍到单文件夹小范围，ext_rank CASE WHEN 在 ≤ 200 条上跑无瓶颈）。
    缺失则新建 alembic migration（命名形如 `v2_6_0_f027_keyset_indexes.py`）补齐，作为本 feature 的前置依赖任务；**`knowledge` / `flow` 索引缺失不得发布**。
  - 目标值（非硬性 AC）：
    - **`knowledge` / `flow` 列表翻深页不再线性退化**：第 50 页与第 1 页的后端开销同阶（O(`page_size / 可见率`)），不再是 O(N × page_size × ReBAC)；
    - **`knowledge_space/children` 单次请求 ReBAC 调用数显著下降**：由「拉够即停」机制保证；翻深页性能依赖单文件夹数据规模（≤ 200 条无瓶颈；> 1000 条单目录是已知边界，列为后续技术债务跟进 AD-14 方案 B）；
    - 首屏 P95 不退化；预期下降（去掉 COUNT 查询的 round-trip）；
    - 后端不引入新的 N+1 查询。
- **安全**：
  - ReBAC 过滤链路不变；可见性判定与改造前等价；
  - 多租户自动 `tenant_id` 注入不变；
  - 不新增对 `role_access` 的直接查询（不触发 arch-guard RULE-8）；
  - cursor 不携带敏感信息（仅含业务排序字段值和 id），即便明文 base64 泄露也无权限放大风险。
- **兼容性**：
  - **请求/响应结构破坏性变更**：请求 `page_num` / `page` 消失改为 `cursor`；响应 `total` / `member_count` 字段消失。由于前后端同版本发布、且无第三方公开 API 依赖，按破坏性变更直接发布；
  - `PageData[T]`（旧 envelope）保留供其他模块用，本次不动；
  - DM8/MySQL 双库兼容性：cursor-based keyset 用 SQLAlchemy `tuple_()` 表达式生成 `WHERE (col1, col2, id) > (...)`（AD-13）。**tasks 阶段开工首日必须在 DM8 实跑 smoke 测试**，确认 dialect 接受元组比较 SQL；若拒绝，DAO 层 `_build_keyset_where` helper fallback 到展开形式 `WHERE a > a0 OR (a=a0 AND b > b0) OR ...`，Service 层无感。
    - **Fallback 路径性能说明**：展开形式 SQL 复杂度上升（OR 子句嵌套），优化器对其执行计划的稳定性低于元组比较；翻深页性能预期为「优于改造前 OFFSET，但低于元组比较形态」。Fallback 触发即视为可生产，但 §10 性能目标值「与第 1 页同阶」可能不再完全成立；需在 tasks 阶段记录实测对比数据。
- **可观测性**：
  - 沿用 `RebacClient` 现有指标，不新增 metric；
  - 若发版后想量化降幅，可在 OpenFGA / Grafana 看板上直接对比改造前后调用速率与 P95。

---

## 相关文档

- 版本契约: [`../release-contract.md`](../release-contract.md)
- 架构文档: `docs/architecture/10-permission-rbac.md`
- PRD: 飞书 wiki [2.6 beta3 PRD](https://dataelem.feishu.cn/wiki/RLZ2wa8GTiXC7FknbfGcaODPnPd) §6、§7
- 依赖 Feature: F004 ReBAC core、F008 resource-rebac-adaptation
