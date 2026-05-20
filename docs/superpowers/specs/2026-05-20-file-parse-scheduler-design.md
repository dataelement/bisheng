# 文件解析调度优化设计方案

**日期**：2026-05-20  
**需求**：① OCR 调用并发独立控制；② 按用户公平调度（一人一个文件）

---

## 1. 现状

```
文件上传 → MinIO → DB(WAITING) → parse_knowledge_file_celery.delay(file_id, ...)
                                              ↓
                                   knowledge_celery 队列（FIFO）
                                              ↓
                            20 个线程工作者（-c 20 -P threads）
                                              ↓
                            KnowledgeFilePipeline
                              ├─ OCR loader（ETL4LM / Mineru / PaddleOCR）
                              └─ Transformers → Milvus + ES
```

**现存问题：**

- 20 个 worker 可同时调 OCR 服务，OCR 服务无独立并发上限。
- 队列 FIFO：用户 A 上传 100 个文件，用户 B 的文件排在最后，全部等待 A 处理完才能开始。

---

## 2. 目标与约束

- **需求一**：OCR 类文件（PDF + 图片，当 OCR 服务已配置时）和非 OCR 类文件使用独立 worker 池，各自独立控制并发。
- **需求二**：多用户并发上传时，按用户轮询公平调度；每用户最大飞行中文件数（`max_per_user_inflight`）可配置，支持按用户覆盖。
- **约束**：两个需求均通过 feature flag 独立开关，关闭时行为与现在完全一致（向后兼容）。
- **约束**：不能有数据丢失、数据不一致、重复处理。

---

## 3. 整体架构

```
文件上传
  │
  ▼
[is fair_scheduler.enabled?]
  │ YES                          NO
  ▼                              ▼
enqueue_to_redis_vqueue      直接 apply_async（现有逻辑）
  │
  ├─ 立即触发 dispatch（事件驱动）
  │
  ▼
FileScheduler（Celery Beat 兜底 + 事件触发）
  ├─ 获取分布式锁
  ├─ 轮询 active_users（round-robin）
  └─ dispatch_one（Lua 原子）
       │
       ├─ [is ocr_queue.enabled?]
       │   YES → 判断文件类型 → ocr_celery（OCR）/ knowledge_celery（非OCR）
       │   NO  → knowledge_celery（现有队列）
       │
       ▼
    apply_async(queue=...)
       │ 失败
       └─ rollback_dispatch（Lua 原子）

parse_knowledge_file_celery（acks_late=True）
  └─ finally → complete_file(user_id, file_id)（Lua 原子）→ 触发下次 dispatch
```

---

## 4. 需求一：OCR 队列分流

### 4.1 路由判断

在 dispatch 时（或直接上传场景下直接 delay 时），调用以下函数确定目标队列：

```
needs_ocr_queue(file_ext):
  ocr_configured = etl4lm.url OR mineru.url OR paddle_ocr.url
  if file_ext in {png, jpg, jpeg, bmp}: return True   # 图片必须走 OCR
  if file_ext == pdf: return ocr_configured             # PDF 视配置决定
  return False                                          # 其他文件走普通队列
```

此判断完全基于配置，在 dispatch 前可确定，无需读 MinIO/DB。

### 4.2 Celery 队列路由

新增两条路由（在 `CeleryConf.validate` 中追加）：

```python
"bisheng.worker.knowledge.file_worker.parse_knowledge_file_celery": {
    # 不设静态路由；由 apply_async(queue=...) 动态决定
}
```

实际路由通过 `apply_async(args=[...], queue='ocr_celery' or 'knowledge_celery')` 传入，无需修改任务函数。

### 4.3 Worker 启动配置

通过环境变量控制 worker 模式：

| 模式 | 监听队列 | 说明 |
|------|---------|------|
| `all`（默认） | `ocr_celery,knowledge_celery,workflow_celery,celery` | 兼容模式，与现有行为一致 |
| `ocr` | `ocr_celery` | 专属 OCR worker，concurrency = ocr_concurrency |
| `file` | `knowledge_celery,workflow_celery,celery` | 非 OCR worker（现有队列） |

