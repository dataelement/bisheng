"""Lua scripts for the file parse scheduler.

All scripts use the literal hash tag ``{bisheng_fs}`` so that every key
they touch lands in a single Redis Cluster slot. The prefix is hard-coded
on purpose — it must not be parameterized.
"""

ENQUEUE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]
local preview_cache_key = ARGV[2]
local callback_url = ARGV[3]
local file_ext = ARGV[4]
local payload_ttl = tonumber(ARGV[5])
local tenant_id = ARGV[6]
local idempotency_key = ARGV[7]
local file_change_request_id = ARGV[8]
local file_change_execution_token = ARGV[9]
local identity = idempotency_key
if identity == '' then
    identity = 'file:' .. file_id
end

local scheduled_identity = prefix .. 'scheduled_identity'
local inflight_identity = prefix .. 'inflight_identity'
local file_identity = prefix .. 'file_identity'
local identity_file = redis.call('HGET', scheduled_identity, identity)
if not identity_file then
    identity_file = redis.call('HGET', inflight_identity, identity)
end
if identity_file then
    if identity_file == file_id then
        return 0
    end
    return -2
end
local active_identity = redis.call('HGET', file_identity, file_id)
if active_identity then
    local active_file = redis.call('HGET', scheduled_identity, active_identity)
    if not active_file then
        active_file = redis.call('HGET', inflight_identity, active_identity)
    end
    if active_file then
        if active_identity == identity then
            return 0
        end
        return -1
    end
    redis.call('HDEL', file_identity, file_id)
end

redis.call('LPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('HSET',  prefix .. 'payload:' .. file_id,
    'preview_cache_key', preview_cache_key,
    'callback_url',      callback_url,
    'user_id',           user_id,
    'file_ext',          file_ext,
    'tenant_id',         tenant_id,
    'idempotency_key',   idempotency_key)
if file_change_request_id ~= '' then
    redis.call('HSET', prefix .. 'payload:' .. file_id,
        'file_change_request_id', file_change_request_id,
        'file_change_execution_token', file_change_execution_token)
end
redis.call('EXPIRE', prefix .. 'payload:' .. file_id, payload_ttl)
redis.call('HSET', scheduled_identity, identity, file_id)
redis.call('HSET', file_identity, file_id, identity)
redis.call('SADD', prefix .. 'active_users', user_id)
redis.call('SADD', prefix .. 'inflight_users', user_id)
return 1
"""

DISPATCH_ONE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]

local inflight_key = prefix .. 'inflight:' .. user_id
local queue_key    = prefix .. 'queue:'    .. user_id
local active_key   = prefix .. 'active_users'

-- No per-user in-flight ceiling: the only hard limit is the per-queue global
-- concurrency cap, enforced by the Python dispatch round (which knows the
-- target queue after reading the payload). This script just pops one file.
local file_id = redis.call('RPOP', queue_key)
if not file_id then
    redis.call('SREM', active_key, user_id)
    return nil
end

if redis.call('LLEN', queue_key) == 0 then
    redis.call('SREM', active_key, user_id)
end

redis.call('SADD', inflight_key, file_id)
local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
if not identity then
    identity = redis.call('HGET', prefix .. 'payload:' .. file_id, 'idempotency_key')
    if not identity or identity == '' then
        identity = 'file:' .. file_id
    end
    redis.call('HSET', prefix .. 'file_identity', file_id, identity)
end
redis.call('HDEL', prefix .. 'scheduled_identity', identity)
redis.call('HSET', prefix .. 'inflight_identity', identity, file_id)
redis.call('SADD', prefix .. 'inflight_users', user_id)
return file_id
"""

