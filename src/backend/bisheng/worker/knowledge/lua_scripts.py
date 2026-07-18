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

redis.call('LPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('HSET',  prefix .. 'payload:' .. file_id,
    'preview_cache_key', preview_cache_key,
    'callback_url',      callback_url,
    'user_id',           user_id,
    'file_ext',          file_ext,
    'tenant_id',         tenant_id)
redis.call('EXPIRE', prefix .. 'payload:' .. file_id, payload_ttl)
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
redis.call('HSET', prefix .. 'inflight_queue', file_id, queue)
redis.call('INCR', prefix .. 'inflight_total:' .. queue)
redis.call('DEL',  prefix .. 'payload:' .. file_id)
return 1
"""

ROLLBACK_DISPATCH = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
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
redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
redis.call('DEL',  prefix .. 'payload:' .. file_id)
if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
end
return 1
"""

COMPLETE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)

-- Return the file's slot to whichever queue it was dispatched on.
local queue = redis.call('HGET', prefix .. 'inflight_queue', file_id)
if queue then
    redis.call('DECR', prefix .. 'inflight_total:' .. queue)
    redis.call('HDEL', prefix .. 'inflight_queue', file_id)
end

if redis.call('SCARD', prefix .. 'inflight:' .. user_id) == 0 then
    redis.call('SREM', prefix .. 'inflight_users', user_id)
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
