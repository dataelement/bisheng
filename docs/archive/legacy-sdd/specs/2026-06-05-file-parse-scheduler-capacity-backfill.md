# 文件解析调度 —— 全局并发上限 + 轮询取数(方案1)

**日期**:2026-06-05(2026-06-05 修订:纠正限流模型)
**关联设计**:`docs/archive/legacy-sdd/specs/2026-05-20-file-parse-scheduler-design.md`
**状态**:待审核(spec)

---

## 1. 背景与问题

现有公平调度器 [`run_dispatch_round`](../../../src/backend/bisheng/worker/knowledge/scheduler.py) 有两个错误:

1. **把 `max_per_user_inflight` 当成"每用户在飞上限"**,默认 `1` → 每个用户最多 1 份在飞。
   `DISPATCH_ONE` 里 `SCARD(inflight:user) >= limit → 跳过`。
2. **每个活跃用户每轮只派 1 个**,无"填满到并发上限"的回填。

结果:**在飞文件数 ≈ 活跃用户数**。1 个用户传 20 份只跑 1 份,20 个 worker 线程里 19 个空转。

### 正确的需求模型

- 文件解析**只有一个硬上限:全局最大并发**(例:knowledge_celery 20、ocr_celery 5),贴着 worker 部署的 `-c` 之和配置。
- **公平 = 轮询取数粒度**:调度时按用户轮询,每轮从一个用户队列取 **1 份**(可按用户加权),依次铺满到全局并发上限为止。
- **用户在飞数不设上限**:某用户可以同时有多份在飞(取决于轮询填充的结果),不该被一个 per-user 上限卡住。
- 填满后等待;有文件完成释放出空位,再按同样规则继续取队列中的文件。

### 目标示例(本 spec 的验收基准)

```
全局并发上限 = 20;用户 A/B/C 分别排队 10 / 50 / 2 份
轮询(每用户每轮取 1)铺满 20:
  轮1: A,B,C       → 在飞 3
  轮2: A,B,C       → 在飞 6   (C 队列取空)
  轮3: A,B         → 在飞 8
  …  A、B 交替 …
  轮9: A,B         → 在飞 20  → 停止,等待空位
稳态在飞: A=9, B=9, C=2;  队列剩余 A=1, B=41
每完成 1 份 → 释放 1 个空位 → 再按轮询规则补 1 份,始终维持 20 在飞
```

---

## 2. 目标 / 非目标

**目标**

- G1:调度器拥有一个**可配置的全局并发上限(每队列)**,把在飞数回填到该上限。
- G2:单用户独占时也能打满整条队列(解决利用率问题)。
- G3:多用户竞争时,按"每用户每轮取 1"的轮询近似公平分配剩余并发额度。
- G4:全程在 `fair_scheduler_enabled` flag 内;flag 关闭时行为不变。

**非目标**

- 不做心跳上报并发的自适应方案(后续"方案2");本 spec 用**静态配置**声明并发上限。
- 不引入"每用户在飞上限"(明确否定原 `max_per_user_inflight` 语义)。
- 不改 OCR 分流、hash-tag、多租户、对账四大 Case 的既有语义。
- 全局上限是**准入目标**,不是精确实时背压。

---

## 3. 核心模型(请重点审核)

**只有一层硬限流 + 一个公平权重参数:**

| 参数 | 作用域 | 语义 | 默认 |
|------|--------|------|------|
| `queue_concurrency[queue]` | 每队列(全局) | 该队列**最大同时在飞**文件数 = 文件解析最大并发,贴 worker `-c` 之和 | knowledge_celery=20, ocr_celery=5 |
| `per_user_pick_size` | 每用户 | 用户的**公平权重**(份额比例,非在飞上限) | 1 |
| `user_overrides` | 按用户 | 覆盖某用户的权重,如 `{"1": 3}` → 用户 1 维持约 3 倍在飞份额 | {} |

**算法 = 加权最少在飞优先(weighted least-inflight)回填:**
每派发一份,就从"队首文件指向未满队列"的活跃用户中,挑选 `当前在飞数 / 权重` **最小**的用户取 1 份;
重复直到该队列在飞数达到 `queue_concurrency` 为止。完成事件释放空位后,同样把空位给"份额最少"的用户。

