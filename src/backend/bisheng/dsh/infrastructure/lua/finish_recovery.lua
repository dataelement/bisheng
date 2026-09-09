-- SQL epoch publication has committed; only this immutable recovery owner may open the gate.
if redis.call('TYPE',KEYS[1]).ok~='hash' then return {'DENY','missing_recovery_gate'} end
if redis.call('HGET',KEYS[1],'recovery_owner')~=ARGV[1] or redis.call('HGET',KEYS[1],'recovery_digest')~=ARGV[2] or redis.call('HGET',KEYS[1],'epoch')~=ARGV[3] or redis.call('HGET',KEYS[1],'version')~=ARGV[4] then return {'DENY','recovery_fence_lost'} end
if redis.call('HGET',KEYS[1],'state')~='FROZEN' and redis.call('HGET',KEYS[1],'state')~='READY' then return {'DENY','invalid_recovery_state'} end
-- Complete evidence recovery clears storage uncertainty only; policy operations keep their own blockers.
local kind=redis.call('TYPE',KEYS[2]).ok
if kind~='none' and kind~='set' then return {'DENY','bad_block_type'} end
for _,reason in ipairs(redis.call('SMEMBERS',KEYS[2])) do
  if string.sub(reason,1,18)=='STORAGE_UNCERTAIN:' then redis.call('SREM',KEYS[2],reason) end
end
redis.call('HSET',KEYS[1],'state','READY')
return {'OK'}