`run_celery.py` 读取环境变量 `BISHENG_CELERY_MODE` 和 `BISHENG_CELERY_CONCURRENCY`。

**OCR 并发 = OCR worker 进程的 `--concurrency` 数量**，无需额外信号量。

### 4.4 backward compatibility

若 `ocr_queue_enabled = false`：所有任务仍路由到 `knowledge_celery`，行为不变。  
若 `ocr_queue_enabled = true` 但只启动一个 worker 监听所有队列：依然工作，只是 OCR 没有独立隔离。

---

## 5. 需求二：公平调度器

### 5.1 Redis 数据模型

所有 key 使用固定 hash tag `{bisheng_fs}` 作为前缀（Redis Cluster 兼容）：

| Key | 类型 | 内容 | 生命周期 |
|-----|------|------|---------|
| `{bisheng_fs}:queue:{user_id}` | List | `file_id`（字符串）| enqueue → dispatch |
| `{bisheng_fs}:payload:{file_id}` | Hash | `preview_cache_key`, `callback_url`, `user_id`, `file_ext` | enqueue → dispatch成功 |
| `{bisheng_fs}:inflight:{user_id}` | Set | `file_id`（字符串）| dispatch → complete |
| `{bisheng_fs}:active_users` | Set | `user_id`（字符串）| enqueue → queue清空 |
| `{bisheng_fs}:dispatch_lock` | String（NX EX）| `{worker_id}` | 调度期间持有 |

**Hash tag 说明**：Redis Cluster 以 key 中 `{}` 内的内容决定 slot。所有调度器 key 共用 `{bisheng_fs}` 这个 hash tag，确保全部落在同一 slot，Lua 脚本跨 key 原子操作在单节点、哨兵、集群三种模式下均可正常执行。代价是这些 key 集中在一个 Cluster 节点，但调度器数据量小、操作频率低，这是可接受的。

**选择 Set（存 file_id）而非 Counter（INCR/DECR）的理由**：  
Counter 在 worker 崩溃后无法对账（只知道数字，不知道是哪些文件）；  
Set 存具体 file_id，可与 DB 中文件状态逐一比对，是对账的基础。

### 5.2 Lua 脚本（保证原子性）

所有涉及多 key 的操作均通过 Lua 执行，Redis 单线程保证原子性。

---

#### Lua-1：enqueue_file

**触发时机**：文件上传入库后，替代原来的 `parse_knowledge_file_celery.delay()`

```lua
-- KEYS[1] = user_id
-- ARGV[1] = file_id, ARGV[2] = preview_cache_key, ARGV[3] = callback_url, ARGV[4] = file_ext
local prefix = 'bisheng:fs:'
local user_id = KEYS[1]

redis.call('LPUSH', prefix .. 'queue:' .. user_id, ARGV[1])
redis.call('HSET',  prefix .. 'payload:' .. ARGV[1],
    'preview_cache_key', ARGV[2],
    'callback_url',      ARGV[3],
    'user_id',           user_id,
    'file_ext',          ARGV[4])
redis.call('EXPIRE', prefix .. 'payload:' .. ARGV[1], 14400)  -- 4h TTL，防止 Redis eviction 导致孤儿 key
redis.call('SADD',  prefix .. 'active_users', user_id)
return 1
```

**原子性保证**：所有操作在同一 Lua 脚本中，Redis 不会在中间插入其他命令。  
**崩溃场景**：若 Redis 在脚本执行中宕机，脚本不会部分执行（Redis 要么执行完整脚本，要么不执行）。  
**TTL 说明**：payload key 设置 4h TTL，即使 dispatch 后的 DEL 调用失败，最终也会自动清理；若 Redis maxmemory-policy 为 allkeys-lru 导致提前淘汰，对账任务在 Case 2 中会从 DB 重建 payload（`preview_cache_key`/`callback_url` 在此场景下可接受为空，核心解析逻辑不依赖它们）。

---

#### Lua-2：dispatch_one

**触发时机**：调度器为某个 user_id 尝试派发一个文件

