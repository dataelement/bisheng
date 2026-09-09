-- Shared mode (budget=0) respects the existing server limit without capping other applications.
local function pressure(stream,budget,headroom,high,age_ms)
  local info=redis.call('INFO','memory')
  local used=tonumber(string.match(info,'\nused_memory:([0-9]+)'))
  local maximum=tonumber(string.match(info,'\nmaxmemory:([0-9]+)'))
  if not used or not maximum then return 'capacity_unknown' end
  if budget==0 then
    if maximum>0 and used>=maximum-math.min(headroom,maximum/10) then return 'capacity_backpressure' end
  else
    if maximum>0 then budget=math.min(budget,maximum) end
    if budget<=headroom or used>=budget-headroom then return 'capacity_backpressure' end
  end
-- Admission independently detects a stopped projector; worker liveness is not a gate.
if redis.call('TYPE',stream).ok=='stream' then
  local groups=redis.call('XINFO','GROUPS',stream); local found=nil
  for _,g in ipairs(groups) do
    local row={}; for i=1,#g,2 do row[g[i]]=g[i+1] end
    if row.name=='dsh-sql-projection-v1' then found=row end
  end
  local oldest=nil
  if found then
    if not found.lag or found.lag+found.pending>=high then return 'projection_backpressure' end
    local pending=redis.call('XPENDING',stream,'dsh-sql-projection-v1','-','+',1)
    if #pending>0 then oldest=pending[1][1] end
    local unread=redis.call('XRANGE',stream,'('..found['last-delivered-id'],'+','COUNT',1)
    if #unread>0 then
      local id=unread[1][1]
      if not oldest or tonumber(string.match(id,'^[0-9]+'))<tonumber(string.match(oldest,'^[0-9]+')) then oldest=id end
    end
  else
    if redis.call('XLEN',stream)>=high then return 'projection_backpressure' end
    local unread=redis.call('XRANGE',stream,'-','+','COUNT',1)
    if #unread>0 then oldest=unread[1][1] end
  end
  if oldest then
    local now=redis.call('TIME'); local now_ms=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
    if now_ms-tonumber(string.match(oldest,'^[0-9]+'))>age_ms then return 'projection_backpressure' end
  end
end
return nil
end
