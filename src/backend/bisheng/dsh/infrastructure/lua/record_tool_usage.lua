-- Post-execution atomic tool usage settlement into unified Redis ledger.
-- KEYS[1]=gate, KEYS[2]=month:{YM}, KEYS[3]=tools:{YM}, KEYS[4]=request:{id}, KEYS[5]=events, KEYS[6]=tool_settlements, KEYS[7]=projection_work
-- ARGV[1]=expected_epoch, ARGV[2]=tool_id, ARGV[3]=billed_tokens, ARGV[4]=event_json, ARGV[5]=usage_month, ARGV[6]=identity, ARGV[7]=request_id
local function integer(v) return v and string.match(v,'^%d+$') and (#v<19 or (#v==19 and v<='9223372036854775807')) end
local function add(a,b)
  local i,j,carry,result=#a,#b,0,''
  while i>0 or j>0 or carry>0 do
    local n=(i>0 and tonumber(string.sub(a,i,i)) or 0)+(j>0 and tonumber(string.sub(b,j,j)) or 0)+carry
    result=tostring(n%10)..result; carry=math.floor(n/10); i=i-1; j=j-1
  end
  return result
end
if not integer(ARGV[3]) then return {'DENY','bad_counter'} end
local pending_type=redis.call('TYPE',KEYS[6]).ok
if pending_type~='none' and pending_type~='hash' then return {'DENY','bad_tool_settlements_type'} end
if redis.call('EXISTS',KEYS[4])==1 then
  if redis.call('HGET',KEYS[4],'event_kind')=='tool'
     and redis.call('HGET',KEYS[4],'billed_tokens')==ARGV[3]
     and redis.call('HGET',KEYS[4],'identity')==ARGV[6] then
    redis.call('HDEL',KEYS[6],ARGV[7])
    return {'OK','idempotent'}
  end
  return {'DENY','settlement_conflict'}
end
if redis.call('TYPE',KEYS[1]).ok~='hash' or redis.call('TYPE',KEYS[2]).ok~='hash' then
  return {'DENY','missing_user_ledger'}
end
local tt=redis.call('TYPE',KEYS[3]).ok
if tt~='none' and tt~='hash' then return {'DENY','bad_counter'} end
local stream_type=redis.call('TYPE',KEYS[5]).ok
if stream_type~='none' and stream_type~='stream' then return {'DENY','bad_event_stream_type'} end
if redis.call('HGET',KEYS[1],'write_in_progress')=='1' then return {'DENY','ledger_write_incomplete'} end
if redis.call('HGET',KEYS[1],'state')~='READY' or redis.call('HGET',KEYS[2],'state')~='READY' then
  return {'DENY','not_ready'}
end
if redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[2],'epoch')~=ARGV[1] then
  return {'DENY','version_mismatch'}
end
local used=redis.call('HGET',KEYS[2],'used')
local tool_used=redis.call('HGET',KEYS[3],ARGV[2]) or '0'
if not integer(used) or not integer(tool_used) then return {'DENY','bad_counter'} end
local new_used=add(used,ARGV[3])
local new_tool_used=add(tool_used,ARGV[3])
if not integer(new_used) or not integer(new_tool_used) then return {'DENY','counter_overflow'} end
redis.call('HSET',KEYS[1],'write_in_progress','1')
-- 先留下可恢复的事件。追加失败时尚未变更任何计数。
local id=redis.pcall('XADD',KEYS[5],'*','event',ARGV[4],'event_kind','tool')
if type(id)=='table' and id.err then
  redis.call('HSET',KEYS[1],'write_in_progress','0')
  return {'DENY','event_append_failed'}
end
redis.call('HSET',KEYS[2],'used',new_used)
redis.call('HSET',KEYS[3],'_initialized','1',ARGV[2],new_tool_used)
redis.call('HSET',KEYS[4],'event',ARGV[4],'event_kind','tool','version','1','status','SUCCEEDED','month',ARGV[5],'model',ARGV[2],'tool_id',ARGV[2],'billed_tokens',ARGV[3],'epoch',ARGV[1],'identity',ARGV[6],'latest_stream_id',id,'retained_stream_count','1')
redis.call('HSET',KEYS[1],'write_in_progress','0')
redis.call('HDEL',KEYS[6],ARGV[7])
return {'OK',new_used,new_tool_used}