```lua
-- KEYS[1] = user_id
-- ARGV[1] = max_inflight_limit
local prefix  = 'bisheng:fs:'
local user_id = KEYS[1]
local limit   = tonumber(ARGV[1])

local inflight_key = prefix .. 'inflight:' .. user_id
local queue_key    = prefix .. 'queue:'    .. user_id
local active_key   = prefix .. 'active_users'

-- 检查是否超过用户并发限制（check + pop 原子，不会超发）
local inflight_count = redis.call('SCARD', inflight_key)
if inflight_count >= limit then
    return nil  -- 用户已达上限，跳过
end

-- 出队（RPOP = 取最早入队的文件，FIFO）
local file_id = redis.call('RPOP', queue_key)
if not file_id then
    redis.call('SREM', active_key, user_id)  -- 队列已空，清除用户
    return nil
end

-- 若队列已空，从 active_users 移除（无更多文件需调度）
if redis.call('LLEN', queue_key) == 0 then
    redis.call('SREM', active_key, user_id)
end

-- 记录飞行中
redis.call('SADD', inflight_key, file_id)

return file_id
```

**关键设计**：inflight 检查和 RPOP 在同一 Lua 脚本中，即使两个调度器并发，  
第二个执行 Lua 时 inflight 已经是 1，会直接返回 nil，**不会超发**。

---

#### Lua-3：rollback_dispatch

**触发时机**：dispatch_one 成功（文件已从队列弹出、已进 inflight），但后续 `apply_async` 失败

```lua
-- KEYS[1] = user_id
-- ARGV[1] = file_id
local prefix  = 'bisheng:fs:'
local user_id = KEYS[1]
local file_id = ARGV[1]

-- 从 inflight 移除
redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
-- 放回队列头部（RPUSH = 放到右端，下次 RPOP 优先取出）
redis.call('RPUSH', prefix .. 'queue:' .. user_id, file_id)
-- 确保 user 在 active_users 中（可能已被 dispatch_one 移除）
redis.call('SADD',  prefix .. 'active_users', user_id)
return 1
```

---

#### Lua-4：complete_file

**触发时机**：Celery 任务 `finally` 块（无论成功/失败/异常）

```lua
-- KEYS[1] = user_id
-- ARGV[1] = file_id
redis.call('SREM', 'bisheng:fs:inflight:' .. KEYS[1], ARGV[1])
return 1
```

**注意**：不在此 Lua 中加回 `active_users`。`active_users` 仅由 `enqueue_file` 写入，  
`dispatch_one` 在队列为空时移除。完成时 user 是否有更多文件由队列状态决定，  
若队列非空，`dispatch_one` 在上次出队时已保留了 `active_users` 中的用户。

---

### 5.3 调度器算法

```
function run_dispatch_round():
    # 1. 获取分布式锁（防止并发调度）
    lock_acquired = SET(dispatch_lock, worker_id, NX, EX=lock_ttl)
    if not lock_acquired:
        return  # 上一轮还在跑，本次跳过

    try:
        # 2. 获取所有有待处理文件的用户
        active_users = SMEMBERS(active_users_key)

        # 3. 轮询每个用户，为其 dispatch 一个文件
        for user_id in active_users:
            limit = get_user_limit(user_id)  # 配置中读取，支持 per-user override
            file_id = lua_dispatch_one(user_id, limit)

            if file_id is None:
                continue  # 用户已达上限或队列为空

            # 4. 读取 payload（只有被 dispatch 的那个任务持有 file_id）
            payload = HGETALL(payload_key(file_id))
            if not payload:
                # payload 丢失（异常情况），通知对账任务处理
                lua_rollback_dispatch(user_id, file_id)
                log.error(...)
                continue

            # 5. 决定目标队列
            if ocr_queue_enabled and needs_ocr_queue(payload['file_ext']):
                queue = 'ocr_celery'
            else:
                queue = 'knowledge_celery'  # 非 OCR 或 feature flag 关闭时用现有队列

            # 6. 派发到 Celery
            try:
                parse_knowledge_file_celery.apply_async(
                    args=[int(file_id), payload.get('preview_cache_key'), payload.get('callback_url')],
                    queue=queue
                )
                # 7. dispatch 成功后删除 payload（不再需要）
                DEL(payload_key(file_id))
            except Exception:
                # 8. apply_async 失败：回滚 Redis 状态
                lua_rollback_dispatch(user_id, file_id)
                log.error(f"dispatch failed for file_id={file_id}, rolled back")
    finally:
        # 9. 释放锁（仅释放自己持有的锁）
        lua_release_lock(worker_id)
```

