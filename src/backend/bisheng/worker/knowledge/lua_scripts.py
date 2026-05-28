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

redis.call('LPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('HSET',  prefix .. 'payload:' .. file_id,
    'preview_cache_key', preview_cache_key,
    'callback_url',      callback_url,
    'user_id',           user_id,
    'file_ext',          file_ext)
redis.call('EXPIRE', prefix .. 'payload:' .. file_id, payload_ttl)
redis.call('SADD', prefix .. 'active_users', user_id)
redis.call('SADD', prefix .. 'inflight_users', user_id)
return 1
"""

DISPATCH_ONE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local limit = tonumber(ARGV[1])

local inflight_key = prefix .. 'inflight:' .. user_id
local queue_key    = prefix .. 'queue:'    .. user_id
local active_key   = prefix .. 'active_users'

if redis.call('SCARD', inflight_key) >= limit then
    return nil
end

local file_id = redis.call('RPOP', queue_key)
if not file_id then
    redis.call('SREM', active_key, user_id)
    return nil
end

if redis.call('LLEN', queue_key) == 0 then
    redis.call('SREM', active_key, user_id)
end

redis.call('SADD', inflight_key, file_id)
return file_id
"""

ROLLBACK_DISPATCH = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
redis.call('RPUSH', prefix .. 'queue:' .. user_id, file_id)
redis.call('SADD',  prefix .. 'active_users', user_id)
return 1
"""

COMPLETE_FILE = r"""
local prefix = '{bisheng_fs}:'
local user_id = KEYS[1]
local file_id = ARGV[1]

redis.call('SREM', prefix .. 'inflight:' .. user_id, file_id)
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