CONFIRM_DISPATCH = r"""
local prefix = '{bisheng_fs}:'
local file_id = KEYS[1]
local queue   = ARGV[1]

-- Atomically: remember which queue the file went to, bump that queue's global
-- in-flight counter, and drop the now-consumed payload. Called only AFTER
-- apply_async succeeds, so the INCR pairs exactly with COMPLETE_FILE's DECR.
local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
if not identity or redis.call('HGET', prefix .. 'inflight_identity', identity) ~= file_id then
    return 0
end
if redis.call('HSETNX', prefix .. 'inflight_queue', file_id, queue) == 0 then
    return 0
end
redis.call('INCR', prefix .. 'inflight_total:' .. queue)
redis.call('DEL',  prefix .. 'payload:' .. file_id)
return 1
"""

ROLLBACK_DISPATCH = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

if redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id) == 0 then
    return 0
end
local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
if identity then
    redis.call('HDEL', prefix .. 'inflight_identity', identity)
    redis.call('HSET', prefix .. 'scheduled_identity', identity, file_id)
end
-- RPUSH puts the file back at the tail, which is the very next position RPOP
-- will read — preserves FIFO retry order, NOT a deprioritization.
redis.call('RPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('SADD',  prefix .. 'active_users', user_id)
return 1
"""

DROP_DISPATCH = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

-- Discard a ghost in-flight entry (payload lost / DB terminal-or-deleted) that
-- was RPOP'd by DISPATCH_ONE but must NOT be parsed. Unlike ROLLBACK_DISPATCH
-- this does NOT RPUSH the file back — re-queuing a payload-less file is exactly
-- what turns it into a poison pill. The file was never confirmed, so the queue
-- counter was never bumped and must not be touched here.
local removed = redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
redis.call('DEL',  prefix .. 'payload:' .. file_id)
if removed == 1 then
    local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
    if identity then
        redis.call('HDEL', prefix .. 'inflight_identity', identity)
        redis.call('HDEL', prefix .. 'file_identity', file_id)
    end
end
if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
end
return 1
"""

COMPLETE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

local removed = redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)

-- Return the file's slot to whichever queue it was dispatched on.
if removed == 1 then
    local queue = redis.call('HGET', prefix .. 'inflight_queue', file_id)
    if queue then
        redis.call('DECR', prefix .. 'inflight_total:' .. queue)
        redis.call('HDEL', prefix .. 'inflight_queue', file_id)
    end
    local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
    if identity then
        redis.call('HDEL', prefix .. 'inflight_identity', identity)
        redis.call('HDEL', prefix .. 'scheduled_identity', identity)
        redis.call('HDEL', prefix .. 'file_identity', file_id)
    end
end

if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
end
return 1
"""

REMOVE_QUEUED = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]
local removed = redis.call('LREM', prefix .. 'queue:' .. user_id, 0, file_id)
if removed > 0 then
    local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
    if identity and not redis.call('HGET', prefix .. 'inflight_identity', identity) then
        redis.call('HDEL', prefix .. 'scheduled_identity', identity)
        redis.call('HDEL', prefix .. 'file_identity', file_id)
    end
end
if redis.call('LLEN', prefix .. 'queue:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'active_users', user_id)
end
return removed
"""

PURGE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('LREM', prefix .. 'queue:' .. user_id, 0, file_id)
redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
redis.call('DEL', prefix .. 'payload:' .. file_id)
local queue = redis.call('HGET', prefix .. 'inflight_queue', file_id)
if queue then
    redis.call('DECR', prefix .. 'inflight_total:' .. queue)
    redis.call('HDEL', prefix .. 'inflight_queue', file_id)
end
local identity = redis.call('HGET', prefix .. 'file_identity', file_id)
if identity then
    redis.call('HDEL', prefix .. 'scheduled_identity', identity)
    redis.call('HDEL', prefix .. 'inflight_identity', identity)
    redis.call('HDEL', prefix .. 'file_identity', file_id)
end
if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
end
if redis.call('LLEN', prefix .. 'queue:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'active_users', user_id)
end
return 1
"""

RELEASE_LOCK = r"""
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

REFRESH_LOCK = r"""
-- Extend a lock's TTL only if the caller still owns it (token match). Used by
-- the parse heartbeat to keep a long-running parse's lock alive without ever
-- stealing a lock that a different worker now holds.
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