**分布式锁的 lock_ttl**：建议设为 `dispatch_interval_seconds × 0.8`（如 24s），  
短于触发间隔，确保即使调度器崩溃，锁也会在下一次触发前自动过期。

---

### 5.4 调度触发机制

**主动触发（事件驱动，低延迟）**：

1. **上传触发**：`enqueue_file` Lua 执行成功后，立即调用 `trigger_dispatch_task.delay()`（一个轻量 Celery 任务，只执行一轮调度）。
2. **完成触发**：Celery 任务 `finally` 块中，`complete_file` Lua 执行后，调用 `trigger_dispatch_task.delay(user_id=...)`（只针对该用户调度）。

**兜底触发（Celery Beat，防漏）**：

```yaml
beat_schedule:
  file_scheduler_dispatch:
    task: bisheng.worker.knowledge.scheduler.dispatch_round
    schedule: 30.0  # 每 30 秒
```

Beat 触发是最后的安全网，处理事件驱动触发被漏掉的边界情况（服务重启、异常等）。

---

### 5.5 Celery 任务修改（complete_file 回调）

`file_worker.py` 中 `parse_knowledge_file_celery` 的 `finally` 块新增：

```python
finally:
    db_file = KnowledgeFileDao.get_file_by_ids([file_id])
    # ... 现有逻辑不变 ...

    # 新增：通知调度器此文件已完成
    if settings.file_scheduler.fair_scheduler_enabled and db_file:
        user_id = db_file[0].user_id
        file_scheduler.complete_file(user_id=str(user_id), file_id=str(file_id))
        trigger_dispatch_task.delay(user_id=str(user_id))
```

---

### 5.6 重试场景

**重试入口**（代码中存在三处调用）：

- `knowledge_utils.process_rebuild_file` — 用户修改切割规则后重新解析
- `knowledge_utils.process_retry_files` — 用户对失败文件批量重试
- `knowledge_space_service` — 知识空间侧的重试

**重试与首次上传的关键区别**：重试需要先清理旧向量数据（`delete_knowledge_file_vectors`），才能重新解析。清理步骤本身不涉及 OCR，耗时短。

**当 `fair_scheduler_enabled = true` 时的重试流程**：

```
retry_knowledge_file_celery（仍运行于 knowledge_celery）
  │
  ├─ Step 1: delete_knowledge_file_vectors（清理旧向量，快速）
  │           失败 → 标记 FAILED，返回
  │
  ├─ Step 2: 重置 DB 状态为 WAITING
  │
  └─ Step 3: 调用 enqueue_file Lua（file_id 重新入虚拟队列）
              → trigger_dispatch_task.delay()（立即触发调度）
              → 后续走与首次上传完全相同的调度路径
```

`retry_knowledge_file_celery` 本身不再直接调用 `_parse_knowledge_file`，而是把清理完的文件交还给调度器。这样：

- **并发控制**：重试的文件与正常上传的文件共享同一套调度器，受 `max_per_user_inflight` 约束，用户一次重试 100 个也不会冲垮 OCR 服务
- **OCR 分流**：重试文件经过调度器 dispatch 时同样判断文件类型，路由到正确队列
- **公平性**：多用户同时重试，与首次上传的文件在同一个 `active_users` 轮询中公平竞争

**当 `fair_scheduler_enabled = false` 时**：行为与现在完全一致，`retry_knowledge_file_celery` 直接调用 `_parse_knowledge_file`，不变。

