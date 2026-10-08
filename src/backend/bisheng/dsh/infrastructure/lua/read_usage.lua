for i=1,4 do
  local kind=redis.call('TYPE',KEYS[i]).ok
  local expected=i==4 and 'set' or 'hash'
  if kind~=expected and not (i==4 and kind=='none') then return {'DENY','missing_or_bad_ledger'} end
end
local function integer(s) return s and (s=='0' or string.match(s,'^[1-9][0-9]*$')) and (#s<19 or (#s==19 and s<='9223372036854775807')) end
local function add(a,b)
  local carry=0; local result=''; local i=#a; local j=#b
  while i>0 or j>0 or carry>0 do
    local n=(i>0 and tonumber(string.sub(a,i,i)) or 0)+(j>0 and tonumber(string.sub(b,j,j)) or 0)+carry
    result=tostring(n%10)..result; carry=math.floor(n/10); i=i-1; j=j-1
  end
  return result
end
local used=redis.call('HGET',KEYS[2],'used'); local limit=redis.call('HGET',KEYS[1],'limit')
if not integer(used) or not integer(limit) then return {'DENY','bad_counter'} end
local models=redis.call('HGETALL',KEYS[3]); local sum='0'
for i=1,#models,2 do
  if models[i]~='_initialized' then
    if not integer(models[i+1]) then return {'DENY','bad_counter'} end
    sum=add(sum,models[i+1])
  end
end
if sum~=used then return {'DENY','incomplete_model_ledger'} end
local limits={}; local total_limit='0'
for _,field in ipairs(redis.call('HKEYS',KEYS[1])) do
  if string.sub(field,1,6)=='model:' then
    local model=string.sub(field,7); local value=redis.call('HGET',KEYS[1],'limit:'..model)
    if not integer(value) or not integer(redis.call('HGET',KEYS[3],model)) then return {'DENY','missing_model_limit'} end
    limits[#limits+1]=model; limits[#limits+1]=value; total_limit=add(total_limit,value)
  end
end
if total_limit~=limit then return {'DENY','incomplete_model_limits'} end
local state='ready'
if redis.call('HGET',KEYS[1],'state')~='READY' or redis.call('HGET',KEYS[2],'state')~='READY' or redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[2],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[1],'write_in_progress')=='1' then state='unavailable'
elseif redis.call('SCARD',KEYS[4])>0 then state='blocked' end
if pressure(KEYS[5],tonumber(ARGV[2]),tonumber(ARGV[3]),tonumber(ARGV[4]),tonumber(ARGV[5])) then state='unavailable' end
local kind=redis.call('TYPE',KEYS[6]).ok
if (kind~='none' and kind~='zset') or redis.call('HGET',KEYS[1],'running_index')~='1' then state='unavailable'
elseif redis.call('ZCARD',KEYS[6])~=tonumber(redis.call('HGET',KEYS[1],'running_count')) then state='unavailable' end
local unknown_type=redis.call('TYPE',KEYS[7]).ok
if unknown_type~='none' and unknown_type~='set' then return {'DENY','bad_usage_index_type'} end
-- Missing usage is observational and never changes the admission state.
local unknown=redis.call('SCARD',KEYS[7])
local now=redis.call('TIME')
return {'OK',used,limit,state,now[1],now[2],models,tostring(unknown),limits}
