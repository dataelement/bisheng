# 中粮分支合并手册

> **这份文档只在 `feat/cofco-909-3.0.0-beta1` 上维护。** 每次合并完，把新踩到的坑和调整后的结论回写到这里。
>
> 用途:中粮定制线和主版本线并行开发,同一批 bug 常常两条线各修一遍,合并时**同一批文件反复冲突**。这里记录每处冲突「为什么必然冲突」和「按什么原则收」,下次直接照表处理,不用重新推理一遍。
>
> 最近一次全量合并:2026-09-03(2.8-common → 3.0.0-beta1 → 909 ← cofco-902)

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
