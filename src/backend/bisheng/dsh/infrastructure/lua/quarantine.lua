-- This connection may confirm only the originally approved primary, or ADD a blocker.
-- It never grants admission, increments usage, removes a blocker, or publishes READY.
local bt=redis.call('TYPE',KEYS[2]).ok
if bt~='none' and bt~='set' then return {'FROZEN'} end
local rt=redis.call('TYPE',KEYS[3]).ok
local current=rt=='hash' and redis.call('HGET',KEYS[3],'event') or nil
local run=string.match(redis.call('INFO','server'),'run_id:([^\r\n]+)')
local complete=redis.call('TYPE',KEYS[1]).ok=='hash' and redis.call('HGET',KEYS[1],'write_in_progress')~='1'
local same_primary=complete and run==ARGV[1] and string.match(redis.call('INFO','replication'),'role:master')~=nil
if same_primary and current==ARGV[2] then return {'CONFIRMED'} end
if redis.call('HGET',KEYS[1],'state')=='FROZEN' then return {'FROZEN'} end
local status=rt=='hash' and redis.call('HGET',KEYS[3],'status') or nil
if same_primary and (status=='SUCCEEDED' or status=='FAILED' or status=='CANCELLED') then return {'KNOWN_DIFFERENT'} end
redis.call('SADD',KEYS[2],'STORAGE_UNCERTAIN:'..ARGV[4])
local st=redis.call('TYPE',KEYS[4]).ok
if same_primary and rt=='hash' and status=='RUNNING' and (st=='none' or st=='stream') and redis.call('HGET',KEYS[3],'identity')==ARGV[3] and redis.call('HGET',KEYS[3],'version')==ARGV[6] then
  redis.call('HSET',KEYS[3],'event',ARGV[5],'version',ARGV[7],'status','USAGE_UNKNOWN')
  local id=redis.call('XADD',KEYS[4],'*','event',ARGV[5])
  redis.call('HSET',KEYS[3],'latest_stream_id',id)
redis.call('HINCRBY',KEYS[3],'retained_stream_count',1)
  local kind=redis.call('TYPE',KEYS[5]).ok
  if kind=='zset' then
    local removed=redis.call('ZREM',KEYS[5],ARGV[4])
    if removed==1 then redis.call('HINCRBY',KEYS[1],'running_count',-1) end
  end
  return {'UNKNOWN'}
end
return {'FROZEN'}
