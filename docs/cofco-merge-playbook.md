# 中粮分支合并手册

> **这份文档只在 `feat/cofco-909-3.0.0-beta1` 上维护。** 每次合并完，把新踩到的坑和调整后的结论回写到这里。
>
> 用途:中粮定制线和主版本线并行开发,同一批 bug 常常两条线各修一遍,合并时**同一批文件反复冲突**。这里记录每处冲突「为什么必然冲突」和「按什么原则收」,下次直接照表处理,不用重新推理一遍。
>
> 最近一次全量合并:2026-09-07(2.8-common → 3.0.0-beta1 → 909 ← cofco-902)

---

## 1. 分支拓扑与合并方向

| 分支 | 性质 | 说明 |
|---|---|---|
| `feat/2.8-common` | **主版本** | 通用功能与 bug 修复的上游 |
| `feat/3.0.0-beta1` | **主版本** | 3.0 主线,含 f048 权限重写 |
| `feat/cofco-902` | **定制** | 中粮 2.6 线 |
| `feat/cofco-909-3.0.0-beta1` | **定制** | 中粮功能 + 3.0 底座,本文档所在分支 |

**铁律:定制功能不能回流主版本。** 合并方向只有两条:

```
feat/2.8-common  ──→  feat/3.0.0-beta1
feat/cofco-902   ──→  feat/cofco-909-3.0.0-beta1
```

`2.8-common → cofco-*` 或 `cofco-* → *-common` 都是错的。

---

## 2. 合并顺序(直接影响工作量)

909 = 中粮定制 + 3.0 底座。同一批 bug 在 2.8-common 和 cofco-902 上**各修了一遍**(2026-09-03 那轮 9 对同名提交里,5 对补丁完全相同,4 对因定制上下文而不同)。顺序错了,同一份移植工作要做两遍。

**正确顺序:**

```
① feat/2.8-common          →  feat/3.0.0-beta1     (主线内部对齐)
② feat/3.0.0-beta1         →  feat/cofco-909-…     (把已适配 f048 的修复带下来)
③ feat/cofco-902           →  feat/cofco-909-…     (只剩真正的定制差异)
```

**为什么 ② 要在 ③ 前面**:909 跑在 3.0 底座上。先合 3.0,那批共有修复是「已经移植到 f048 之后」的形态进来的;再合 902 时,它们已经在位,冲突只剩真正的定制差异。

> 实测(2026-09-03):按 ③②① 顺序试跑,902 那一轮有 **27 个冲突文件**;改成 ①②③ 后降到 **少数几个真冲突**,其余自动合并。

---

## 3. 必冲突清单

> 用法:合并中断后先 `git diff --name-only --diff-filter=U`,对照下表逐个处理。
> 表里「取 909」= `git checkout --ours -- <file>`;「取 902/主线」= `--theirs`。
> **注意**:`--ours/--theirs` 会整文件取一侧,只在「另一侧的改动整体不适用」时才这么用;否则要逐 hunk 处理。

### 3.1 后端 · 权限(f048 已删服务)

**症状**:`DU`(deleted by us, modified by them)冲突,一次 9 个文件:

```
bisheng/permission/domain/services/resource_authorization_service.py
bisheng/permission/domain/services/grant_subject_query_service.py
bisheng/channel/domain/services/channel_authorization_service.py
bisheng/channel/domain/services/channel_creation_application_service.py
bisheng/knowledge/domain/services/knowledge_space_creation_application_service.py
+ 对应的 5 个测试文件
```

**根因**:3.0 的 f048 权限重写(`edcbe81bc`)把这批服务整体删了,而 902 还在往里改。

**处理方式**:

1. **一律接受删除**(`git rm`),这些文件回不来。
2. **但不能只删** —— 要先看 902 在这些文件里改了什么**行为**,再把行为移植到 f048 的落点。
3. **它们的测试不要救** —— 直接吃已删服务的 API(`AuthorizationResult`、`AuthorizeGrantItem` 等),搬不动。需要覆盖就在 f048 落点重写。

**行为落点对照表**(持续补充):

| 902 的行为 | f048 落点 | 已移植 |
|---|---|---|
| 审批场景关闭时,个人授权降级为直接授权 | `PersonalGrantInviteGate.scenario_guard()` + `resource_api.mutate_grants` 里的 `AsyncExitStack` | ✅ 2026-09-03 |
| 全局超管跨部门选授权对象 | `permission/api/endpoints/grant_subjects.py` 的 `_authorized_scope`(`is_global_super` 时不做部门收窄) | ✅ 2026-09-03 |
| 写入时的部门空间校验(`_validate_department_space_grants`) | **909 没有这一层**,f048 把写时部门门禁整个去掉了,不需要移植 | — n/a |

