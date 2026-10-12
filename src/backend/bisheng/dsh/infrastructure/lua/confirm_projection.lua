-- Called only after the repository scope has committed. Never infer SQL confirmation from delivery.
local now=redis.call('TIME'); local ms=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
for i=2,#KEYS do
  local offset=2*(i-2)+2
  if redis.call('TYPE',KEYS[i]).ok=='hash' and redis.call('HGET',KEYS[i],'event')==ARGV[offset+1] then
    redis.call('HSET',KEYS[i],'sql_confirmed_event',ARGV[offset+1],'sql_confirmed_ms',tostring(ms))
  end
end
return #KEYS-1
