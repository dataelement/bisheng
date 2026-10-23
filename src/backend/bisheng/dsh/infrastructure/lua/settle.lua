local unknown_type=redis.call('TYPE',KEYS[8]).ok
if unknown_type~='none' and unknown_type~='set' then return {'DENY','bad_usage_index_type'} end
local index_type=redis.call('TYPE',KEYS[7]).ok
if index_type~='none' and index_type~='zset' then return {'DENY','bad_running_index_type'} end
if redis.call('TYPE',KEYS[1]).ok=='hash' and redis.call('HGET',KEYS[1],'state')~='READY' then return {'DENY','recovery_required'} end
local expected={'hash','hash','hash','set','hash','stream'}
for i=1,6 do
  local t=redis.call('TYPE',KEYS[i]).ok
  if t~=expected[i] and not (i==4 and t=='none') then return {'DENY','missing_or_bad_ledger'} end
end
local function integer(s)
  return s and (s=='0' or string.match(s,'^[1-9][0-9]*$')) and (#s<19 or (#s==19 and s<='9223372036854775807'))
end
-- String arithmetic avoids Lua double rounding above 2^53.
local function add(a,b)
  local carry=0; local result=''; local i=#a; local j=#b
  while i>0 or j>0 or carry>0 do
    local n=(i>0 and tonumber(string.sub(a,i,i)) or 0)+(j>0 and tonumber(string.sub(b,j,j)) or 0)+carry
    result=tostring(n%10)..result; carry=math.floor(n/10); i=i-1; j=j-1
  end
  return result
end
if redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[2],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[2],'state')~='READY' then return {'DENY','recovery_required'} end
if redis.call('HGET',KEYS[5],'month')~=ARGV[5] or redis.call('HGET',KEYS[5],'model')~=ARGV[4] or redis.call('HGET',KEYS[5],'epoch')~=ARGV[12] then return {'DENY','ownership_mismatch'} end
if redis.call('HGET',KEYS[5],'version')==ARGV[3] then
  if redis.call('HGET',KEYS[5],'event')==ARGV[9] then return {'EXISTS',ARGV[9]} end
  return {'DENY','settlement_conflict'}
end
if redis.call('HGET',KEYS[5],'version')~=ARGV[2] then return {'DENY','event_version_conflict'} end
if redis.call('HGET',KEYS[5],'identity')~=ARGV[13] then return {'DENY','ownership_mismatch'} end
local old=redis.call('HGET',KEYS[5],'status')
if old~='RUNNING' and old~='USAGE_UNKNOWN' then return {'DENY','already_settled'} end
if old=='USAGE_UNKNOWN' and (ARGV[6]=='USAGE_UNKNOWN' or ARGV[10]=='' or ARGV[11]=='') then return {'DENY','reconciliation_required'} end
if old=='USAGE_UNKNOWN' and (redis.call('HGET',KEYS[5],'reconcile_owner')~=ARGV[10] or redis.call('HGET',KEYS[5],'reconcile_hash')~=ARGV[11] or redis.call('HGET',KEYS[5],'reconcile_generation')~=ARGV[14]) then return {'DENY','stale_reconciliation_worker'} end
local used=redis.call('HGET',KEYS[2],'used'); local model=redis.call('HGET',KEYS[3],ARGV[4])
if not integer(used) or not integer(model) then return {'DENY','bad_counter'} end
if redis.call('HGET',KEYS[1],'write_in_progress')=='1' then return {'DENY','ledger_write_incomplete'} end
if ARGV[7]~='' then
  if not integer(ARGV[7]) or not integer(add(used,ARGV[7])) or not integer(add(model,ARGV[7])) then return {'DENY','counter_overflow'} end
  redis.call('HSET',KEYS[1],'write_in_progress','1')
  redis.call('HSET',KEYS[2],'used',add(used,ARGV[7]))
  redis.call('HSET',KEYS[3],ARGV[4],add(model,ARGV[7]))
  redis.call('SREM',KEYS[8],ARGV[8])
else
  redis.call('HSET',KEYS[1],'write_in_progress','1')
  redis.call('SADD',KEYS[8],ARGV[8])
end
redis.call('HSET',KEYS[5],'event',ARGV[9],'version',ARGV[3],'status',ARGV[6],'operation_id',ARGV[10],'payload_hash',ARGV[11])
local id=redis.call('XADD',KEYS[6],'*','event',ARGV[9])
redis.call('HSET',KEYS[5],'latest_stream_id',id)
redis.call('HINCRBY',KEYS[5],'retained_stream_count',1)
local removed=redis.call('ZREM',KEYS[7],ARGV[8])
if removed==1 then redis.call('HINCRBY',KEYS[1],'running_count',-1) end
redis.call('HSET',KEYS[1],'write_in_progress','0')
return {'OK',ARGV[9]}
