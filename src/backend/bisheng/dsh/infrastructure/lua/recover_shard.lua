-- Every phase is fenced by an opaque recovery owner. Errors retain the shared FROZEN gate.
local command=ARGV[1]; local owner=ARGV[2]
if redis.call('TYPE',KEYS[1]).ok~='hash' then return {'DENY','bad_recovery_gate'} end
if command=='begin' then
  local current=redis.call('HGET',KEYS[1],'epoch')
  if current and current~=ARGV[3] and not (current==ARGV[5] and redis.call('HGET',KEYS[1],'recovery_digest')==ARGV[6]) then return {'DENY','epoch_conflict'} end
  redis.call('HSET',KEYS[1],'state','FROZEN','recovery_owner',owner,'recovery_count','0','recovery_expected',ARGV[4],'recovery_digest',ARGV[6])
  return {'OK'}
end
if redis.call('HGET',KEYS[1],'state')~='FROZEN' or redis.call('HGET',KEYS[1],'recovery_owner')~=owner then return {'DENY','recovery_fence_lost'} end
if command=='month' then
  for i=2,3 do local kind=redis.call('TYPE',KEYS[i]).ok; if kind~='none' and kind~='hash' then return {'DENY','bad_type'} end end
  redis.call('DEL',KEYS[2],KEYS[3])
  redis.call('HSET',KEYS[2],'used',ARGV[4],'epoch',ARGV[3],'state','READY')
  redis.call('HSET',KEYS[3],'_initialized','1')
  for i=6,#ARGV,2 do redis.call('HSET',KEYS[3],ARGV[i],ARGV[i+1]) end
  redis.call('HSET',KEYS[1],'month:'..ARGV[5],'1')
elseif command=='events' then
  if #KEYS-3>500 then return {'DENY','recovery_chunk_too_large'} end
  for i=2,#KEYS do
    local kind=redis.call('TYPE',KEYS[i]).ok
    local expected=i==2 and 'set' or (i==3 and 'stream' or 'hash')
    if kind~='none' and kind~=expected then return {'DENY','bad_type'} end
  end
  if redis.call('HGET',KEYS[1],'recovery_count')~=ARGV[3] then return {'DENY','recovery_cursor_conflict'} end
  local index=4
  for key=4,#KEYS do
    redis.call('HSET',KEYS[key],'event',ARGV[index],'version',ARGV[index+1],'status',ARGV[index+2],'month',ARGV[index+3],'model',ARGV[index+4],'epoch',ARGV[index+5],'identity',ARGV[index+6])
    if ARGV[index+2]=='USAGE_UNKNOWN' then redis.call('SADD',KEYS[2],ARGV[index+7]) end
    local id=redis.call('XADD',KEYS[3],'*','event',ARGV[index])
  redis.call('HSET',KEYS[key],'latest_stream_id',id)
redis.call('HINCRBY',KEYS[key],'retained_stream_count',1)
    index=index+8
  end
  redis.call('HINCRBY',KEYS[1],'recovery_count',#KEYS-3)
elseif command=='finish' then
  if redis.call('HGET',KEYS[1],'recovery_count')~=redis.call('HGET',KEYS[1],'recovery_expected') then return {'DENY','incomplete_recovery'} end
  for _,field in ipairs(redis.call('HKEYS',KEYS[1])) do
    if string.sub(field,1,6)=='model:' or string.sub(field,1,6)=='limit:' or string.sub(field,1,8)=='version:' or string.sub(field,1,13)=='operation_id:' or string.sub(field,1,11)=='generation:' or string.sub(field,1,18)=='installed_version:' or string.sub(field,1,15)=='policy_payload:' then redis.call('HDEL',KEYS[1],field) end
  end
  local last=6+tonumber(ARGV[6])*2
  for i=7,last,2 do redis.call('HSET',KEYS[1],'model:'..ARGV[i],'1','limit:'..ARGV[i],ARGV[i+1],'version:'..ARGV[i],ARGV[4]) end
  for i=last+1,#ARGV,2 do redis.call('HSET',KEYS[1],'version:'..ARGV[i],ARGV[i+1]) end
  redis.call('HSET',KEYS[1],'epoch',ARGV[3],'version',ARGV[4],'limit',ARGV[5],'write_in_progress','0','state','FROZEN','running_index','1','running_count','0')
else return {'DENY','unknown_recovery_phase'} end
return {'OK'}
