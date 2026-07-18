# 列表 Cursor 翻页与无限滚动 (F027)

BiSheng 高频列表(知识库 / 应用 / 知识空间文件)统一从 `page_num + COUNT(*)` 偏移翻页改造为 **cursor (keyset) 翻页 + 前端无限滚动**。改造的核心驱动力不是 UI 体验,而是**根治翻深页时 OpenFGA 细权限请求量随页号线性增长**:OFFSET 模式下,翻第 50 页要为前 49 页全部资源跑一次 ReBAC 过滤;cursor 模式下,每次只对当前 keyset 窗口跑一次。本文档描述这套模式的协议、后端实现套路、前端模式、以及 DM8 兼容上的关键坑。

---

## 1. 总览

```
┌──────────────────────────────────────────────────────────────────┐
│  前端                                                              │
│  ┌──────────────┐  ┌───────────────────────┐                     │
│  │ useInfinite-  │  │ LoadMore sentinel     │                     │
│  │ CursorTable   │  │ (IntersectionObserver)│                     │
│  └──────┬───────┘  └───────────┬───────────┘                     │
│         │  cursor=next_cursor   │  滚到底自动触发                   │
│         ▼                       ▼                                 │
│         GET /api/v1/<list>?cursor=<token>&page_size=20            │
└──────────────────────────┬────────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  后端 Service                                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ decode_cursor(token, expected_context, expected_key_len)   │  │
│  │   失败 → 抛业务错误码 (10550 / 10991 / 18070)               │  │
│  └────────────────────────┬───────────────────────────────────┘  │
│                           ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ fetch-until-enough scan loop (若细权限过滤可能减少)         │  │
│  │   每轮:  DAO.aget_xxx(cursor=batch_cursor, limit=batch)    │  │
│  │   过滤:  ApplicationPermissionService.get_app_permission   │  │
│  │   累积:  到 page_size + 1 (探 has_more) 或 DB 拉空        │  │
│  │   推进:  batch_cursor = last DB row (非 last visible)      │  │
│  └────────────────────────┬───────────────────────────────────┘  │
│                           ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ encode_cursor((sort_key_tuple), context) → next_cursor      │  │
│  └────────────────────────┬───────────────────────────────────┘  │
└──────────────────────────┬────────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  DAO + DB (MySQL / DM8)                                           │
│  SELECT ... WHERE <keyset predicate>                              │
│         ORDER BY <sort_cols> LIMIT <batch+1>                      │
│  注: DM8 不支持 row-value tuple 比较,统一走展开 OR ladder         │
└──────────────────────────────────────────────────────────────────┘
```

**改造范围**:

| 接口 | 改造内容 |
|------|---------|
| `GET /api/v1/knowledge` | OFFSET → cursor;砍 COUNT;`sort_by=name` 用复合索引 `(name, id)` |
| `GET /api/v1/workflow/list` | OFFSET → cursor;砍 COUNT;workflow + assistant UNION;**fetch-until-enough 循环** |
| `GET /api/v1/knowledge/space/{id}/children` | OFFSET → cursor;**scan loop 凑够即停**;ext_rank 用 CASE WHEN |
| `GET /api/v1/departments/tree` | 删 `member_count` 字段及对应 `COUNT(*) GROUP BY` |
| `GET /api/v1/tool` | 后端不动,只清前端「共 X 个」文案 |

---

## 2. 协议层:cursor envelope

所有 cursor 接口返回统一 envelope:

```python
# common/schemas/api.py
class PageInfiniteCursorData(BaseModel, Generic[T]):
    data: List[T]
    page_size: int
    has_more: bool
    next_cursor: Optional[str]
```

**与旧 `PageData[T]` 的区别**:无 `total` 字段(砍 COUNT 是性能优化的核心),用 `has_more` 替代「是否最后一页」。`next_cursor` 为 None 时表示已到末页,前端 LoadMore sentinel 应停止触发。

请求侧约定:`cursor` 是 query 参数,空值或省略 = 第一页;`page_size` 用户可控,典型 20。

### 2.1 Cursor token 编解码

`common/cursor.py`:

