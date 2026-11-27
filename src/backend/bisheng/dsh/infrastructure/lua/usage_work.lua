-- Work remains durable while claimed. All retries use Redis time, never a worker clock.
local now=redis.call('TIME'); local ms=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
local function last_id(stream)
  if redis.call('TYPE',stream).ok~='stream' then return '' end
  local info=redis.call('XINFO','STREAM',stream)
  for i=1,#info,2 do if info[i]=='last-generated-id' then return info[i+1] end end
  return ''
end
if ARGV[1]=='mark' then
  redis.call('SADD',KEYS[4],ARGV[2])
  return redis.call('ZADD',KEYS[1],'NX',ms,ARGV[2])
elseif ARGV[1]=='claim' then
  local users=redis.call('ZRANGEBYSCORE',KEYS[1],'-inf',ms,'LIMIT',0,1)
  if #users==0 then return {} end
  local stream=users[1]
  local id=last_id(stream)
  redis.call('ZADD',KEYS[1],ms+tonumber(ARGV[3]),stream)
  redis.call('HSET',KEYS[2],stream,ARGV[2])
  return {stream,ARGV[2],id}
elseif ARGV[1]=='finish' then
  if redis.call('HGET',KEYS[2],KEYS[3])~=ARGV[2] then return 0 end
  redis.call('HDEL',KEYS[2],KEYS[3])
  if ARGV[5]=='1' then
    redis.call('ZADD',KEYS[1],ms+tonumber(ARGV[4]),KEYS[3])
  elseif last_id(KEYS[3])~=ARGV[3] then
    redis.call('ZADD',KEYS[1],ms,KEYS[3])
  elseif redis.call('EXISTS',(string.gsub(KEYS[3],':events$',':tool_settlements')))==1 then
    -- 领取后可能有新结算入队，此时事件流的最后 ID 尚未改变。
    redis.call('ZADD',KEYS[1],ms+math.max(2000,tonumber(ARGV[4])),KEYS[3])
  elseif tonumber(ARGV[4])>0 then
    redis.call('ZADD',KEYS[1],ms+tonumber(ARGV[4]),KEYS[3])
  else
    redis.call('ZREM',KEYS[1],KEYS[3])
  end
  return 1
end
return redis.error_reply('Unknown usage work command')
