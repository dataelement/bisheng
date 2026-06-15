# F036 压测报告 — 知识空间子项列表 ReBAC 评估优化

**日期**: 2026-06-15 · **环境**: 109(`192.168.106.109`,达梦 + OpenFGA-on-DM)· **被测接口**: `GET /api/v1/knowledge/space/57/children`
**分支**: `worktree-feat+2.6.0+036-rebac-eval-cost-optim`(从 `feat/2.6.0-beta4` 切出)
**部署方式**: 把改动的两个文件 `docker cp` 进 `bisheng-backend-dm` 容器(原文件备份为 `.f036bak`),`docker restart` 加载;压测后已**还原为原始代码**。

---

## 1. 背景与定位

原始 Locust 报告:`/children` 等接口在并发下 P50 22–24s、Min 也有 10–16s。实测归因(见 spec 前置):
- 单请求仅 **0.6s**;DM 查询 1–11ms、OpenFGA 单次 Check 8–15ms,均不慢。
- 并发下 **backend CPU 打满(~704%)**,OpenFGA 146%、Milvus 15%。
- 根因:`_filter_visible_child_items` 对**每个子项**做一次细粒度 ReBAC 评估(逐项 `read_tuples` + 逐 tuple 线性扫 bindings + 每项 2 次 `get_*_permission_level`),CPU 随页内项数线性增长。

## 2. 改动(本次落地 ①③;② 不可行)

- **③ bindings 索引**:`_resolve_binding_for_tuple` 由"每 tuple 线性扫全 bindings"改为按 `(resource_type,resource_id)` O(1) 命中。
- **① 继承快速通道**(开关 `BS_REBAC_CHILD_FASTPATH`,默认关):无更近 binding 的子项跳过完整逐项评估,继承"父链决策"(每条链算一次)或 owner 短路(`item.user_id==当前用户`);仅叶级有 binding 的项走完整评估。原逐项路径保留为 oracle/兜底。
- **② 整页批量预取 tuple**:不可行 —— OpenFGA `/read` 无多对象批量原语;且其想省的 I/O 已被 ① 跳过评估所覆盖。
- 前置不变量(已用 109 数据验证):**file/folder 上非 owner 的真实授权 100% 有 binding**(裸 tuple=0);`owner`/`parent` 裸 tuple 为加性/结构性,不影响可见集。

## 3. 正确性:真实数据等价校验(安全红线)

对 sarah(user 1)/space 57,分别在 **flag OFF**(完整逐项)与 **flag ON**(快速通道)下抓取 `/children` 4 个变体(全量 / `file_status=2` / `file_type=1` / `file_type=0`)返回的文件 id 集合:

| 变体 | OFF count | ON count | id 集合 |
|---|---|---|---|
| `page_size=500` | 98 | 98 | **完全一致** |
| `&file_status=2` | 98 | 98 | **完全一致** |
| `&file_type=1` | 98 | 98 | **完全一致** |
| `&file_type=0` | 0 | 0 | 一致 |

→ **FINGERPRINT 逐位相等**,快速通道与原路径返回相同可见集。
单测另覆盖:owner 短路、叶级 binding 走完整评估不走链、bindings 索引等价(见 `test/permission/test_f036_binding_index.py`、`test/knowledge/test_f036_child_fastpath_equivalence.py`)。

> **本次校验局限**:sarah 为 admin、space 57 文件均无 binding(走继承/owner 分支);叶级 binding 分支由单测覆盖,未在 109 用"有 binding 的空间 + 非 admin 用户"做端到端 diff。合入前建议补这一场景的真实数据 diff。

## 4. 性能结果(20 并发 × 6 轮 = 120 请求,`/children?page_size=20`)

| 配置 | p50 | p95 | p99 | min | max |
|---|---|---|---|---|---|
| 原始基线(未改造,早前实测) | ~4.5s(20并发) / 22–24s(Locust 持续) | — | — | — | — |
| **FLAG OFF**(③ + 完整逐项) | 4.898s | 5.038s | 5.105s | 4.151s | 5.121s |
| **FLAG ON**(①③ 快速通道) | **0.338s** | **0.587s** | 0.615s | 0.155s | 0.644s |

- **① 快速通道:p50 提升 ~14.5×(4.898→0.338s)、p95 ~8.6×**;并发下稳定在亚秒级。
- **③ 单独贡献有限**:FLAG OFF≈原始基线,因为本环境 bindings 仅 42 条,线性扫描本就不是瓶颈。真正消除 704% CPU 的是 ①(多数项不再做逐项评估 + 不再每项 2 次 `get_*_permission_level`)。
- 对照原始 Locust 的 22–24s,①③ 把同口径接口压到亚秒级。

## 5. 结论与建议

- ① 是关键优化,且经真实数据验证可见集等价;**已按决定去掉开关 `BS_REBAC_CHILD_FASTPATH`,优化逻辑成为默认且唯一路径**(完整逐项 `_filter_visible_child_items_reference` 保留作等价测试 oracle/兜底)。本报告中的 "flag OFF/ON" 是当时为 A/B 压测临时切换的方式。
- 已补测试缺口:① "有 binding 空间 + 非 admin 用户"真实 eval 等价(`test_f036_real_eval_equivalence`);② "授权 binding ↔ fast-path bound_ff"闭环(`test_f036_invariant`)。残留非阻断建议:authorize 写路径加 arch-guard 强制"非 owner 授权必带 model_id ⟹ 写 binding"。
- ③ 保留(零风险、O(1) 解析);在 bindings 规模增大的租户上收益会更明显。

## 附:复现实命令骨架

```bash
# 20 并发 × 6 轮，取 p50/p95/p99/min/max
for r in $(seq 1 6); do for i in $(seq 1 20); do
  (curl -s -m120 -o /dev/null -w '%{time_total}\n' -H "Cookie: $TK" \
   'http://localhost:7865/api/v1/knowledge/space/57/children?page_size=20' >> /tmp/t) & done; wait; done
sort -n /tmp/t | awk '{a[NR]=$1} END{print "p50="a[int(NR*.5)]" p95="a[int(NR*.95)]" max="a[NR]}'
# flag 切换：sed 改 BS_REBAC_CHILD_FASTPATH 默认值 + docker restart bisheng-backend-dm
```