**`retry_knowledge_file_celery` 本身不需要 `complete_file` 回调**：因为在新流程中它只做清理+入队，不做解析。解析由调度器派发的 `parse_knowledge_file_celery` 完成，`complete_file` 在后者的 `finally` 中调用。

---

### 5.7 对账任务（兜底数据修复）

每 5 分钟运行一次（Celery Beat），对账 Redis 状态与 DB 状态：

```
function reconcile():
    # Case 1：inflight 中的文件在 DB 中已完成（complete_file 回调丢失）
    for user_id in all_users_with_inflight():
        for file_id in SMEMBERS(inflight_key(user_id)):
            db_status = KnowledgeFileDao.get_status(file_id)
            if db_status in {SUCCESS, FAILED, VIOLATION}:
                lua_complete_file(user_id, file_id)  # 清除泄漏的 inflight 记录
                log.warning(f"reconcile: leaked inflight entry cleaned for file_id={file_id}")

    # Case 2：inflight 中的文件在 DB 中仍是 WAITING（apply_async 曾失败且 rollback 也失败）
    for user_id in all_users_with_inflight():
        for file_id in SMEMBERS(inflight_key(user_id)):
            db_status = KnowledgeFileDao.get_status(file_id)
            if db_status == WAITING:
                # 文件从未被 Celery 接收到，需重新入队
                lua_complete_file(user_id, file_id)
                lua_enqueue_file(user_id, file_id, ...)  # payload 从 DB 重建
                log.error(f"reconcile: re-enqueued orphaned file_id={file_id}")

    # Case 3：inflight 中的文件 PROCESSING 时间超过 inflight_ttl（worker 已死，任务消失）
    for user_id in all_users_with_inflight():
        for file_id in SMEMBERS(inflight_key(user_id)):
            db_file = KnowledgeFileDao.get_file_by_ids([file_id])
            if not db_file:
                lua_complete_file(user_id, file_id)  # 文件已删，清理残留
                continue
            if db_file.status == PROCESSING and (now - db_file.update_time) > inflight_ttl:
                # 超时且 DB 仍在 PROCESSING：认为 worker 已丢失此任务
                lua_complete_file(user_id, file_id)
                # 重置 DB 状态，触发重新解析（复用 retry 逻辑）
                KnowledgeFileDao.update_file_status([file_id], KnowledgeFileStatus.WAITING)
                lua_enqueue_file(user_id, file_id, preview_cache_key='', callback_url='', file_ext=db_file.file_ext)
                log.error(f"reconcile: timed-out file_id={file_id} re-enqueued")

    # Case 4：active_users 中存在但 queue 已空的用户
    for user_id in SMEMBERS(active_users_key):
        if LLEN(queue_key(user_id)) == 0 and SCARD(inflight_key(user_id)) == 0:
            SREM(active_users_key, user_id)
```

---

## 6. 风险矩阵（数据一致性全面审查）

### 6.0 上传进程与调度器进程并发

上传进程（`enqueue_file` Lua）和调度器进程（`dispatch_one` Lua）同时运行时的安全性分析：

| 场景 | 是否安全 | 原因 |
|------|---------|------|
| 两个 Lua 脚本同时发往 Redis | **安全** | Redis 单线程：Lua 脚本串行执行，不会交错 |
| 调度器 SMEMBERS 后、循环结束前，新用户入队 | 本轮调度不感知，无数据丢失 | 新用户的文件安全在队列中；上传触发的 trigger_dispatch 或 Beat 兜底（≤30s）处理 |
| dispatch_one 刚 SREM 出 active_users，上传 SADD 重新加入 | **安全** | 两个 Lua 均原子；最终 active_users 正确包含该用户；下轮调度正常处理 |
| 调度器和上传同时操作同一 user 的队列 | **安全** | LPUSH（入队）和 RPOP（出队）作用于队列两端，无竞争 |

**结论**：上传进程与调度器进程之间不存在数据一致性风险。调度器的 SMEMBERS 是非原子快照，仅引入最多 30s 的调度延迟（由事件驱动触发消除到近零），不影响数据正确性。

---

### 6.1 enqueue 阶段