> 降级那条要注意:场景守卫会给场景行**加锁**,必须在整个 mutation 期间持有(用 `AsyncExitStack`),否则可能出现「一部分发了邀请、另一部分直接写入」的半截状态。

### 3.2 后端 · 知识库文件夹 rollup

**文件**:`knowledge/domain/services/knowledge_space_service.py` 的 `_handle_file_folder_extra_info`

**根因**:两条线对同一个统计做了不同实现。

| | 中粮线(909) | 主线(3.0) |
|---|---|---|
| 统计方式 | 一次分块 UNION 统计整页文件夹 | 每个文件夹一条查询 |
| 额外逻辑 | 扣除「文件变更审批隐藏行」 | `has_abnormal_files`(存在异常,含 TIMEOUT)+ 按当前用户可见性过滤 |

**处理方式**:**保留 909 的 UNION 批量结构**,把主线新增的计数器挂到同一次聚合上(不要退回「每文件夹一条查询」);可见性判定仍按文件夹跑,但**只在聚合已经发现异常时**才跑。

**两个坑**:
- `abnormal` 与 `retryable` 是**重叠**关系不是互斥,累加时用独立的 `if`,不能接在 `elif` 链上。
- 被隐藏的 **TIMEOUT** 行没有自己的计数器,但也必须从 `abnormal` 里扣掉,否则文件夹会为一个谁都看不见的文件一直挂着「存在异常」。

> 2026-09-03 那轮:902 自己也独立做了同样的整合,行为一致、写法更干净,于是这几个 hunk 取了 902 的,并删掉了 909 这边重复的 `visible_abnormal_exists`(两个同名闭包,后定义的会静默遮蔽前一个)。

### 3.2b 后端 · 知识空间「设为私密 / 广场可见」路径

**文件**:`knowledge_space_service.py` 的 `update_knowledge_space` 开头

**根因**:主线 hotfix(`d53524e69`,广场可见性与权限解耦)删掉了 `old_square_visible` / `new_square_visible` 及其驱动的 `sync_public_reader`;909 在**同一位置**加了「部门绑定空间不允许转私密」的守卫。两边改同一段,必冲突。

**处理方式**:删掉 `old_square_visible`(它的消费者已经没了),**保留 909 的部门守卫**。

**别误删**:`sync_public_reader(..., enabled=False)` 那个调用**要留着** —— 主线也留着。hotfix 删的是**授予** public_reader 的路径,空间转私密时**清理**残留的那条是有意保留的。

### 3.3 后端 · 权限判定 seam

**症状**:`_can_manage_space_cached`、`_filter_visible_child_items` 尾部等处,902 调 `_user_can_manage_space(...)`,909 调 `_check_action(..., "manage_permission")`。

**处理方式**:**一律取 909 的 f048 seam**。`_user_can_manage_space` 走的是 f048 已删的 `PermissionService.check(relation=...)`。

配套:测试里 stub 的也要跟着换成 `svc._check_action`。

### 3.4 后端 · Excel 解析三件套

**文件**:`rag/pipeline/loader/excel.py`、`rag/pipeline/loader/utils/md_from_excel.py`、`rag/base_file_pipeline.py`

**根因**:两条线各自长出了内嵌图片提取;3.0 额外有超长行降级和 chunk 预算,主线额外有「图片按 sheet 顺序穿插」。

**处理方式**:**以 3.0 的 loader 为底**(功能更全),把主线的 sheet 排序搬上去。

**坑**:两条线的 markdown 分片**文件名格式不同** —— 3.0 是 `{sheet:03d}_{chunk:06d}.md`,主线是 `{sheet:02d}{i:03d}.md`。搬 sheet 排序时前缀匹配必须跟着改,否则**不报错**,只是所有图片静默掉到列表末尾(排序等于没做)。

### 3.5 前端 · 授权对象选择器

**文件**:`components/permission/` 下的 `PermissionListTab.tsx`、`SubjectSearchUser.tsx`、`SubjectSearchUserGroup.tsx`、`SubjectSearchDepartment.tsx`

**根因**:3.0 跑的是 f050 统一权限设置版,主线是 creation-mode 版,**结构不同**(API、props、内部状态都不一样)。

**处理方式**:**取 3.0/909 的**。主线在这几个文件上的改动基本是视觉重构(共用行间距、共享空状态组件),搬不过来也不影响功能。这个结论在 `972397fbe` 就定过一次,2026-09-03 再次确认。

### 3.6 前端 · 日常对话限流恢复(⚠️ 已知缺口)

**文件**:`hooks/useAiChat.ts`、`components/Chat/AiChatMessages.tsx`、`components/Chat/AiMessageBubble.tsx`