```python
def encode_cursor(values: Sequence, *, context: str) -> str
def decode_cursor(token: str, *, expected_key_len: int, expected_context: str) -> List
```

token 结构(简化):`base64(json({"c": context, "v": [...sort_key_values]}))`。`context` 字符串是「这个 cursor 是哪个查询发的」的标签(例如 `"flow|sort=update_time"`、`"knowledge_space_children|sort=file_type_asc"`),用来防御「用户拿 A 接口的 cursor 喂 B 接口」。

`decode_cursor` 失败(token 篡改 / context 不匹配 / key 长度对不上)抛 `CursorDecodeError`,Service 层翻译成业务错误码:

| 错误码 | 模块 | 含义 |
|--------|------|------|
| `10550` | flow (105) | `AppInvalidCursorError` — workflow/app 列表 cursor 解码失败 |
| `10991` | knowledge (109) | `KnowledgeInvalidCursorError` — 知识库列表 cursor 解码失败 |
| `18070` | knowledge_space (180) | `KnowledgeSpaceInvalidCursorError` — 空间文件列表 cursor 解码失败 |

前端拿到这些错误码后必须 `reset cursor=null` 重新从第一页拉。

---

## 3. Keyset WHERE 子句:DM8 兼容的展开式

`database/utils/keyset.py` 的 `build_keyset_where()` 是所有 cursor DAO 的统一 WHERE 子句生成器。SQL-92 标准是 **row-value tuple 比较**:

```sql
WHERE (update_time, id) < (?, ?)
```

MySQL / Postgres / SQLite 都支持。但 **DM8 v8 不支持**(`[CODE:-2007] line N, column M, nearby [?] has error: Syntax error`),即使 T001 的 dialect-stub smoke test 用 `DefaultDialect` 编译能过。

→ **`_USE_EXPANDED_FALLBACK = True` 必须始终开启**。helper 自动展开成 OR ladder:

```sql
WHERE
    update_time > ?
  OR (update_time = ? AND id > ?)
```

语义等价,索引使用一样(复合索引 `(update_time, id)` 同样能 seek)。修改这个开关前必须在真实 DM8 环境验证。

### 3.1 混合方向 ASC/DESC

space_children 的 keyset 是 `file_type ASC, ext_rank ASC, update_time DESC, id DESC` — 混合方向用 tuple 表达不了,必须用展开 OR。helper 接受 `descending: Sequence[bool]` 参数,自动按列方向生成 `>` 或 `<`:

```python
build_keyset_where(
    sort_cols=(t.c.file_type, t.c.update_time, t.c.id),
    cursor_values=(0, dt0, 100),
    descending=(False, True, True),
)
```

### 3.2 CASE 表达式作 sort_col

`knowledge_file` 的 `ext_rank`(扩展名优先级:pdf=1 / docx=2 / ...)是 15-WHEN CASE 表达式。helper 接受任意 `ColumnElement` 包括 `case()`,所以 cursor 排序键可以是计算值;**注意:Python 侧需要有对应的 `_compute_ext_rank_python()` 函数**,用来在收到 DAO 一批数据后给最后一行算 `ext_rank` 推进 `batch_cursor`。这个「双函数对」(SQL CASE + Python 等价 fn)的一致性必须维护,Python 侧错位会导致下一批漏行或重复。

---

## 4. Fetch-until-enough scan loop

OFFSET 翻页时代,「细权限把当前页过滤剩 7 条」的「页缺数」问题不存在(下一页是第 N+1 行起步)。但 cursor 模式下,如果 service 在 DAO 之后做 ReBAC 细过滤,page_size=20 拉来可能剩 7 条,直接返给前端就是「列表突然短」。

**解决套路**:在 service 层加循环,DAO 拉一批 → 过滤 → 累积到 `page_size + 1` 探到 has_more 或 DB 拉空才返。两个地方用了:

| 接口 | 实现 | batch_size 常量 |
|------|------|-----------------|
| `workflow/list` | `WorkFlowService._scan_visible_flows_cursor` | `_FLOW_PERMISSION_SCAN_BATCH_SIZE = 50` |
| `knowledge_space/children` | `KnowledgeSpaceService._scan_visible_child_items` | `_CHILD_PERMISSION_SCAN_BATCH_SIZE = 100` |