| 风险场景 | 影响 | 缓解措施 |
|---------|------|---------|
| Redis 不可用，enqueue Lua 失败 | 文件入 DB（WAITING）但不在虚拟队列 | 对账任务：扫描 DB 中 WAITING 且不在任何队列中的文件，重新入队 |
| Lua 脚本部分执行 | 不可能：Lua 在 Redis 中原子执行 | N/A |
| enqueue 成功，但 trigger_dispatch.delay() 失败 | 文件在队列中，延迟至 Beat（≤30s）才被调度 | 可接受；Beat 是兜底 |

### 6.2 dispatch 阶段

| 风险场景 | 影响 | 缓解措施 |
|---------|------|---------|
| dispatch_one Lua 成功（RPOP + SADD inflight），apply_async 失败 | 文件离开队列，进入 inflight，但 Celery 未收到 | rollback_dispatch Lua 将文件放回队列、移出 inflight；若 rollback 也失败，对账任务修复 |
| rollback_dispatch Lua 失败（Redis 故障） | 文件在 inflight 但 DB 仍 WAITING | 对账任务（Case 2）：WAITING + inflight → 重新入队 |
| 两个调度器并发 | 可能双重 dispatch | 分布式锁（主防）+ dispatch_one Lua inflight 检查（副防，即使锁失效也不超发） |
| payload 在 dispatch 后、delete 前被其他进程读取 | 不可能：file_id 已进 inflight，只有当前 dispatch 持有 | N/A |
| payload key 意外删除（Redis eviction） | apply_async 收到空 payload | maxmemory-policy 设为 allkeys-lru 时有风险；解决：对 payload key 设置足够长的 TTL（如 2h），同时对账任务检测空 payload 并从 DB 重建 |

### 6.3 执行阶段（Celery task）

| 风险场景 | 影响 | 缓解措施 |
|---------|------|---------|
| Worker 在处理中崩溃 | 文件在 inflight，DB 在 PROCESSING；Celery acks_late 自动重新入 Celery 队列 | 文件继续被处理（正确）；inflight 在任务重试完成后由 finally 清除 |
| Worker 崩溃且 Celery 也无法重新投递（broker 故障） | 文件在 inflight，DB 在 PROCESSING，无人处理 | 对账任务（Case 3）：PROCESSING 超时 → 移出 inflight，重新入虚拟队列 |
| complete_file 在 finally 中抛异常 | file_id 留在 inflight，占用用户配额 | 对账任务（Case 1）：DB 已 SUCCESS/FAILED，inflight 仍有 → 清除 |
| 同一文件被处理两次（重复） | 数据写入两遍 | dispatch_one Lua 保证每个 file_id 只出现在一个用户的 inflight 中，且队列 RPOP 保证 file_id 只被弹出一次；不会重复派发 |
| acks_late 导致任务重新投递，complete_file 已被调用一次 | inflight 第一次 complete 后已清除；第二次任务完成时 complete 再次执行 SREM，Redis SREM 对不存在的 member 是 no-op | 安全，无副作用 |

### 6.4 complete 阶段

| 风险场景 | 影响 | 缓解措施 |
|---------|------|---------|
| complete_file 后 trigger_dispatch 失败 | 用户有更多文件但本次不触发 | Beat 兜底（≤30s） |
| complete_file 调用了但 user_id 取自已删除的 db_file（文件被删除） | user_id 为 None，Lua key 格式错误 | finally 块先判断 db_file 是否存在；若文件已删除，对账任务会清理 inflight |

### 6.5 对账任务

| 风险场景 | 影响 | 缓解措施 |
|---------|------|---------|
| 对账任务与正在处理中的任务并发 | 可能误判"处理超时"而重新入队 | 设置足够保守的超时阈值（建议 = OCR 最大 timeout × 3） |
| 对账任务本身崩溃 | 本次对账未完成 | 下次 Beat 触发时重跑；对账是幂等操作 |

### 6.6 配置与部署

