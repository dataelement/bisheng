-- Policy ownership and versions belong to one user/model row. Usage remains a user hash slot.
local gt=redis.call('TYPE',KEYS[1]).ok; local bt=redis.call('TYPE',KEYS[2]).ok
if gt~='hash' or (bt~='none' and bt~='set') then return {'DENY','bad_policy_ledger'} end
if redis.call('HGET',KEYS[1],'state')~='READY' then return {'DENY','recovery_required'} end
if redis.call('HGET',KEYS[1],'epoch')~=ARGV[4] then return {'DENY','epoch_conflict'} end
local model=ARGV[6]; local suffix=':'..model
local owner=redis.call('HGET',KEYS[1],'operation_id'..suffix)
local generation=redis.call('HGET',KEYS[1],'generation'..suffix) or '0'
local current=redis.call('HGET',KEYS[1],'version'..suffix) or '0'
local reason='POLICY_SYNC:'..model..':'..ARGV[2]
local function less(a,b) return #a<#b or (#a==#b and a<b) end
if ARGV[1]=='block' then
  if owner==ARGV[2] then
    if less(ARGV[3],generation) then return {'DENY','stale_worker'} end
    if current~=ARGV[5] and current~=redis.call('HGET',KEYS[1],'installed_version'..suffix) then return {'DENY','version_conflict'} end
  else
    local prefix='POLICY_SYNC:'..model..':'
    for _,r in ipairs(redis.call('SMEMBERS',KEYS[2])) do
      if string.sub(r,1,#prefix)==prefix then return {'DENY','policy_owned'} end
    end
    if current~=ARGV[5] then return {'DENY','version_conflict'} end
  end
  redis.call('HSET',KEYS[1],'operation_id'..suffix,ARGV[2],'generation'..suffix,ARGV[3])
  redis.call('SADD',KEYS[2],reason)
  return {'OK'}
end
if owner~=ARGV[2] or generation~=ARGV[3] then return {'DENY','stale_worker'} end
if ARGV[1]=='install' then
  if current==ARGV[7] then
    if redis.call('HGET',KEYS[1],'policy_payload'..suffix)~=ARGV[9] then return {'DENY','payload_conflict'} end
    return {'OK'}
  end
  if current~=ARGV[5] or redis.call('SISMEMBER',KEYS[2],reason)~=1 then return {'DENY','version_conflict'} end
  local function integer(s)
    return s and (s=='0' or string.match(s,'^[1-9][0-9]*$')) and (#s<19 or (#s==19 and s<='9223372036854775807'))
  end
  local function add(a,b)
    local carry=0; local result=''; local i=#a; local j=#b
    while i>0 or j>0 or carry>0 do
      local n=(i>0 and tonumber(string.sub(a,i,i)) or 0)+(j>0 and tonumber(string.sub(b,j,j)) or 0)+carry
      result=tostring(n%10)..result; carry=math.floor(n/10); i=i-1; j=j-1
    end
    return result
  end
  -- A new model starts at zero only after the intact component sum proves no missing usage.
  for key=3,#KEYS,2 do
    if redis.call('TYPE',KEYS[key]).ok~='hash' or redis.call('TYPE',KEYS[key+1]).ok~='hash' then return {'DENY','missing_ledger'} end
    local used=redis.call('HGET',KEYS[key],'used'); local total='0'
    local components=redis.call('HGETALL',KEYS[key+1])
    for i=1,#components,2 do
      if components[i]~='_initialized' then
        if not integer(components[i+1]) then return {'DENY','bad_counter'} end
        total=add(total,components[i+1])
      end
    end
    if total~=used then return {'DENY','incomplete_model_ledger'} end
  end

  local total=ARGV[10]=='1' and ARGV[8] or '0'
  for _,field in ipairs(redis.call('HKEYS',KEYS[1])) do
    if string.sub(field,1,6)=='limit:' and field~='limit:'..model then
      local value=redis.call('HGET',KEYS[1],field)
      if not integer(value) then return {'DENY','bad_counter'} end
      total=add(total,value)
    end
  end
  if not integer(total) then return {'DENY','quota_total_overflow'} end
  for key=3,#KEYS,2 do redis.call('HSETNX',KEYS[key+1],model,'0') end
  if ARGV[10]=='1' then
    redis.call('HSET',KEYS[1],'model:'..model,'1','limit:'..model,ARGV[8])
  else
    redis.call('HDEL',KEYS[1],'model:'..model,'limit:'..model)
  end
  redis.call('HINCRBY',KEYS[1],'version',1)
  redis.call('HSET',KEYS[1],'version'..suffix,ARGV[7],'installed_version'..suffix,ARGV[7],
             'limit',total,'policy_payload'..suffix,ARGV[9])
  return {'OK'}
end
if ARGV[1]=='finish' then
  if current~=ARGV[5] then return {'DENY','version_conflict'} end
  redis.call('SREM',KEYS[2],reason)
  return {'OK'}
end
return {'DENY','invalid_action'}