骨架(伪代码):

```python
visible: List[Dict] = []
batch_cursor = decoded_cursor  # 从前端 cursor 解出来,或 None 表示第一页

while True:
    batch, db_has_more = await DAO.fetch(cursor=batch_cursor, limit=BATCH_SIZE)
    if not batch:
        return visible[:page_size], False

    kept = filter_by_fine_grained_permission(batch)
    for item in kept:
        visible.append(item)
        if len(visible) > page_size:
            return visible[:page_size], True   # has_more=True

    if not db_has_more:
        return visible[:page_size], False

    # 关键: cursor 推进用 last DB row,不是 last visible
    batch_cursor = encode_sort_key_from(batch[-1])
```

**最容易写错的一行**:`batch_cursor = batch[-1]` 必须用 DAO 返回的最后一行,**不能用过滤后的最后一行**。如果用 last visible,被过滤掉的中间行会在下一批被 DAO 重新返出来(因为 keyset 的「严格大于」边界没跨过它们),最终重复出现在累积 visible 里。

### 4.1 不同接口的过滤位置差异

三条 cursor 线的 OpenFGA 过滤策略不同:

| 接口 | 过滤位置 | 是否需要 scan loop |
|------|---------|---------------------|
| `knowledge` | **DB 之前**:`PermissionService.list_accessible_ids()` 一次拉出可见 id 集,作为 DAO `WHERE id IN (...)` 条件 | 否,DB 拉多少 = 返多少 |
| `workflow/list` | **DB 前粗筛 + DB 后细筛**:粗筛只看类型维度(view_app/edit_app),DAO 后对结果再跑 `get_app_permission_map_async` | 是,因为细筛可能缩水 |
| `knowledge_space/children` | **DB 后逐批过滤**:`_build_child_permission_context` + per-item check | 是,且过滤率可能 > 50% |

knowledge 走「先算清楚再查」,代价是首次进来要并发跑全集 ReBAC,但走 Redis 缓存基本毫秒级。workflow / space_children 走「先查再过滤」,所以必须 fetch-until-enough。

---

## 5. 前端模式

### 5.1 Platform (`src/frontend/platform/`)

复用 hook `src/frontend/platform/src/util/hook.ts → useInfiniteCursorTable`:

```typescript
const { data, hasMore, loading, reload, loadMore } = useInfiniteCursorTable({
    queryFn: ({ cursor }) => getKnowledgeList({ cursor, page_size: 20, ...filters }),
    deps: [searchText, sortBy],  // 这些变化时自动 reload(reset cursor=null)
})
```

hook 内部维护 `nextCursor` / `accumulated data`;调用方只暴露 `data`、`hasMore`、`loadMore()`。

### 5.2 Client (`src/frontend/client/`)

Client 没有通用 hook(`useFileManager.ts` 是 SpaceDetail 专用)。`useFileManager` 把「page 1 替换、page>1 append」「默认路径用 nextCursor、搜索路径用 nextSearchPage 拼接」合在 `loadFiles(page)` 一个方法里,外部用 `onPageChange(currentPage + 1)` 触发下一批。

### 5.3 LoadMore sentinel

`src/frontend/platform/src/components/bs-comp/loadMore/index.tsx` 和 `src/frontend/client/src/pages/knowledge/SpaceDetail/LoadMore.tsx` 是同一模式的两个版本。核心实现:

```typescript
const sentinelRef = useRef<HTMLDivElement>(null)

useEffect(() => {
    const root = findScrollableAncestor(sentinelRef.current)
    //          ↑ 必须传 root,否则容器内滚动不触发
    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) onLoadRef.current?.()
    }, { root, threshold: 0.1 })
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
}, [])
```

**两个最坑的陷阱**:

1. **IntersectionObserver `root: null` 默认走 viewport**。BiSheng 大部分列表是「列表区在固定高度容器里 overflow:scroll」,容器内滚动不改变 sentinel 跟 viewport 的关系 → observer 只在 mount 时触发一次,之后永远不再触发。必须用 `findScrollableAncestor()` 走 DOM 找最近 `overflow-y: auto / scroll / overlay` 祖先作 root。
2. **`onLoad` 闭包冻结 stale `nextCursor`**。observer 是 mount 时创建的(`[]` deps),callback 里用的 `onLoad` 是首次渲染时的版本。必须用 `useRef` 同步:`onLoadRef.current = onLoad` 每次 render 都更新,observer callback 调 `onLoadRef.current?.()` 拿最新版本。

不解决这两个,代码看起来对、第一页加载也对,然后下拉就再也不触发,且没报错。

### 5.4 短列表「mount 即触发」副作用

如果首屏数据不足以撑满 scroll container,sentinel mount 时就跟 viewport 相交 → 立刻触发一次 LoadMore。如果第二页数据还不满,继续触发 → 直到 `hasMore=false`。这是正确行为(数据够少就该一次全拉),但 UX 上「没滚就在加载」可能让用户疑惑。需要时可加 500ms mount 缓冲期。

### 5.5 5s 状态轮询不能动 cursor 链

`useFileManager` 在有「处理中文件」时每 5s 轮询刷状态。append 模式下,**不能再用 `loadFiles(currentPage)`** — 那会把累积 files 替换成最新一批,前面累积的尾部全丢,且 cursor 会前进。

正确做法(`refreshLoadedStatuses()`):
- 调一次 `cursor=null, page_size=files.length`,拿前 N 条最新数据
- 按 `id` merge:已加载行用回包覆盖 status / progress 字段;回包里有但本地没有(新上传)append 到头部;本地有但回包没有的不删
- `nextCursor / hasMore` **不动**

搜索状态下不轮询(搜索结果是「截图」,实时刷状态意义不大且接口语义不同)。

---

## 6. 关键陷阱速查

| 现象 | 根因 | 修法 |
|------|------|------|
| DM8 报 `[CODE:-2007] line N nearby [?] Syntax error`,SQL 含 `(col_a, col_b) < (?, ?)` | DM8 不支持 row-value tuple compare | `_USE_EXPANDED_FALLBACK = True`(已是默认) |
| Workflow/space_children 列表「页缺数」(每页返 7 条) | 细权限过滤后没补 | scan loop,batch_cursor 推进用 last DB row |
| LoadMore mount 后只触发一次,滚动再不触发 | IntersectionObserver `root: null` 默认 viewport,但 sentinel 在 overflow 容器里 | `findScrollableAncestor()` 找最近 scroll 祖先作 root |
| LoadMore 触发但 `onLoad` 用的是首次 render 的 cursor | `[]` deps 的 useEffect 闭包冻结了 onLoad | `useRef` 同步:`onLoadRef.current = onLoad` 每 render |
| Client SpaceDetail 跳到第 5 页拿到第 2 页数据 | `cursor: page > 1 ? nextCursor : null` 中 nextCursor 只是「下一页」的 cursor,跨页跳无中间历史 | 不允许跳页:UI 改成 LoadMore append 即可 |
| 5s 轮询把无限滚动列表「截短」回首页 | 轮询调 `loadFiles(currentPage)` 替换了累积数据 | 改成 `refreshLoadedStatuses()`,只 merge status,不动 cursor 链 |
| `int(last['id'])` 抛 ValueError | workflow/list UNION:flow id 是 int,assistant id 是 UUID 字符串 | `encode_cursor` 不强转类型,JSON 保留原类型 |
| `datetime is not JSON serializable` | `update_time` 是 datetime,cursor 编码崩 | `encode_cursor` 加 datetime → ISO 字符串 fallback |
| 部署 backend 镜像时拉不到 `dataelement/bisheng-backend:base.v8` | base image 在 docker.io 上 403,cr.dataelem.com 上没有 | 写 `Dockerfile.beta3`:`FROM cr.dataelem.com/dataelement/bisheng-backend:feat_2.6.0-beta2` + `COPY ./ ./` 增量构建 |

---

## 7. 关键文件路径