| 风险场景 | 影响 | 缓解措施 |
|---------|------|---------|
| ocr_queue 开启后，没有 worker 监听 ocr_celery | 任务发到 ocr_celery 但没有 worker 消费 | 部署规范：先启动 ocr worker 再开启 flag；ocr_queue 可配为 knowledge_celery 过渡 |
| Redis 虚拟队列积压（调度器挂了，文件只进队不出） | 队列无限增长 | 监控告警：queue:{user_id} length > N；Beat 兜底确保调度器存活 |
| `max_per_user_inflight` 配置为 0（误配） | 所有用户永远不被调度 | 配置校验：`max_per_user_inflight` 必须 ≥ 1 |

---

## 7. 配置参考

```yaml
# config.yaml 新增节
knowledge_file_worker:
  # 需求一：OCR 队列分流
  ocr_queue_enabled: false          # 默认关闭，向后兼容
  ocr_queue: ocr_celery             # OCR 任务专属队列（新增）
  # 非 OCR 任务继续使用现有 knowledge_celery，无需配置

  # 需求二：公平调度器
  fair_scheduler_enabled: false     # 默认关闭，向后兼容
  fair_scheduler:
    dispatch_interval_seconds: 30   # Beat 兜底触发间隔
    dispatch_lock_ttl_seconds: 24   # 分布式锁 TTL（必须 < dispatch_interval）
    redis_key_prefix: "bisheng:fs:" # Redis key 命名空间
    max_per_user_inflight: 1        # 全局默认每用户最大并发
    user_overrides:                 # 按 user_id 覆盖（优先级 > 全局默认）
      # "123": 3
      # "456": 5
    inflight_ttl_seconds: 7200      # 对账任务判定"卡住"的超时阈值（2h）
    reconcile_interval_seconds: 300 # 对账任务触发间隔（5min）
```

**Worker 启动环境变量**：

```bash
# OCR 专属 worker（控制 OCR 并发 = 5）
BISHENG_CELERY_MODE=ocr BISHENG_CELERY_CONCURRENCY=5 python run_celery.py

# 非 OCR worker（监听现有 knowledge_celery，并发 = 15）
BISHENG_CELERY_MODE=file BISHENG_CELERY_CONCURRENCY=15 python run_celery.py

# 兼容模式（监听所有队列，适合单进程部署）
BISHENG_CELERY_MODE=all BISHENG_CELERY_CONCURRENCY=20 python run_celery.py
```

---

## 8. 改动范围

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `core/config/settings.py` | 新增 | `KnowledgeFileWorkerConf` 配置类 |
| `worker/knowledge/file_worker.py` | 修改 | `parse_*` 的 `finally` 块调用 `complete_file`；`retry_*` 改为清理后入虚拟队列 |
| `knowledge/domain/services/knowledge_utils.py` | 无需改动 | retry 入口不变，仍调 `retry_knowledge_file_celery.delay()`；逻辑变更在 task 内部 |
| `worker/knowledge/scheduler.py` | 新增 | 调度器主逻辑、Lua 脚本、对账任务 |
| `worker/knowledge/redis_ops.py` | 新增 | 封装所有 Lua 脚本调用 |
| `worker/config.py` | 修改 | 新增 `ocr_celery` 队列路由 |
| `knowledge/domain/services/knowledge_service.py` | 修改 | dispatch 入口：根据 feature flag 走虚拟队列或直接 delay |
| `run_celery.py` | 修改 | 读取 `BISHENG_CELERY_MODE` 环境变量 |
| `core/config/settings.py` 中 `CeleryConf` | 修改 | `beat_schedule` 新增调度器和对账任务 |

---

## 9. 迁移路径

1. **阶段一（仅需求一）**：开启 `ocr_queue_enabled=true`，部署两种 worker。关闭 `fair_scheduler_enabled`。验证 OCR 并发隔离效果。
2. **阶段二（加需求二）**：开启 `fair_scheduler_enabled=true`。从 `max_per_user_inflight=3` 开始（不太激进），观察稳定后调整为 1。
3. **回滚**：任何时候将对应 flag 设为 false，行为立即回退到现有逻辑。Redis 虚拟队列中的数据可由对账任务清理。