**根因**:909 跑的是 3.0 的 `useAiChat` —— 单会话、submission 驱动;902 的是多会话、自己开 live stream 存 map。两套实现。而且 3.0 的 `ChatView` 根本没接恢复入口。

**处理方式**:**取 909 的**。硬搬 902 的 `recoverRateLimitedMessage` 需要连带它的整套 stream store,而且搬过去也没人调。

**影响范围**:只影响**日常对话**的限流恢复。**任务模式不受影响** —— `ExecutionFlow` / `TaskTurnPanel` 能干净合并,换模型按钮照常;后端 `LinsightWorkbenchImpl.continue_conversation(model_id=...)` 也已落地。

**未决**:要不要在 3.0 的 hook 上重写日常对话的恢复流程。这是产品决定,不是合并能解决的。

**副作用检查**:取 909 后,902 那侧自动合并进来的辅助变量会变成孤儿(`handleSwitchModel`、`switchModelOptions`、`handleRecoveryModelChange` 等)。跑 lint 会报 unused —— **不要加 eslint-disable**,应该把整文件对齐 909 版本(`git checkout HEAD -- <file>`)。

### 3.7 前端 · 提示卡片组件

**文件**:`components/ServiceBusyNotice.tsx`、`components/ChatErrorCard.tsx`

**根因**:两条线在同几周里各加各的 —— 902 加限流态文案 + 换模型/稍后再试;3.0 加动画图标 + 新布局(操作按钮跟着描述末行或「查看详情」行走)。

**处理方式**:**props 取并集,渲染取 3.0 的布局**,把 902 的按钮放进 3.0 那个共享的 `actions` 元素里(用 `@bisheng/ui` 的 Button API,不要保留手写尺寸)。

**坑**:2026-09-03 这样合完出现了**两个 `const actions`**。`pnpm lint` 和 `tsc-strict` **都没抓到**,只有 `vite build` 报 `The symbol "actions" has already been declared`。见 §4。

### 3.8 前端 · 溯源抽屉

**文件**:`components/Chat/Messages/Content/CitationReferencesDrawer.tsx`

**处理方式**:
- 高度用 **909 的 `[height:var(--bs-dvh,100dvh)]`** —— 这是信创 webview 的修复,不能退回 `100dvh`。
- i18n key 用 **主线的 `com_message.source_*`** —— 两条线各自抽过一遍中文,主线那版还顺带把手写 chip 迁到了 `@bisheng/ui` 的 Tag。
- 主线没有的 key(如 `com_citation.no_download_url`,属 3.0 的下载功能)保留。

### 3.9 前端 · i18n locale 文件(⚠️ 会静默丢东西)

**文件**:`client/src/locales/{en,ja,zh-Hans}/translation.json`

**常规处理**:两边都是往同一位置加 key,**保留双方**(注意补逗号)。

**⚠️ 合并后必查:顶层命名空间重复。** 两条线可能各自新建了同名命名空间(2026-09-03 是 `com_message`,一个装限流文案、一个装溯源面板文案)。合并后文件里会出现**两个同名块**,JSON 只保留最后一个 —— **一半的 key 静默解析为空**,而且:

- 文件仍然是合法 JSON
- `pnpm check-i18n` 仍然通过
- 三种语言的 key 数量仍然对齐(因为三份都错得一样)

检查方法(会报出任意层级的重复键,不止顶层):

```bash
cd src/frontend/client && python3 -c "
import json, collections
for lang in ('en','ja','zh-Hans'):
    p=f'src/locales/{lang}/translation.json'
    dupes=[]
    json.loads(open(p,encoding='utf-8').read(), object_pairs_hook=lambda ps:(
        dupes.extend(k for k,c in collections.Counter(k for k,_ in ps).items() if c>1), dict(ps))[1])
    print(lang, '重复键:', dupes or '无')
"
```

有重复就把两块**合并成一块**(键不重叠时直接并集)。

### 3.10 前端 · useFileManager 依赖数组

**文件**:`pages/knowledge/hooks/useFileManager.ts`

**根因**:主线删掉了 `activeSpace.role` 的用法(状态过滤下沉到服务端),连带从依赖数组里去掉;909 还在用它(深链先装 id 占位、再补 role,靠它挡住重复请求)。

**处理方式**:**依赖数组必须保留 `activeSpace?.role`**。

**注意**:这个点在 2026-09-03 的**两轮合并里各被自动合并悄悄改回一次**(不在冲突块内,不会提示)。合完必跑 `pnpm lint`,`react-hooks/exhaustive-deps` 会抓到。

### 3.11 后端 · Celery 定时任务注册

**文件**:`core/config/settings.py`(定时表)+ `worker/__init__.py`(注册表)

**根因**:任务名写在定时表里,模块 import 写在注册表里,**分处两个文件**,容易只改一边。只改定时表 → worker 每周期报 `Received unregistered task`,任务永远不执行。

