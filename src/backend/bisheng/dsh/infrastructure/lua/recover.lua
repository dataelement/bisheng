-- The service validated a bounded audited manifest. Any script failure leaves FROZEN.
local current=redis.call('HGET',KEYS[1],'epoch')
if current and current~=ARGV[1] and not (current==ARGV[2] and redis.call('HGET',KEYS[1],'recovery_digest')==ARGV[#ARGV-1]) then return {'DENY','epoch_conflict'} end
for i=1,#KEYS do
  local t=redis.call('TYPE',KEYS[i]).ok
  local expected='hash'; if i==2 then expected='set' elseif i==3 then expected='stream' end
  if t~='none' and t~=expected then return {'DENY','bad_type'} end
end
local index=6; local models=tonumber(ARGV[5]); local fields=redis.call('HKEYS',KEYS[1])
for _,f in ipairs(fields) do if string.sub(f,1,6)=='model:' or string.sub(f,1,6)=='limit:' or string.sub(f,1,8)=='version:' or string.sub(f,1,13)=='operation_id:' or string.sub(f,1,11)=='generation:' or string.sub(f,1,18)=='installed_version:' or string.sub(f,1,15)=='policy_payload:' then redis.call('HDEL',KEYS[1],f) end end
for i=1,models do redis.call('HSET',KEYS[1],'model:'..ARGV[index],'1','limit:'..ARGV[index],ARGV[index+1],'version:'..ARGV[index],ARGV[3]); index=index+2 end
local versions=tonumber(ARGV[index]); index=index+1
for i=1,versions do redis.call('HSET',KEYS[1],'version:'..ARGV[index],ARGV[index+1]); index=index+2 end
local months=tonumber(ARGV[index]); index=index+1; local key=4
for m=1,months do
  local total=ARGV[index]; local count=tonumber(ARGV[index+1]); index=index+2
  redis.call('DEL',KEYS[key],KEYS[key+1])
  redis.call('HSET',KEYS[key],'used',total,'epoch',ARGV[2],'state','READY')
  local month=string.match(KEYS[key],':month:(.+)$')
  redis.call('HSET',KEYS[1],'month:'..month,'1')
  for i=1,count do redis.call('HSET',KEYS[key+1],ARGV[index],ARGV[index+1]); index=index+2 end
  if count==0 then redis.call('HSET',KEYS[key+1],'_initialized','1') end
  key=key+2
end
redis.call('DEL',KEYS[2])
local count=tonumber(ARGV[index]); index=index+1
for i=1,count do
  redis.call('HSET',KEYS[key],'event',ARGV[index],'version',ARGV[index+1],'status',ARGV[index+2],'month',ARGV[index+3],'model',ARGV[index+4],'epoch',ARGV[index+5],'identity',ARGV[index+6])
  if ARGV[index+2]=='USAGE_UNKNOWN' then redis.call('SADD',KEYS[2],ARGV[index+7]) end
  local id=redis.call('XADD',KEYS[3],'*','event',ARGV[index])
  redis.call('HSET',KEYS[key],'latest_stream_id',id)
redis.call('HINCRBY',KEYS[key],'retained_stream_count',1)
  index=index+8; key=key+1
end
redis.call('HSET',KEYS[1],'epoch',ARGV[2],'version',ARGV[3],'limit',ARGV[4],'state','FROZEN','write_in_progress','0','running_index','1','running_count','0','recovery_digest',ARGV[#ARGV-1],'recovery_owner',ARGV[#ARGV])
return {'OK'}
