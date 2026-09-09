-- All keys share one user hash tag. Validate before writing: Lua errors do not roll back.
local expected = {'hash','hash','hash','set','hash','stream'}
for i=1,6 do
  local t=redis.call('TYPE',KEYS[i]).ok
  if t~='none' and t~=expected[i] then return {'DENY','bad_type'} end
  if i<=3 and t=='none' then return {'DENY','missing_ledger'} end
end
local function integer(s)
  return s and (s=='0' or string.match(s,'^[1-9][0-9]*$')) and (#s<19 or (#s==19 and s<='9223372036854775807'))
end
local function less(a,b) return #a<#b or (#a==#b and a<b) end
if redis.call('HGET',KEYS[1],'model:'..ARGV[3])~='1' then return {'DENY','model_not_allowed'} end
local used=redis.call('HGET',KEYS[3],ARGV[3])
local limit=redis.call('HGET',KEYS[1],'limit:'..ARGV[3])
if not integer(used) or not integer(limit) or not integer(redis.call('HGET',KEYS[3],ARGV[3])) then return {'DENY','bad_counter'} end
if redis.call('HGET',KEYS[1],'write_in_progress')=='1' then return {'DENY','ledger_write_incomplete'} end
if redis.call('HGET',KEYS[1],'state')~='READY' or redis.call('HGET',KEYS[2],'state')~='READY' then return {'DENY','not_ready'} end
if redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[2],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[1],'version')~=ARGV[2] then return {'DENY','version_mismatch'} end
if redis.call('HGET',KEYS[1],'model:'..ARGV[3])~='1' then return {'DENY','model_not_allowed'} end
local reason=pressure(KEYS[6],tonumber(ARGV[7]),tonumber(ARGV[8]),tonumber(ARGV[9]),tonumber(ARGV[10]))
if reason then return {'DENY',reason} end
if redis.call('SCARD',KEYS[4])~=0 then return {'DENY','blocked'} end
if redis.call('EXISTS',KEYS[5])==1 then
  if redis.call('HGET',KEYS[5],'admission')~=ARGV[4] then return {'DENY','request_conflict'} end
  return {'EXISTS',redis.call('HGET',KEYS[5],'event')}
end
if not less(used,limit) then return {'DENY','quota_exceeded'} end
local kind=redis.call('TYPE',KEYS[7]).ok
if (kind~='none' and kind~='zset') or redis.call('HGET',KEYS[1],'running_index')~='1' or redis.call('ZCARD',KEYS[7])~=tonumber(redis.call('HGET',KEYS[1],'running_count')) then return {'DENY','running_index_missing'} end
redis.call('HSET',KEYS[1],'write_in_progress','1')
redis.call('HSET',KEYS[5],'event',ARGV[4],'admission',ARGV[4],'version','1','status','RUNNING','month',ARGV[5],'model',ARGV[3],'epoch',ARGV[1],'identity',ARGV[6])
local id=redis.call('XADD',KEYS[6],'*','event',ARGV[4])
redis.call('HSET',KEYS[5],'latest_stream_id',id)
redis.call('HINCRBY',KEYS[5],'retained_stream_count',1)
redis.call('ZADD',KEYS[7],ARGV[12],ARGV[11])
redis.call('HINCRBY',KEYS[1],'running_count',1)
redis.call('HSET',KEYS[1],'write_in_progress','0')
return {'OK',ARGV[4]}