**防护**:已有 `test/celery/test_beat_schedule_registration.py`,会遍历整张定时表检查注册。合并后跑一次即可。

### 3.12 后端 · Alembic 又分叉(⚠️ 会挂掉每一次部署)

**症状**:合并本身零冲突,但 `uv run alembic heads` 打出两行。

**根因**:909 的 `f054_merge_cofco_909_heads` 只合并了「当时」的两个头。主线继续往前长(2026-09-07 是 F053 的 `f053_pat_tenant_setting`),再合一次主线就又分叉。**每次合主线都要重新检查一遍。**

**处理方式**:加一个空的 merge revision,`down_revision` 写成当前两个头的元组。别改老的 merge revision。

```bash
cd src/backend && uv run alembic heads          # 必须只有一行
uv run pytest test/database/test_alembic_single_head.py test/permission/test_f048_schema_contract.py -q
```

**为什么必须修**:`entrypoint.sh` 在多头时 fail fast,直接拒绝启动 API —— 不是测试洁癖,是部署会挂。

> 已落地:`f055_merge_cofco_909_f053_heads`(2026-09-07)。

### 3.13 后端 · F053 换掉了 /api/v2 的身份 seam

**根因**:F053(开放 API 鉴权与身份传递)把 `/api/v2` 的身份来源从「请求里的 user_id」改成「凭据」。落地后:

- `filelib.resolve_operator(user_id)` / `get_default_operator_async` **不存在了**,统一是 `get_open_api_operator_async()`(无参)。
- 端点签名里的**裸 `user_id` 入参被移除**。

**处理方式**:

| 位置 | 怎么改 |
|---|---|
| 生产代码 | 取 F053 的 `get_open_api_operator_async()`,**但 909 的 `_require_resolved_tenant(login_user)` 要留在它后面** —— 那是中粮的租户 fail-closed,F053 不提供 |
| 909 的测试 | `monkeypatch.setattr(filelib, "resolve_operator", ...)` → `"get_open_api_operator_async"`;resolver 改成无参;调用里删掉 `user_id=`;`assert_awaited_once_with(91)` → `assert_awaited_once_with()` |

**注意**:909 侧只有一处 hunk 进冲突,其余调用点是**自动合并**掉的 —— 也就是说光看冲突列表会漏掉这批测试,要靠跑测试发现。

### 3.14 后端 · 主线测试撞上 909 的两道守卫

主线新增的测试(2026-09-07 是 `test_openapi_retrieve_file_visibility.py`)不知道 909 多出来的两层,合过来必挂:

| 症状 | 根因 | 处理 |
|---|---|---|
| `TypeError: object MagicMock can't be used in 'await' expression` | 909 在检索路径里插了文件变更审批的查询/名称投影(`project_mutation_retrieval_query` / `_names`),`MagicMock` 的属性不可 await | 把这两个 hook stub 成 `AsyncMock` 直通 |
| `ValueError: positive tenant_id and user_id are required for file visibility` | 909 的可见性服务要求身份和租户 ContextVar 指向同一个正租户 | fixture 给 `login_user` 配 `tenant_id`,并 `set_current_tenant_id()` |
| 查到 `knowledge_space_file_change_request` 表不存在 | 909 独有的表,单测没有 fixture | stub `_list_file_change_excluded_ids` |

**原则**:这三处都是**主线测试补 909 的前提**,不是放宽 909 的守卫。守卫是中粮的安全行为,不能为了让主线测试过就摘掉。

### 3.15 后端 · 同一个函数被两条线各加一个参数

**文件**:`workstation/domain/services/chat_service.py` 的 `_agent_stream_chat_completion` / `_agent_initialize_chat`

**根因**:909 加了限流恢复(`recovery_attempt` / `recovery_message`,走 keyword-only),主线 F053 加了身份传递(`session_subject`)。两边改同一行签名。

**处理方式**:**并集**。位置参数 `session_subject` 放在 `*` 前面,909 的恢复参数留在 `*` 后面,然后**别忘了把 `session_subject` 传进非恢复分支的 `_agent_initialize_chat` 调用**。恢复分支的调用点用的是关键字实参,不受影响。

**坑**:同一次合并里,`MessageSession` 的构造也冲突 —— 主线要 `new_session` 变量(F053 要 `session_subject.stamp(new_session)`),909 要 `name=""`(占位标题由客户端 i18n 渲染,不入库)。取主线的结构 + 909 的空标题。

### 3.16 ⚠️ 自动合并会静默吃掉「只有一方新增的实参」

**2026-09-07 实例**:`knowledge_space_chat_service.py` 的 `_aretrieve_chunks_for_kb` 里,冲突块只有一段注释,但主线在**紧邻的调用**里加了 `sort_by_source_and_index=False`。解完注释冲突后那个实参没了 —— 同文件里的兄弟方法却留着,两条 OpenAPI 检索路径行为不一致。

