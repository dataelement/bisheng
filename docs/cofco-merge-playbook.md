# 中粮分支合并手册

> **先读 [`release-trains.md`](release-trains.md)**:哪条是本期、哪条是下一批、往哪个方向合。
>
> **本文只记「每次合并都会冲突」的点**,以及合并后的检查清单。只冲突过一次的点不写进来,
> 按三方版本逐块解决即可。历史合并过程看 git log,不写进本文。
>
> **只在中粮线维护**(`feat/cofco-909-*`,经合并流向后续中粮分支),主版本分支不放这份文档。
> **每次合并结束都要更新本文**:新发现的必冲突点加进 §2,过时的点删掉,
> 结论变了就直接改掉旧结论,不要把两种说法并列。本文自身冲突时,取中粮这一侧。

---

## 1. 合并顺序

```
① 主线本期  → 主线下一批        (feat/3.0.0-beta1-batch1 → feat/3.0.0-beta1)
② 主线下一批 → 中粮下一批        (feat/3.0.0-beta1 → feat/cofco-909-3.0.0-beta1)
```

同一层先把主线合平,再合进中粮线:通用修复会以「已经适配好新底座」的样子进来,
留在中粮线上的冲突只剩真正的定制差异。**反方向合并一律禁止**:中粮代码不回流主线,
下一批的代码也不合回本期。

---

## 2. 每次必冲突的点

> 用法:合并中断后先 `git diff --name-only --diff-filter=U` 列出冲突文件,再对照本节处理。
> 除非本节写明,**不要整文件取某一侧**(`--ours` / `--theirs`),要逐块合并。

### 2.1 知识空间服务 `knowledge_space_service.py`(几乎每次都冲突)

**原因**:两条线都在持续改这个文件,中粮线在同一批方法里嵌了自己的逻辑。

**原则**:结构和通用修复取主线;以下中粮逻辑**一律保留**:

- 文件变更审批的隐藏过滤(未审批通过的文件不对其他人显示)
- 租户一致性守卫
- 文件夹统计用的分块 UNION 批量查询,不要退回「每个文件夹查一次」
- 部门空间不允许转为私密的守卫
- 空间详情里的下载开关(`download_action_enabled`)
- 权限判定统一走 `_check_action(...)`,不走已删除的旧接口

主线常见的冲突形式是**纯格式化或抽成公共函数**(例如 2026-09-18 把「可见即已加入」的判断
抽成 `_resolve_effective_subscription_status`)。这时取主线的写法,中粮这侧的注释可以留下。

### 2.2 主线新测试撞上中粮的守卫(每次合主线都会出现)

主线测试不知道中粮额外多出的几层,合过来就失败。处理原则:**给测试补上中粮的前提条件,
不要为了测试通过去放宽中粮的守卫**。

| 症状 | 原因 | 在测试里补 |
|---|---|---|
| `Context 'permission_runtime' not found` | 空间详情要查下载开关 | patch `get_f048_runtime`,返回的 `effective_actions` 里包含 `download` |
| `MagicMock can't be used in 'await' expression` | 检索路径多了文件变更审批的查询和名称投影 | 把 `project_mutation_retrieval_query` / `_names` stub 成直通的 `AsyncMock` |
| `positive tenant_id and user_id are required` | 可见性服务要求当前用户和当前租户是同一个正数租户 | 给 `login_user` 配上 `tenant_id`,并调用 `set_current_tenant_id()` |
| `knowledge_space_file_change_request` 表不存在 | 这张表只在中粮线上有 | stub `_list_file_change_excluded_ids` |

### 2.3 ⚠️ 中粮独有的配置被静默删掉(不冲突、测试也测不到)

**文件**:`docker/bisheng/config/config.yaml`,以及任何只在中粮线上有的配置段。

**原因**:三方合并分不清「主线从来没有这段」和「这段被删了」。主线没有中粮的配置段,
合并就按删除处理,**而且不出冲突**。代码里的默认值是关闭,所以丢了也不会报错,
只是功能悄悄失效。2026-09-17 合进 923 时,`knowledge_space_read_bypass` 就这样整段消失了。

**必须保留的中粮配置**(新增定制配置时同步加到这张表和守卫测试里):

