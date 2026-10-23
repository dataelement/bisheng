-- A restorer owns the request inventory while the shared gate is frozen.
local gate=string.gsub(KEYS[2],':request:[^:]+$',':gate')
if redis.call('HGET',gate,'state')~='READY' then return 0 end
-- Deletion is conservative: only the exact SQL-confirmed reliable state, retained long enough.
if redis.call('TYPE',KEYS[1]).ok~='stream' or redis.call('TYPE',KEYS[2]).ok~='hash' then return 0 end
local event=redis.call('HGET',KEYS[2],'event')
if event~=ARGV[3] or redis.call('HGET',KEYS[2],'sql_confirmed_event')~=event then return 0 end
local state=redis.call('HGET',KEYS[2],'status')
if state~='SUCCEEDED' and state~='FAILED' and state~='CANCELLED' then return 0 end
local confirmed=tonumber(redis.call('HGET',KEYS[2],'sql_confirmed_ms'))
local now=redis.call('TIME'); local ms=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
if not confirmed or ms-confirmed<tonumber(ARGV[4]) then return 0 end
-- Every group must have delivered and ACKed this entry; adding another consumer group is safe.
local groups=redis.call('XINFO','GROUPS',KEYS[1]); if #groups==0 then return 0 end
local function id_less(a,b)
  local am,as=string.match(a,'^(%d+)%-(%d+)$'); local bm,bs=string.match(b,'^(%d+)%-(%d+)$')
  return tonumber(am)<tonumber(bm) or (am==bm and tonumber(as)<tonumber(bs))
end
for _,g in ipairs(groups) do
  local row={}; for i=1,#g,2 do row[g[i]]=g[i+1] end
  if id_less(row['last-delivered-id'],ARGV[2]) then return 0 end
  if #redis.call('XPENDING',KEYS[1],row.name,ARGV[2],ARGV[2],1)>0 then return 0 end
end
-- Keep a compact request proof while older stream events still exist. Only the latest entry may remove it.
local latest=redis.call('HGET',KEYS[2],'latest_stream_id')
local retained=tonumber(redis.call('HGET',KEYS[2],'retained_stream_count'))
if not latest or not retained or retained<1 then return 0 end
local removed=redis.call('XDEL',KEYS[1],ARGV[2])
if removed==1 then
  if retained==1 then redis.call('DEL',KEYS[2]) else redis.call('HINCRBY',KEYS[2],'retained_stream_count',-1) end
end
return removed