**检查方法**:冲突块解完后,**看一眼冲突块前后 10 行**对方那侧的 diff(`git diff <merge-base> <对方tip> -- <file>`),确认没有落下相邻的新增行。lint / typecheck / 测试都不一定抓得到 —— 这次是靠主线自带的断言测试才暴露。


---

### 3.17 后端 · 溯源解析(主线重写了整个批量解析)

**文件**:`citation/domain/services/citation_resolve_service.py`

**根因**:主线 F054 把批量解析从「解析不了就静默丢掉」改成「每条说明为什么解析不了」,
整个方法重写(匿名调用者一律拒绝、未知 ID 报「已过期」、无权限报「无权限」);
909 在同一个方法里有三层自己的东西 —— 位置重读(`_canonicalize_rag_items`)、
旧文件名投影(`_project_old_file_names`)、F046 隐藏行过滤(`_file_change_visible_ids`
+ `_apply_file_change_filter`)。两边改同一段,必冲突。

**处理方式**:**取主线的结构,把 909 的三层插回已登录分支**。三个函数在
`login_user is None` 时都是直通,所以匿名分支原样保留主线的写法。顺序照单条解析路径:
位置重读 → 旧名投影 → 算 permitted → F046 过滤 → 分级过滤 → 逐条 enrich。

**一个坑**:位置重读会**丢掉文件行已经不存在的条目**(`file_row is None` 时 continue)。
主线的契约是每个请求 ID 都要么给条目、要么给理由,所以重读前后要对一次 ID 差集,
丢掉的标成「已过期」——已登录调用者本来就能从规则 2 得到同样的答案,不泄露任何东西。

### 3.18 ⚠️ 两条线各自把授权模型从 v3 升到「自己的 v4」

**症状**:`core/openfga/authorization_model_f048.py` 的 `MODEL_VERSION` 冲突,
`test/permission/fixtures/f048_bench_contract.synthetic.json` 与
`test/permission/test_f048_performance_contract.py` 里的 checksum 跟着冲突。

**根因**:主线 F053(服务账号主体)和主线 test 分支 F054(部门上下文成员)各自改了模型,
各自把版本从 `f048-v3` 写成 v4。合并后的模型两个改动都有,**既不是 F053 的 v4 也不是
F054 的 v4**。

**处理方式**:

1. 版本号**另起一个**(2026-09-11 是 `f048-v5`),不要挑任何一边的。
2. checksum **重算,不要挑边**:
   ```bash
   cd src/backend && uv run python -c "
   from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048, authorization_model_checksum
   print(authorization_model_checksum(build_authorization_model_f048()))"
   ```
   把结果写进 bench fixture 的 `authorization_model_checksum`,再重算 `contract_checksum`
   (`scripts/benchmark_f048_permission_paths.contract_checksum`,它是对去掉该字段后的整个
   contract 求哈希),最后同步到性能合同测试里的断言。
   `dataset` / `source` / `visible` 三个 checksum 与模型无关,两边本来就一样,别动。
3. **部署要重新发模型**。任何一边的 v4 已经发过的环境都要再跑一次迁移,见文末「部署提醒」。

### 3.19 前端 · 主线把中文抽成 i18n,909 在同几行有信创修复

**文件**:`components/Chat/Messages/Content/Markdown.tsx`

**处理方式**:**取主线的结构**(`localize(...)` + 新增的「来源已失效」分支),
**但把宽度换回 909 的 `calc(var(--bs-vw,100vw)-32px)`** —— 这是信创 webview 的修复,
跟 §3.8 同一个理由,不能退回 `100vw`。

---

## 4. 合并后验证清单

按顺序跑,**一项都不能省**:

**① 建基线 worktree(不要用 `git stash`)**

合并中途 `git stash` 会因为存在未解决冲突而失败,且可能留下半截 stash。正确做法是拿合并前的 tip 开一个 worktree:

```bash
SP=<scratchpad>
git worktree add -f --detach $SP/base <合并前的 tip>
ln -sfn $(pwd)/src/backend/.venv $SP/base/src/backend/.venv    # 复用 venv,别重装
cp src/backend/bisheng/config.yaml $SP/base/src/backend/bisheng/config.yaml
```

**② 比对失败集,不是比对数字**

```bash
cd src/backend && uv run pytest test/ -q -p no:randomly 2>&1 | tee /tmp/new.txt
cd $SP/base/src/backend && uv run pytest test/ -q -p no:randomly 2>&1 | tee /tmp/base.txt
for t in base new; do grep -E "^(FAILED|ERROR) (test/|src/)" /tmp/$t.txt | sed 's/ - .*//' | sort -u > /tmp/$t.set; done
comm -13 /tmp/base.set /tmp/new.set     # 合并新引入的失败 —— 必须为空
```

