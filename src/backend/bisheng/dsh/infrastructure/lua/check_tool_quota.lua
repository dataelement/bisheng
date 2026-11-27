-- Pre-execution quota check for paid non-task tool calls.
-- KEYS[1]=gate, KEYS[2]=month:{YM}, KEYS[3]=blocks
-- ARGV[1]=expected_epoch, ARGV[2]=mode ("" or "unmetered"), ARGV[3]=monthly_limit_override (optional)
if redis.call('TYPE',KEYS[1]).ok~='hash' or redis.call('TYPE',KEYS[2]).ok~='hash' then
  return {'DENY','missing_user_ledger'}
end
local function integer(v) return v and string.match(v,'^%d+$') and (#v<19 or (#v==19 and v<='9223372036854775807')) end
local function less(a,b) return #a<#b or (#a==#b and a<b) end
if redis.call('HGET',KEYS[1],'write_in_progress')=='1' then return {'DENY','ledger_write_incomplete'} end
if redis.call('HGET',KEYS[1],'state')~='READY' or redis.call('HGET',KEYS[2],'state')~='READY' then
  return {'DENY','not_ready'}
end
if redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[2],'epoch')~=ARGV[1] then
  return {'DENY','version_mismatch'}
end
if redis.call('HGET',KEYS[1],'backpressure')=='1' then return {'DENY','projection_backlog'} end
local blocks_type=redis.call('TYPE',KEYS[3]).ok
if blocks_type~='none' and blocks_type~='set' then return {'DENY','bad_counter'} end
if redis.call('SCARD',KEYS[3])>0 then return {'DENY','blocked'} end
local used=redis.call('HGET',KEYS[2],'used')
local limit=(ARGV[3] and ARGV[3]~='') and ARGV[3] or redis.call('HGET',KEYS[1],'limit')
if not integer(used) or not integer(limit) then return {'DENY','bad_counter'} end
if ARGV[2]=='unmetered' then
  return {'OK',used,limit}
end
if not less(used,limit) then return {'DENY','quota_exceeded'} end
return {'OK',used,limit}