关键性质:

- **唯一硬上限是 `queue_concurrency`**,与用户数无关 → 单用户也能独自填满(G2)。
- **没有 per-user 在飞上限**,用户可累积多份在飞(示例里 A=9、B=9),彻底移除原 `max_per_user_inflight` 拦截。
- **释放的空位给份额最少者(解决 D3)**:B 的文件完成腾出的空位,会优先补给当前份额更低的 B,而**不会**被排队最多的 A 抢走 → A/B 份额自动均衡,谁都不会被长期压在后面。
- **`user_overrides` 即权重**:`{"1": 3}` 让用户 1 的在飞份额维持在普通用户的约 3 倍(选择键用 `inflight / weight`)。

> 与原实现的本质差异:原 `max_per_user_inflight=1` 是"用户最多 1 份在飞"(=bug);新 `per_user_pick_size` 是"份额权重"(默认 1 即等额竞争),不限制总在飞。

---

## 4. 配置变更

`config.yaml` 的 `knowledge_file_worker.fair_scheduler` 节:

```yaml
knowledge_file_worker:
  ocr_queue_enabled: true
  ocr_queue: "ocr_celery"
  fair_scheduler_enabled: true
  fair_scheduler:
    dispatch_lock_ttl_seconds: 24
    inflight_ttl_seconds: 7200
    # 新增:每队列全局并发上限 = 文件解析最大并发(需与 worker 的 -c 之和对齐)
    queue_concurrency:
      knowledge_celery: 20      # 该队列所有 worker 进程 -c 之和
      ocr_celery: 5
    # 替代原 max_per_user_inflight:用户公平权重(份额比例,非在飞上限)
    per_user_pick_size: 1
    user_overrides: {"1": 3}    # 按 user_id 覆盖权重,如用户 1 维持约 3 倍在飞份额
```