> 过滤一定要带 `(test/|src/)`,否则会把日志里以 `ERROR ` 开头的行也算进去,那些行含绝对路径和 task id,两次跑必然不同,看着像一堆差异。
>
> 本仓库有**大量环境相关的既有失败**(全量 480 个左右),所以只能比集合,不能看总数。

**③ 必须跑真实构建**

```bash
cd src/frontend && pnpm lint          # 抓 unused / hooks deps
cd src/frontend/client   && npx vite build
cd src/frontend/platform && npx vite build
```

**`pnpm lint` 和 `pnpm typecheck` 抓不到重复声明** —— 带 `@ts-strict-ignore` 头的文件会被 tsc 跳过,而 esbuild 不会。历史上 CI 挂过两次都是这个:一次 `getLinsight` 重复,一次 `actions` 重复。**合并后必须真跑一次 build。**

**④ i18n 重复命名空间检查** —— 见 §3.9。

**⑤ 后端 celery 注册检查**

```bash
cd src/backend && uv run pytest test/celery/ -q
```

---

## 5. 一些排查陷阱

- **`git log <base>..<tip> -- <path>` 的路径是相对当前目录的。** 在 `src/backend/` 里跑 `-- src/backend/xxx` 会解析成 `src/backend/src/backend/xxx`,**静默返回空**,看起来像「这个文件没被改过」。查历史前先 `cd` 到仓库根。
- **两条线之间可能有多个 merge base。** `git merge-base --all A B` 返回多个时,git 用的是递归虚拟基,这时候用 `git diff <某个base> <tip>` 推断「对方改了什么」会得到错误结论。要问「对方改了什么」,直接用 `git log A..B -- <path>`(在仓库根跑)。
- **「定义了但没人调用」是丢集成点的典型信号。** f048 删服务那类合并特别容易出现:函数搬过来了,但调用点还留在被删的文件里。合并后可以扫一遍新增的导出符号有没有引用方。
- **推之前先 `git fetch`。** 主线可能已经有人用 PR 合了同一个东西。2026-09-03 就撞上一次:本地合完 hotfix,推的时候被 non-fast-forward 拒绝,upstream 已经有 `d53524e69`(#2409),父提交和树跟本地的一模一样。这种情况**直接 `git reset --hard origin/<branch>` 用上游那个**,别造一个「两个相同合并再合一次」的提交。确认方法:`git diff <本地merge> <上游merge>` 为空。

---

## 6. 更新约定

- 每次合并**结束后**回来更新本文件:
  - 新踩到的必冲突点 → 加进 §3
  - §3.1 移植了新行为 → 更新对照表并标日期
  - 结论变了(比如某个「取 3.0」改成了「取 909」)→ **直接改掉旧结论**,不要并列两种说法
- 只在 `feat/cofco-909-3.0.0-beta1` 维护。合并主线时如果本文件冲突,**永远取 909 这边**。
- 已知缺口(§3.6)有进展就更新状态。

---

## 附:历史合并记录

| 日期 | 合并 | 提交 | 备注 |
|---|---|---|---|
| 2026-09-03 | `2.8-common` → `3.0.0-beta1` | `0f0691a79` | 13 个冲突;excel 整合、失败文件可见性移植到 f048 seam |
| 2026-09-03 | `3.0.0-beta1` → `909` | `4db02485a` | 4 个冲突;文件夹 rollup 整合、提示卡片 props 取并集 |
| 2026-09-03 | `cofco-902` → `909` | `22790b986` | 29 个冲突;9 个 f048 已删服务、3 处行为移植;日常对话限流恢复未带过来 |
| 2026-09-03 | `hotfix/3.0.0-beta1` → `3.0.0-beta1` | `d53524e69`(#2409) | 广场可见性与权限解耦;**改了 OpenFGA 授权模型**,见下方部署提醒 |
| 2026-09-03 | `3.0.0-beta1` → `909` | `2efa486f7` | 1 个冲突(空间更新路径,见 §3.2b) |
| 2026-09-07 | `2.8-common` → `3.0.0-beta1` | `dae918025` | 零冲突;技能上传上限 + 知识空间深链两笔 |
| 2026-09-07 | `3.0.0-beta1` → `909` | `b5b7e56e5` | 6 个冲突,全是新的(F053 开放 API 鉴权),见 §3.13 / §3.15 / §3.16 |
| 2026-09-07 | `cofco-902` → `909` | `deed07980` | **零冲突**(①②③ 顺序生效);坑全在合并之后,见 §3.12 / §3.13 / §3.14 |
| 2026-09-11 | `909-test` → `909` | `eb59d7bb8` | 5 个冲突,全是「同一个 bug 两条线各修一遍」;审批人解析取主线的 F048 Grant 读法,删掉 909 那版创建者兜底 |
| 2026-09-11 | `3.0.0-beta1-test` → `3.0.0-beta1` | `07c1c3b3a` | 4 个冲突,全在授权模型与它的 checksum,见 §3.18;另有两个 Feature 撞 F054 编号 |
| 2026-09-11 | `3.0.0-beta1` → `909` | 见本次合并 | 5 个冲突:溯源解析(§3.17)、开放 API filelib 并集、Markdown 文案(§3.19)、两处并集 |

---

## 附:部署提醒 — 授权模型变更(每次合主线都要看)

**结论先行:合完主线、部署上去之前,先假设授权模型变了。** 这不是某一次 hotfix 的偶发问题 ——
两次都撞上了:

| 版本 | 改了什么 | 模型 checksum |
|---|---|---|
| `d53524e69` | 把 `public_reader` 从模型里摘掉 | `98cc4927…` → `0bf16de2…` |
| F053(2026-09-07) | 加了服务账号 / 凭据类型 | `0bf16de2…` → `6d4c1ee3…` |
| 2026-09-11 合并 | F053 的服务账号 + F054 的部门上下文成员,合成 `f048-v5` | → `2ed5c834…` |

**症状**:启动卡在
`Context 'permission_runtime' is in error state: authorization_model_migration_required`,
**所有走权限的接口 500**。这是 F048 的设计行为(发现模型是前代就拒绝启动,等运维迁移),不是 bug。

### 先分清两种情况,再选脚本(⚠️ 2026-09-11 在这里踩过)

两个脚本名字都像"迁移",用错的那个不会静默做坏事,但会白跑一次并留下一大堆垃圾数据。

| 环境状态 | 用哪个 |
|---|---|
| **还没上过 F048**(旧 RBAC 数据要翻译成 grant/投影) | `migrate_f048_permission_data.py` —— 一辈子只跑一次 |
| **已经在 F048 上,只是模型 DSL 变了**(合主线的常态) | `publish_authorization_model_change.py` |

判断方法:查 `permission_migration_run`,已经有一行 `COMPLETED` 就是第二种。

#### 情况二(合主线之后几乎总是这种):只发模型

```bash
C=<backend容器>
# 1. dry-run 是默认行为,它会打出 store_id 和目标 checksum
docker exec -w /app -e PYTHONPATH=/app $C \
  python scripts/publish_authorization_model_change.py
# 2. 把上一步打出的两个值填进来再 apply
docker exec -w /app -e PYTHONPATH=/app $C \
  python scripts/publish_authorization_model_change.py --apply \
    --confirm-store-id <store_id> \
    --confirm-target-model-checksum <target_model_checksum> \
    --operator-id 1
# 3. 重启后端和 worker
docker compose restart backend backend_worker backend_worker_ocr
```

它只做三件事:把新模型写进 OpenFGA、在 `authorization_model_release` 登记并置 ACTIVE、
发一个空的 Catalog release 把 CURRENT 指过去。**不碰任何权限数据**,所以没有 verify 那道坎。

`--apply` 的前置条件:没有活跃的 F048 运行时心跳、没有在途的投影操作、CURRENT Catalog 没被写围栏、
store-id 和 checksum 对得上。模型没发出去的时候所有进程的权限运行时都是 error 态、心跳为 0,
所以这一步可以直接在**正在运行的** backend 容器里跑,不用先停容器。

#### 情况一:首次迁移

```bash
docker exec -w /app -e PYTHONPATH=/app <backend容器> \
  python scripts/migrate_f048_permission_data.py migrate --apply
# 中断后用 --run-id <id> 续跑,不要从头再来
```

它会一次做完三件事:在 OpenFGA 里发布新模型、在 `authorization_model_release` 登记它、
把 `permission_catalog_release` 指过去,并把旧权限数据翻译成新模型的 grant/投影。

**已经在 F048 上还跑它会怎样**(2026-09-11 实测):扫到的关系它都不认识,报
`F048 migration blocked: UNKNOWN_LEGACY_RELATION` 退出。权限数据一行没动,但它在
`permission_migration_run` 留下一行 `BLOCKED`,并在 `permission_migration_item` 里落了
**26 万行**扫描结果。这些行不会被任何投影引用(查 `permission_visible_source_projection`
的 `migration_item_id` 全是 NULL 即可确认),但要清就得先删 item 再删 run —— 有外键,顺序反了删不掉。

### ⚠️ 不要用 `openfga.force_write_model` 抄近路

看起来它能"一键发布新模型"(非 production 环境启动时自动写),**但它只写 OpenFGA,不碰数据库的登记表**。
后果(2026-09-07 实测,绕了两小时):

1. OpenFGA 里是新模型,`authorization_model_release` 还 ACTIVE 指着旧的 —— 三方对不上,照样 `migration_required`。
2. 它顺手写下的 `f048-initial` catalog 行会**把正规迁移挡住**:
   `PermissionVersionConflictError: Initial F048 Catalog differs from checkpoint`。
   清理办法是删掉这行 + 它派生的 `permission_action` / `permission_model` 行 + 那条 ACTIVE 的
   `authorization_model_release`,再 `migrate --apply --run-id <id>` 续跑。**删之前先确认
   `permission_grant` / 各 projection / `resource_permission_mode` 都是空的** —— 非空说明有真数据挂在上面。
3. **开着不关会让每个工作进程启动时各写一次模型**,catalog 和进程 pin 立刻错位,报
   `CURRENT Catalog does not match the process OpenFGA pin`,子进程反复启动失败(容器却还显示 healthy,
   因为健康检查打的是 `/health`,不经过权限运行时)。真要用,发布完**立刻改回 false 并重启**。

### 成功判据(三个都要满足)

```
permission_catalog_release  有一行 status = CURRENT
authorization_model_release 那一行 status = ACTIVE      ← 最容易漏
日志出现 FGAClient initialized from discovered runtime,且不再有 migration_required
```

**第二条单独说**:catalog 变 CURRENT 但模型还是 `STAGED` 时,报的是
`CURRENT Catalog authorization model is not active` —— 和 `migration_required` 是**不同的错**,
别当成同一个问题查。走首次迁移时,模型转 ACTIVE 发生在 verify 通过之后;走
`publish_authorization_model_change.py` 时它当场就是 ACTIVE,没有 verify 这一步。

再补一条**功能判据**:未登录打一个走权限的接口,应当是 401 而不是 500。

> 2026-09-11 在 105 的实际结果,可作为对照样板:
> `permission_catalog_release` 37 CURRENT → `authorization_model_release` 4 ACTIVE
> (`f048-v5` / `01M27RXA627215TZ0SH363ZYPW`),前一条 3 自动转 RETIRED;
> 重启后 60 秒内 `migration_required` 零次,`/api/v1/knowledge/space/mine` 返回 401。

### verify 的现实问题:慢库上跑不完

`verify --run-id <id>` 是迁移后的独立校验:拿迁移算出的期望值反问 OpenFGA
"这个人到底能不能看到这个对象",而且同一问题批量问一遍、再逐条问一遍,比对两种问法是否一致。
**不写数据,只读回来对答案。**

它的规模是 **O(不同用户 × 不同对象)**,且每个对象都要一次单独 Check。2026-09-07 在 105 上是
31 个用户 × 1012 个对象 ≈ **3.4 万次单条 Check**。

跑之前三个前提,缺一个就挂:

| 前提 | 症状 | 处置 |
|---|---|---|
| **内存** | `RC=137`(OOM kill) | 宿主 15G 被 `backend_worker` 吃掉 6.2G;临时 `docker compose stop backend_worker backend_worker_ocr`,跑完再起 |
| **客户端超时** | `FGAConnectionError: OpenFGA unreachable:`(冒号后是空的) | `config.yaml` 的 `openfga.timeout` 默认 5 秒,调到 120 |
| **服务端超时** | `OpenFGA 500: {"code":"deadline_exceeded"}` | compose 里 openfga 没配请求超时,加 `OPENFGA_REQUEST_TIMEOUT: 300s` 后重建 |

三个都满足了,**吞吐仍然可能低到跑不完**。105 上 OpenFGA 只有 15 请求/分钟(它的库是达梦,
而那台机磁盘 99% 满),3.4 万次 Check ≈ 4 天。

**这种情况下的取舍**:数据面(grant / 投影 / 资源模式)是迁移脚本已经写好的,verify 只是事后
第三方核对。测试环境可以直接把 `authorization_model_release` 置为 ACTIVE、
`permission_migration_run` 置为 COMPLETED 收尾,**但要先确认数据面非空**,并把 verify 记为欠账,
在库性能正常的环境(客户测试环境 / 生产)上补跑。**生产不要跳过。**

> 注:达梦驱动不接受把 `sa.func.now()` 当绑定参数(`dmVar_TypeByValue(): unhandled data type now`),
> 手写 UPDATE 时用 Python 的 `datetime.datetime.now()`。

### 旧 tuple 清理

旧 Store 里遗留的 `public_reader` tuple 需要单独清理,脚本和步骤见
`src/backend/scripts/README.md` 的 `cleanup_f048_public_reader_tuples.py`(先 dry-run,
apply 要带上一次 dry-run 打出的 store-id 和 checksum)。