| 配置 | 用途 |
|---|---|
| `knowledge_space_read_bypass` | 指定知识空间绕过读权限的白名单 |
| `sso_sync.gateway_hmac_secret` 的实际值 | 客户正在使用的部门/用户同步密钥;**主线上为空,中粮线必须保留原值** |

**防护**:守卫测试 `src/backend/test/cofco/test_cofco_config_customizations.py`,
加上 §3 第 ⓪ 步的全量比对。

**前端代码同理,而且不一定发生在合并里。** 普通提交也会顺手「整文件取主线」:2026-09-18 发现
知识空间 AI dock 的引用条(勾选文件 → 输入框上方灰条、勾选即问答范围)被一个后端 fix 连带换成了
主线版本,主线从没有这段,等于直接删掉。

**别指望比对分支发现它。** 试过三种比对都不成立:拿上一条中粮分支当基准,它自己可能早已丢了
(这次 909 末端就已经和主线一致);拿「不在主线上的提交」当基准,中粮线和 3.0 主线血统不同,
命中几百个文件全是噪音。类型检查也未必兜得住:上游仍给被删的 prop 传值会报 TS2322,但调用方常带
`@ts-strict-ignore`,`pnpm typecheck` 看不见。

**后端定制同样会被静默删掉。** 2026-09-19 发现 F045 的两处部门空间逻辑在 2026-09-01 合并 3.0
时丢了:知识空间服务以主线文件为底重建,嵌在已有函数里的中粮片段没补回来。部门空间因此显示
建空间的超管为创建者,没有管理员的部门空间还能发起加入申请(没人能审批)。F045 自己的 20 个
测试只测部门空间服务,测不到「知识空间服务有没有调用它」。

**只能按功能守护。** 必须保留的中粮定制,每项配一个能直接判断「还在不在」的检查
(新增定制时同步加进这张表):

| 定制 | 检查(合并后在仓库根目录跑,输出 0 即丢了) |
|---|---|
| 知识空间 AI dock 引用条 | `grep -c selectedContent src/frontend/client/src/pages/knowledge/SpaceDetail/AiChat/KnowledgeAiBottomDock.tsx` |
| F045 部门空间显示管理员而非创建者 | `grep -c "never surfaces on a" src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` |
| F045 无管理员时拦住申请加入 | `grep -c "ensure_space_not_pending_admin(space.id)" src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` |

守卫测试:`src/backend/test/cofco/test_cofco_department_space_admin.py`(这两处调用)、
`src/backend/test/cofco/test_cofco_config_customizations.py`(配置)。

### 2.4 Alembic 迁移分叉(每次合主线都要检查)

**症状**:合并本身可能零冲突,但 `alembic heads` 输出两行。后端启动时发现多个 head 会
**直接拒绝启动**。

**原因**:中粮线上的 merge revision 只合并了当时的两个 head,主线之后新增的迁移会再次分叉。

**处理**:新建一个空的 merge revision,`down_revision` 填当前两个 head 组成的元组;
不要修改已有的 merge revision。目前最新的是 `f061_merge_cofco_909_f066_heads`。

### 2.5 授权模型版本号与 checksum(主线改了模型就会冲突)

**文件**:`core/openfga/authorization_model_f048.py` 的 `MODEL_VERSION`,
以及 `test/permission/fixtures/f048_bench_contract.synthetic.json`、
`test/permission/test_f048_performance_contract.py` 里的 checksum。

**原则**:checksum **重新计算,不要挑选任何一侧**;如果两侧都改了模型,版本号另起一个新的。

```bash
cd src/backend && uv run python -c "
from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048, authorization_model_checksum
print(authorization_model_checksum(build_authorization_model_f048()))"
```

计算结果写进 bench fixture 的 `authorization_model_checksum`,然后重新计算
`contract_checksum`(`scripts/benchmark_f048_permission_paths.contract_checksum`),
最后同步到性能合同测试的断言里。

**模型变了,部署就必须跑发布脚本**,见 §4。

### 2.6 前端信创视口修复

**文件**:溯源抽屉 `CitationReferencesDrawer.tsx`、`Markdown.tsx` 等涉及视口宽高的组件。

