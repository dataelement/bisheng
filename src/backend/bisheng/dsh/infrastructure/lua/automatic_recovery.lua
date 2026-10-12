-- Every mutation checks the expiring shared owner; a stale restorer cannot overwrite a successor.
if redis.call('GET',KEYS[1])~=ARGV[1] then return {'DENY','recovery_fence_lost'} end
redis.call('PEXPIRE',KEYS[1],30000)
local command=ARGV[2]
if command=='renew' then return {'OK'} end
if command=='begin' then
  redis.call('HSET',KEYS[2],'state','FROZEN')
elseif command=='reset' then
  redis.call('DEL',KEYS[2],KEYS[3],KEYS[4],KEYS[5])
  redis.call('HSET',KEYS[2],'state','FROZEN','write_in_progress','0')
  for k,v in pairs(cjson.decode(ARGV[3])) do redis.call('HSET',KEYS[2],k,v) end
  for _,v in ipairs(cjson.decode(ARGV[4])) do redis.call('SADD',KEYS[5],v) end
elseif command=='month' then
  redis.call('DEL',KEYS[3],KEYS[4])
  redis.call('HSET',KEYS[3],'used',ARGV[5],'epoch',ARGV[4],'state','READY')
  redis.call('HSET',KEYS[4],'_initialized','1')
  for k,v in pairs(cjson.decode(ARGV[6])) do redis.call('HSET',KEYS[4],k,v) end
  redis.call('HSET',KEYS[2],'month:'..ARGV[3],'1')
elseif command=='events' then
  for i,event in ipairs(cjson.decode(ARGV[3])) do
    local key=KEYS[i+5]
    redis.call('HSET',key,'event',event.event,'version',event.version,'status',event.status,'month',event.month,'model',event.model,'epoch',event.epoch,'identity',event.identity)
    local id=redis.call('XADD',KEYS[3],'*','event',event.event)
    redis.call('HSET',key,'latest_stream_id',id)
    redis.call('HINCRBY',key,'retained_stream_count',1)
    if event.status=='RUNNING' then redis.call('ZADD',KEYS[4],event.started,event.id) end
    if event.status=='USAGE_UNKNOWN' then redis.call('SADD',KEYS[5],event.id) end
  end
elseif command=='counts' then
  for i=3,#KEYS do redis.call('HSET',KEYS[i],'retained_stream_count',ARGV[i]) end
elseif command=='finish' then
  local running=string.gsub(KEYS[2],':gate$',':running')
  redis.call('HSET',KEYS[2],'state','READY','running_count',redis.call('ZCARD',running))
else return {'DENY','invalid_recovery_phase'} end
return {'OK'}