```
docs (本文档)        → docs/architecture/13-cursor-pagination.md
spec / tasks (本地)   → features/v2.6.0/027-rebac-list-perf-optim/{spec,tasks}.md  (features/ 在 gitignore)
release-contract     → features/v2.6.0/release-contract.md  (F027 entry + INV-6)

cursor 编解码         → src/backend/bisheng/common/cursor.py
keyset WHERE         → src/backend/bisheng/database/utils/keyset.py  (_USE_EXPANDED_FALLBACK = True)
envelope             → src/backend/bisheng/common/schemas/api.py     (PageInfiniteCursorData)
errcodes             → src/backend/bisheng/common/errcode/{knowledge,flow,knowledge_space}.py
                        10550 / 10991 / 18070

后端 cursor 实现
  - knowledge          → bisheng/knowledge/domain/services/knowledge_service.py
  - workflow           → bisheng/api/services/workflow.py
                          _scan_visible_flows_cursor  (fetch-until-enough)
                          get_all_flows_envelope
  - space_children     → bisheng/knowledge/domain/services/knowledge_space_service.py
                          _scan_visible_child_items   (fetch-until-enough)
                          list_space_children
                          _compute_ext_rank_python    (SQL CASE 的 Python 等价)
  - departments tree   → bisheng/department/domain/services/department_service.py
                          (member_count 已移除)

前端 platform
  - hook              → src/frontend/platform/src/util/hook.ts → useInfiniteCursorTable
  - LoadMore          → src/frontend/platform/src/components/bs-comp/loadMore/index.tsx
  - 入口              → pages/BuildPage/apps.tsx
                        pages/KnowledgePage/KnowledgeFile.tsx  (兼 /build/knowledge 和 ?type=1 QA 库)

前端 client
  - hook              → src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts
  - LoadMore          → src/frontend/client/src/pages/knowledge/SpaceDetail/LoadMore.tsx
  - 入口              → src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx

测试
  - cursor 编解码     → src/backend/test/common/test_cursor.py
  - keyset DAO        → src/backend/test/database/test_keyset.py
  - knowledge cursor → src/backend/test/knowledge/test_knowledge_list_cursor.py
  - workflow cursor  → src/backend/test/api/test_workflow_list_cursor.py
  - space children   → src/backend/test/knowledge/test_knowledge_space_children_cursor.py
  - 部门树           → src/backend/test/department/test_department_tree_no_member_count.py
  - client SpaceDetail → src/frontend/client/src/pages/knowledge/hooks/useFileManager.test.ts
```

---

## 8. 给「下一个改这块的人」的清单

要新加一个「列表 X」走 cursor + 无限滚动:

1. **DAO 层**:把现有 `query_xxx(page, page_size)` 改成 `query_xxx(cursor, limit)`,WHERE 加 `build_keyset_where(sort_cols, cursor)`(`cursor is None` 时跳过),`fetch_limit = limit + 1` 探 has_more。返 `(data, has_more)`,**不返 total**。
2. **Service 层**:加 `xxx_envelope()`:`decode_cursor → fetch-until-enough (如果有细权限过滤) → encode_cursor(last visible) → PageInfiniteCursorData`。
3. **Endpoint**:`cursor: Optional[str] = Query(None)` + `page_size: int = Query(20)`,return envelope。
4. **errcode**:在所属模块 `errcode/<module>.py` 加一个 `<XxxInvalidCursorError>`(5 位 MMMEE),context 字符串配套(例如 `"xxx|sort=update_time"`)。
5. **索引**:看是否需要新加复合索引 `(sort_col_1, ..., id)`,DM8 + MySQL 双方言验证(`alembic` migration 注意 `dialect_helpers`)。
6. **前端**:platform 用 `useInfiniteCursorTable` 一行接;client 仿照 `useFileManager.ts` 写 hook + `<LoadMore>` sentinel。
7. **测试**:单元测 envelope 路径(mock DAO 测 cursor 解码 / encode / has_more);单元 / 静态测覆盖 fetch-until-enough 循环存在。

实施前先读 spec(`features/v2.6.0/027-rebac-list-perf-optim/spec.md`)的 AD 节,里面是 F027 期间踩坑沉淀下来的 architectural decisions,包括为什么选 keyset(`update_time, id`)而不是其他 + 为什么 file_type 排序要用 ext_rank 复合 cursor 等。