`FairSchedulerConf`([settings.py:268](../../../src/backend/bisheng/core/config/settings.py#L268))变更:

```python
# 删除:max_per_user_inflight、原 limit_for 的"在飞上限"语义
queue_concurrency: dict[str, int] = Field(
    default_factory=lambda: {"knowledge_celery": 20, "ocr_celery": 5}
)
per_user_pick_size: int = Field(default=1, ge=1)
user_overrides: dict[str, int] = Field(default_factory=dict)  # file_id 粒度的取数权重

def concurrency_for(self, queue: str) -> int:
    return self.queue_concurrency.get(queue, self.per_user_pick_size)

def weight_for(self, user_id: str) -> int:
    # 公平权重:in-flight 份额按权重比例分配
    return self.user_overrides.get(str(user_id), self.per_user_pick_size)
```

**运维契约**:`queue_concurrency[q]` 应 = 监听队列 q 的所有 worker 进程 `--concurrency` 之和(如 5 进程 × 20 = 100)。配大 → broker 排队(不丢);配小 → worker 欠载。

---

## 5. Redis 数据模型变更

沿用 `{bisheng_fs}` hash-tag,新增 2 个 key:

| Key | 类型 | 内容 | 维护点 |
|-----|------|------|--------|
| `{bisheng_fs}:inflight_total:<queue>` | String(计数) | 该队列当前在飞数 | confirm 时 INCR / complete 时 DECR / reconcile 重算 |
| `{bisheng_fs}:inflight_queue` | Hash | `file_id` → `queue` | confirm 时 HSET / complete 时 HDEL |

> 全局并发判定基于 `inflight_total:<queue>`(而非用户在飞集合的求和),保证准入只看队列总量。
> `inflight_queue` 让 `complete_file` 知道该归还哪条队列的容量。
> 计数器为"建议值,reconcile 自愈":worker 崩溃造成的漂移只引起短暂过派/欠派(吞吐问题,非数据问题)。

既有 `inflight:<user_id>` 集合、`inflight_users`、`active_users` **保留**(对账、归属仍需要),仅不再用于"准入判断"。

---

## 6. Lua 脚本变更

### 6.1 `DISPATCH_ONE` —— 移除 per-user 在飞上限检查

原脚本的 `if SCARD(inflight:user) >= limit then return nil` **删除**。新脚本只做"RPOP 一份 + 加入 user inflight 集合":

```lua
-- KEYS[1] = user_id   (不再接收 limit 参数)
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local queue_key  = prefix .. 'queue:'  .. user_id
local active_key = prefix .. 'active_users'

local file_id = redis.call('RPOP', queue_key)
if not file_id then
    redis.call('SREM', active_key, user_id)
    return nil
end
if redis.call('LLEN', queue_key) == 0 then
    redis.call('SREM', active_key, user_id)
end
redis.call('SADD', prefix .. 'inflight:' .. user_id, file_id)
redis.call('SADD', prefix .. 'inflight_users', user_id)
return file_id
```

> 全局并发上限改由 Python 层在 RPOP 后、CONFIRM 前判定(因为目标队列要读 payload 的 file_ext 才能确定,Lua 内算不出)。

### 6.2 新增 `CONFIRM_DISPATCH`

apply_async 成功后调用(替代现在的 `delete_payload`):

```lua
-- KEYS[1] = file_id ; ARGV[1] = queue
local prefix = '{bisheng_fs}:'
local file_id = KEYS[1]
local queue   = ARGV[1]
redis.call('HSET', prefix .. 'inflight_queue', file_id, queue)
redis.call('INCR', prefix .. 'inflight_total:' .. queue)
redis.call('DEL',  prefix .. 'payload:' .. file_id)
return 1
```

### 6.3 `COMPLETE_FILE` —— 增加 DECR/HDEL

```lua
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]
redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
local queue = redis.call('HGET', prefix .. 'inflight_queue', file_id)
if queue then
    redis.call('DECR', prefix .. 'inflight_total:' .. queue)
    redis.call('HDEL', prefix .. 'inflight_queue', file_id)
end
if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
end
return 1
```

### 6.4 `ROLLBACK_DISPATCH` —— 不变

回滚发生在 `CONFIRM_DISPATCH` 之前(计数器尚未 INCR),只做"移出 user inflight + 放回队列",无需 DECR。

> 顺序铁律:**先 apply_async,成功后才 CONFIRM_DISPATCH**;INCR 与 complete 的 DECR 严格配对。

---

## 7. 分发任务完整流程(本 spec 重点)

### 7.1 一次调度轮 `run_dispatch_round`

```
function run_dispatch_round():
    token = acquire_dispatch_lock(ttl)         # 全局唯一,防并发轮
    if not token: return                        # 上一轮在跑,跳过
    try:
        cap      = { q: concurrency_for(q) for q in queues }      # 每队列并发上限(配置)
        inflight = { q: GET inflight_total:q for q in queues }     # 每队列当前在飞(快照)
        saturated = set()                        # 本轮判满的队列
        skipped   = set()                        # 本轮搁置的用户(队空/队首指向满队列)

        # 每个用户当前在飞份额(本地快照,派发后递增)
        users = active_users()                   # Redis Set
        share = { u: SCARD(inflight:u) for u in users }

        while not (所有 queue ∈ saturated):
            # 加权最少在飞优先:选 share[u]/weight(u) 最小的可派用户
            eligible = [u for u in users if u not in skipped]
            if not eligible: break
            user_id = argmin(eligible, key = lambda u: share[u] / weight_for(u))

            file_id = DISPATCH_ONE(user_id)         # 仅 RPOP + 加 user inflight
            if file_id is None:
                skipped.add(user_id); continue       # 该用户队空

            payload = HGETALL(payload:file_id)
            if not payload:
                ROLLBACK_DISPATCH(user_id, file_id)  # payload 丢失,交对账
                skipped.add(user_id); continue

            queue = decide_queue(payload.file_ext)   # 路由由 file_ext + 配置决定

            # 全局并发准入
            if queue in saturated or inflight[queue] >= cap[queue]:
                saturated.add(queue)
                ROLLBACK_DISPATCH(user_id, file_id)  # 文件原样放回队首
                skipped.add(user_id)                 # 队首指向满队列,本轮搁置该用户
                continue

            try:
                with tenant_context(payload.tenant_id):
                    parse_knowledge_file_celery.apply_async(
                        args=[file_id, payload.preview_cache_key, payload.callback_url],
                        queue=queue)
            except Exception:
                ROLLBACK_DISPATCH(user_id, file_id)  # 投递失败,回滚(计数器未动)
                skipped.add(user_id); continue

            CONFIRM_DISPATCH(file_id, queue)          # 原子:记队列 + INCR + 删 payload
            inflight[queue] += 1                      # 同步本地快照,供后续判满
            share[user_id] += 1                       # 该用户份额 +1,下次选择自然轮到别人
    finally:
        release_dispatch_lock(token)
```

**要点**

- **加权最少在飞优先**:每次只派 1 份,给当前 `share/weight` 最小的用户;派完它份额 +1,下一份自然落到别人头上。等权重时各用户在飞数被持续拉平,实现等额公平;`weight_for` 大的用户(`user_overrides`)维持成比例的更高份额。
- **无 per-user 在飞上限**:用户能拿多少份只取决于"填到 cap 前轮到它几次",示例里 A=9、B=9。
- **释放空位的去向(D3)**:某文件完成 → 该用户份额下降 → 下一轮它成为最小份额者,空位优先回补给它;若是别的用户完成,则补给那个掉下来的用户。**不会出现"任何空位都被排队最多的 A 抢走"**。
- **满队列回滚 + skip 用户**:用户队列 FIFO,队首文件指向已满队列时无法跳过它取后面的文件,故本轮搁置该用户——既避免乱序,又防止对同一文件反复 RPOP/回滚死循环(单轮对单用户最多回滚 1 次)。
- **OCR / 非 OCR 独立**:两条队列各有 `cap`,一条满了另一条仍可继续填,互不挤占。

### 7.2 端到端时序(对应 §1 示例:A/B/C = 10/50/2,cap=20)

```
三用户上传 → 各文件 enqueue(入虚拟队列) + trigger_dispatch_task.delay()
  (大量 trigger 被 dispatch_lock NX 串行化,只要 1 次拿到锁即可)

拿到锁的调度轮(权重均为 1,选 share 最小者,每次派 1):
  share 全 0 → 依次拉平: A,B,C,A,B,C,...  每人 +1
  C 在 share=2 时队列取空(只有 2 份)→ 之后只在 A、B 间拉平
  填到 inflight=20: A=9 B=9 C=2 → cap 命中 → 退出
  → 打满 20 ✅;队列剩余 A=1 B=41

稳态(始终维持 20 在飞):
  - A 的某文件完成 → A share 9→8 → 下轮 A 最小 → 空位补回 A(A 重回 9)
  - B 的某文件完成 → B share 9→8 → 下轮 B 最小 → 空位补回 B(B 重回 9)
  → A/B 份额始终被拉平在 9/9,谁完成谁补位,不会让 A 独占空位(D3)
```

### 7.3 触发链路(不变)

入队触发 + 完成触发(`finally` 内 complete 后 `trigger_dispatch_task.delay()`,[file_worker.py:320](../../../src/backend/bisheng/worker/knowledge/file_worker.py#L320))+ Beat 30s 兜底,三者共用同一 `run_dispatch_round`,由 `dispatch_lock` 串行。

---

## 8. 一致性、边界与对账

| 场景 | 处理 |
|------|------|
| apply_async 成功、CONFIRM 前 worker 崩溃 | 计数器未 INCR → 该队列偏低 1 → 短暂过派 1;reconcile 重算纠正 |
| complete 回调丢失 | 计数器未 DECR → 偏高 → 短暂欠派;reconcile 重算纠正 |
| 文件被删除(`purge_file`) | 需 `HDEL inflight_queue file_id` + `DECR inflight_total:<queue>`(若存在映射) |
| `queue_concurrency` 配 > 实际 worker | 任务在 broker 排队,不丢;监控队列长度告警 |
| 某队列未配 `queue_concurrency` | `concurrency_for` 回退到 `per_user_pick_size`,回填有界,不会无限派发 |

**对账新增一步(权威重算计数器)**——`reconcile_file_scheduler_task` 末尾:

```python
mapping = HGETALL(inflight_queue)             # {file_id: queue}
counts = Counter(mapping.values())
for q in all_queues:
    SET inflight_total:q = counts.get(q, 0)   # 权威覆盖,消除累计漂移
# 清理 inflight_queue 中已不在任何 user inflight 集合里的孤儿 file_id
```

**向后兼容**:`fair_scheduler_enabled=false` 时整段逻辑不进入,行为与今日完全一致。

---

## 9. 改动文件清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `core/config/settings.py` | 修改 | `FairSchedulerConf`:删 `max_per_user_inflight`/`limit_for`,增 `queue_concurrency`/`per_user_pick_size`/`concurrency_for`/`weight_for` |
| `worker/knowledge/lua_scripts.py` | 修改 | `DISPATCH_ONE` 删除 limit 检查;新增 `CONFIRM_DISPATCH`;`COMPLETE_FILE` 增 DECR/HDEL |
| `worker/knowledge/scheduler.py` | 修改 | `run_dispatch_round` 改"加权最少在飞优先"回填;`dispatch_one` 去掉 limit 参数;新增 `confirm_dispatch()`;`reconcile` 末尾重算计数;`purge_file` 增计数器清理 |
| `config.yaml` | 修改 | `fair_scheduler` 节:`queue_concurrency` + `per_user_pick_size` + `user_overrides` 示例与注释 |
| `test/knowledge/test_file_scheduler_dispatch.py` | 修改/新增 | 覆盖 §1 示例(10/50/2→A9B9C2)、全局上限、满队列回滚不死循环、OCR 双队列独立 |
| `test/knowledge/test_file_scheduler_reconcile.py` | 修改 | 覆盖计数器重算自愈 |

---

## 10. 验收标准(AC)

- **AC1**:`queue_concurrency.knowledge_celery=20`,单用户上传 ≥20 份非 OCR 文件 → 稳态在飞 = 20。
- **AC2**:A/B/C 各排队 10/50/2,cap=20 → 稳态在飞 A=9、B=9、C=2(允许因 Set 无序导致 A/B 差 ±1)。
- **AC3**:OCR + 非 OCR 混合 → knowledge_celery ≤20、ocr_celery ≤5,互不挤占。
- **AC4**:满队列时,队首指向满队列的用户单轮最多回滚 1 次,无死循环。
- **AC5**:手动篡改 `inflight_total` 后,一次 reconcile 恢复为 `inflight_queue` 真实值。
- **AC6**:`fair_scheduler_enabled=false` → 行为与改动前一致(回归)。
- **AC7(D3)**:A 排队 100、B 排队 50,cap=20,稳态各占约 10 在飞;**只让 B 的文件完成**,释放的空位回补给 B(B 重回 10),不会被 A 抢成 A=11/B=9。
- **AC8(权重)**:`user_overrides={"1":3}`,用户 1 与用户 2 同时排队充足,cap=20 → 稳态在飞约 15(用户1)∶5(用户2)≈ 3∶1。

---

## 11. 决策记录(已确认 2026-06-05)

- **D1 ✅ — 配置改名,不兼容旧 key**:删除 `max_per_user_inflight`;新增 `queue_concurrency`(全局并发上限)+ `per_user_pick_size`(公平权重,默认 1)+ 保留 `user_overrides`(如 `{"1": 3}` 让用户 1 维持约 3 倍在飞份额)。无需兼容旧 key。

- **D2 ✅ — 静态配置**:`queue_concurrency` 手工配置,接受"改 `-c`/扩缩容需手动同步"。后续方案2 可演进为心跳自动上报,`concurrency_for` 接口不变。

- **D3 ✅ — 公平由"加权最少在飞优先"保证**:释放出的空位永远补给**当前份额最少**的用户(选择键 `share/weight`),因此**不会出现"任何空位都被排队最多的用户 A 抢走"**。A(100 份)与 B(50 份)会被持续拉平到各占约 cap/2 的在飞份额,B 不会被压在 A 后面饿等。这是对 D3 的核心实现机制(见 §3、§7.1)。

- **D4 ✅ — 计数器建议值 + reconcile 自愈**:接受瞬时 cap±N 偏差。

- **D5 ✅ — `active_users` 保持 Redis Set**:`SMEMBERS` 无序仅影响"份额相同用户之间"的先后(平局),不影响整体公平(由 D3 的 share 比较保证)。接受,不引入有序结构。
