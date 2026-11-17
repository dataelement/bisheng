-- F004 send-entry decision (design 决策 9). Two scripts in one file, split by
-- the "-- @@script <name>" marker lines; run_dispatch.py loads them.
--
-- Both scripts touch only keys that carry the hash tag {conversation_id}
-- (design K8) and use only core commands available in Redis 5.0.
-- Time is the caller's clock (ARGV now_ms), never Redis TIME, the same rule as
-- run_lease.py. The lease is valid iff status == "running" and
-- lease_until > now_ms.

-- @@script dispatch
-- KEYS[1] = bisheng:run:state:{cid}   (hash, contract in run_lease.py)
-- KEYS[2] = bisheng:run:inbox:{cid}   (list of JSON messages, oldest first)
-- ARGV[1] = mode: "submit" | "recover"  (recover = no message, only handle a lapsed lease)
-- ARGV[2] = candidate run id (used only when this call starts a run)
-- ARGV[3] = message JSON ("" in recover mode)
-- ARGV[4] = profile of the message: "direct" | "planned"
-- ARGV[5] = now_ms
-- ARGV[6] = lease_ms         lease of a run that executes right away (direct)
-- ARGV[7] = queued_lease_ms  lease of a run handed to the worker queue (planned, relay)
-- ARGV[8] = state TTL seconds
-- ARGV[9] = inbox TTL seconds
-- Returns {branch, run_id, profile, expired_run_id, inbox_length, head_json}
--   branch: "started" | "queued" | "answer" | "relay" | "idle" | "noop"
local st = redis.call('HMGET', KEYS[1], 'status', 'run_id', 'profile', 'lease_until')
local status = st[1] or 'idle'
local holder = st[2] or ''
local profile = st[3] or ''
local lease_until = tonumber(st[4] or '0') or 0
local mode = ARGV[1]
local now = tonumber(ARGV[5])
local expired = ''

local function lease_ms_for(p)
  if p == 'planned' then
    return tonumber(ARGV[7])
  end
  return tonumber(ARGV[6])
end

local function hold(run_id, p, lease_ms)
  redis.call('HSET', KEYS[1], 'status', 'running', 'run_id', run_id, 'profile', p,
    'lease_until', tostring(now + lease_ms), 'updated_at', ARGV[5])
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[8]))
end

local function push_message()
  local n = redis.call('RPUSH', KEYS[2], ARGV[3])
  redis.call('EXPIRE', KEYS[2], tonumber(ARGV[9]))
  return n
end

-- Branch 4: running but the lease lapsed -> the old run is dead; go on as idle.
if status == 'running' and lease_until <= now then
  expired = holder
  status = 'idle'
end

-- Branch 2: running with a valid lease -> the message is an interjection.
if status == 'running' then
  if mode ~= 'submit' then
    return {'noop', holder, profile, '', redis.call('LLEN', KEYS[2]), ''}
  end
  return {'queued', holder, profile, '', push_message(), ''}
end

-- Branch 3: waiting for the user's answer -> the message is the answer. The
-- same run takes the lease back here, so a second message sent right behind it
-- sees "running" and becomes an interjection.
if status == 'waiting' then
  if mode ~= 'submit' then
    return {'noop', holder, profile, '', redis.call('LLEN', KEYS[2]), ''}
  end
  hold(holder, profile, lease_ms_for(profile))
  return {'answer', holder, profile, '', redis.call('LLEN', KEYS[2]), ''}
end

-- Branch 1: idle (or just declared idle by branch 4).
local unread = redis.call('LLEN', KEYS[2])
if unread > 0 then
  -- Unread messages of a run that died (or was released without the finish
  -- script). They are older than this message, so this message joins the
  -- inbox behind them and one relay run takes the whole inbox.
  if mode == 'submit' then
    unread = push_message()
  end
  local head = redis.call('LINDEX', KEYS[2], 0)
  local relay_profile = 'direct'
  local ok, decoded = pcall(cjson.decode, head)
  if ok and type(decoded) == 'table' and decoded['task_mode'] == true then
    relay_profile = 'planned'
  end
  hold(ARGV[2], relay_profile, tonumber(ARGV[7]))
  return {'relay', ARGV[2], relay_profile, expired, unread, head}
end

if mode ~= 'submit' then
  if expired == '' then
    return {'noop', '', '', '', 0, ''}
  end
  redis.call('HSET', KEYS[1], 'status', 'idle', 'run_id', '', 'profile', '', 'lease_until', '0',
    'updated_at', ARGV[5])
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[8]))
  return {'idle', '', '', expired, 0, ''}
end

hold(ARGV[2], ARGV[4], lease_ms_for(ARGV[4]))
return {'started', ARGV[2], ARGV[4], expired, 0, ''}

-- @@script finish
-- KEYS[1] = bisheng:run:state:{cid}
-- KEYS[2] = bisheng:run:inbox:{cid}
-- ARGV[1] = run id that finished ("" = do not check the holder)
-- ARGV[2] = relay run id (used only when the inbox is not empty)
-- ARGV[3] = now_ms
-- ARGV[4] = queued_lease_ms
-- ARGV[5] = state TTL seconds
-- Returns {outcome, run_id, profile, inbox_length, head_json}
--   outcome: "idle" | "relay" | "stale"
local st = redis.call('HMGET', KEYS[1], 'status', 'run_id')
local status = st[1] or 'idle'
local holder = st[2] or ''
local now = tonumber(ARGV[3])

-- Another run already holds the conversation (this run's lease lapsed and it
-- was taken over). Its state must not be overwritten.
if ARGV[1] ~= '' and holder ~= '' and holder ~= ARGV[1] then
  return {'stale', holder, '', redis.call('LLEN', KEYS[2]), ''}
end

local unread = redis.call('LLEN', KEYS[2])
if unread == 0 then
  redis.call('HSET', KEYS[1], 'status', 'idle', 'run_id', '', 'profile', '', 'lease_until', '0',
    'updated_at', ARGV[3])
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
  return {'idle', '', '', 0, ''}
end

-- Relay: the conversation goes straight from the finished run to the relay
-- run, with no idle gap in which a concurrent send could start a second run.
local head = redis.call('LINDEX', KEYS[2], 0)
local relay_profile = 'direct'
local ok, decoded = pcall(cjson.decode, head)
if ok and type(decoded) == 'table' and decoded['task_mode'] == true then
  relay_profile = 'planned'
end
redis.call('HSET', KEYS[1], 'status', 'running', 'run_id', ARGV[2], 'profile', relay_profile,
  'lease_until', tostring(now + tonumber(ARGV[4])), 'updated_at', ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return {'relay', ARGV[2], relay_profile, unread, head}