**原则**:高度用 `var(--bs-dvh,100dvh)`,宽度用 `var(--bs-vw,100vw)`,这是信创 webview 的修复,
**不能退回** `100dvh` / `100vw`;文案和 i18n key 取主线的。

### 2.7 前端 i18n 文件 `client/src/locales/*/translation.json`

**常规处理**:两侧都在同一位置新增 key,双方都保留(注意补逗号)。

**⚠️ 必查同名命名空间**:两条线可能各自新建了同名的顶层块,合并后 JSON 只保留后一块,
**另一块的 key 会静默变成空**。这时 JSON 仍然合法,`pnpm check-i18n` 也照样通过。检查方法见 §3 第 ④ 步。

---

## 3. 合并后检查清单

按顺序执行,每一项都不能省。

**⓪ 查被静默删掉的中粮定制(§2.3)**:这一步要放在跑测试之前,因为测试发现不了。

```bash
diff <(git show <合并前的中粮tip>:docker/bisheng/config/config.yaml) \
     docker/bisheng/config/config.yaml | grep "^<" | grep -vE "^< *#|^< *$"
diff <(git ls-tree -r --name-only <合并前的中粮tip>) <(git ls-tree -r --name-only HEAD) | grep "^<"
```

有输出就逐条确认:是主线有意删除的,还是中粮定制被当成删除抹掉了。

**① 检查冲突块周围**:冲突块解完之后,看一眼块前后 10 行对方那一侧的 diff,
确认没有漏掉相邻的新增行(比如主线在紧挨着的调用里新加的参数)。自动合并掉的行不会提示。

**② 后端:比较失败集合,不要只看失败数量**

仓库里有大量依赖环境的既有失败,所以只能比较集合。基线用 worktree 建,
**合并中途不要用 `git stash`**:有未解决的冲突时会失败,还可能留下半截 stash。

```bash
git worktree add --detach $SP/base <合并前的tip>
ln -s $(pwd)/src/backend/.venv $SP/base/src/backend/.venv
cp src/backend/bisheng/config.yaml $SP/base/src/backend/bisheng/
# 两边各跑一次相同范围的 pytest,然后:
grep -E "^(FAILED|ERROR) test/" out.txt | sed 's/ - .*//' | sort -u > x.set
comm -13 base.set new.set     # 合并新引入的失败,必须为空
cd src/backend && uv run alembic heads                            # 只能有一行
uv run pytest -q test/cofco test/celery test/database/test_alembic_single_head.py
```

**③ 前端:必须真跑一次构建**。带 `@ts-strict-ignore` 的文件会被 tsc 跳过,
所以 lint 和 typecheck 都抓不到重复声明,只有 vite build 能报出来。

```bash
cd src/frontend && pnpm lint
cd client && npx vite build && cd ../platform && npx vite build
```

**④ i18n 重复 key 检查**

```bash
cd src/frontend/client && python3 -c "
import json, collections
for lang in ('en','ja','zh-Hans'):
    dupes=[]
    json.loads(open(f'src/locales/{lang}/translation.json',encoding='utf-8').read(), object_pairs_hook=lambda ps:(
        dupes.extend(k for k,c in collections.Counter(k for k,_ in ps).items() if c>1), dict(ps))[1])
    print(lang, dupes or '无重复')
"
```

**⑤ 推送前先 `git fetch`**:主线可能已经有人合过同一批内容。如果远程的合并提交和
本地的内容完全一致,直接用远程的,不要再做一个重复的合并提交。

---

## 4. 合并后的部署提醒

- 合并前后对比一次 `MODEL_VERSION`。**模型变了,升级时必须执行**
  `scripts/publish_authorization_model_change.py`(先 dry-run,再 apply),
  否则后端会报 `authorization_model_migration_required`,所有走权限的接口都返回 500。
  用法见 `src/backend/scripts/README.md`。
- **不要用 `openfga.force_write_model` 走捷径**:它只写 OpenFGA,不写数据库里的登记表,
  会导致 OpenFGA 和数据库的登记对不上。
- 模型发布是单向的,发布后回不到旧模型。先在和客户起点一致的测试环境演练。
