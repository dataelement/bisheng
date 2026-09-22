"""内容工作项的原子领取、退避与终止; 所有键保持相同 Redis hash tag。"""

ENQUEUE = """
local count = 0
for i = 2, #ARGV do
  if redis.call('hexists', KEYS[2], ARGV[i]) == 0 then
    count = count + redis.call('zadd', KEYS[1], 'NX', ARGV[1], ARGV[i])
  end
end
return count
"""

CLAIM = """
if redis.call('get', KEYS[4]) ~= ARGV[1] then return {} end
local values = redis.call('zrangebyscore', KEYS[1], '-inf', ARGV[2], 'withscores', 'LIMIT', 0, ARGV[4])
local claimed = {}
for i = 1, #values, 2 do
  local member = values[i]
  local attempt = tonumber(redis.call('hget', KEYS[5], member) or 0)
  if attempt > 0 and #claimed > 0 then break end
  redis.call('zrem', KEYS[1], member)
  if redis.call('hexists', KEYS[6], member) == 0 and attempt < tonumber(ARGV[5]) then
    redis.call('hincrby', KEYS[5], member, 1)
    redis.call('zadd', KEYS[2], ARGV[3], member)
    redis.call('hset', KEYS[3], member, values[i + 1])
    table.insert(claimed, member)
    table.insert(claimed, values[i + 1])
    if attempt > 0 then break end
  elseif redis.call('hexists', KEYS[6], member) == 0 then
    redis.call('hset', KEYS[6], member, cjson.encode({attempt=attempt, error='retry budget exhausted', at=ARGV[2]}))
  end
end
return claimed
"""

RECLAIM = """
local expired = redis.call('zrangebyscore', KEYS[2], '-inf', ARGV[1], 'LIMIT', 0, 1000)
for _, member in ipairs(expired) do
  local attempt = tonumber(redis.call('hget', KEYS[4], member) or 1)
  if attempt >= tonumber(ARGV[2]) then
    redis.call('hset', KEYS[5], member, cjson.encode({attempt=attempt, error='processing lease expired', at=ARGV[1]}))
    redis.call('zrem', KEYS[1], member)
  else
    local next_at = tonumber(ARGV[1]) + math.min(900, 30 * 2 ^ (attempt - 1)) * 1000
    redis.call('zadd', KEYS[1], next_at, member)
  end
  redis.call('zrem', KEYS[2], member)
  redis.call('hdel', KEYS[3], member)
end
return #expired
"""

FAIL = """
if redis.call('get', KEYS[4]) ~= ARGV[1] then return 0 end
local count = 0
for i = 5, #ARGV do
  local member = ARGV[i]
  if redis.call('zscore', KEYS[2], member) then
    local attempt = tonumber(redis.call('hget', KEYS[5], member) or 1)
    local detail = cjson.encode({attempt=attempt, error=ARGV[4], at=ARGV[2]})
    redis.call('hset', KEYS[7], member, detail)
    if attempt >= tonumber(ARGV[3]) then
      redis.call('hset', KEYS[6], member, detail)
      redis.call('zrem', KEYS[1], member)
    else
      local next_at = tonumber(ARGV[2]) + math.min(900, 30 * 2 ^ (attempt - 1)) * 1000
      redis.call('zadd', KEYS[1], next_at, member)
    end
    redis.call('zrem', KEYS[2], member)
    redis.call('hdel', KEYS[3], member)
    count = count + 1
  end
end
return count
"""

REPLAY = """
if redis.call('zscore', KEYS[2], ARGV[1]) then return 0 end
if redis.call('hdel', KEYS[3], ARGV[1]) == 0 then return 0 end
redis.call('hdel', KEYS[4], ARGV[1])
redis.call('hdel', KEYS[5], ARGV[1])
redis.call('zadd', KEYS[1], ARGV[2], ARGV[1])
return 1
"""


class QueuedProjectionFailure(RuntimeError):
    """失败已归还工作项队列, 由工作项预算负责后续重试。"""
