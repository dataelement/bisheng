if redis.call('TYPE',KEYS[1]).ok~='hash' then return {'DENY','missing_user_ledger'} end
if redis.call('HGET',KEYS[1],'state')~='READY' or redis.call('HGET',KEYS[1],'epoch')~=ARGV[1] or redis.call('HGET',KEYS[1],'version')~=ARGV[2] or redis.call('HGET',KEYS[1],'write_in_progress')=='1' then return {'DENY','recovery_required'} end
if redis.call('HEXISTS',KEYS[1],'month:'..ARGV[3])==1 then
  if redis.call('TYPE',KEYS[2]).ok=='hash' and redis.call('TYPE',KEYS[3]).ok=='hash' then return {'OK'} end
  return {'DENY','lost_month_ledger'}
end
if redis.call('EXISTS',KEYS[2])~=0 or redis.call('EXISTS',KEYS[3])~=0 then return {'DENY','unexpected_month_history'} end
local count=0
for _,field in ipairs(redis.call('HKEYS',KEYS[1])) do if string.sub(field,1,6)=='model:' then count=count+1 end end
if count*2~=#ARGV-3 then return {'DENY','model_policy_mismatch'} end
for i=4,#ARGV,2 do
  if redis.call('HGET',KEYS[1],'model:'..ARGV[i])~='1' or redis.call('HGET',KEYS[1],'limit:'..ARGV[i])~=ARGV[i+1] then return {'DENY','model_policy_mismatch'} end
end
redis.call('HSET',KEYS[1],'write_in_progress','1')
redis.call('HSET',KEYS[2],'state','READY','epoch',ARGV[1],'used','0')
redis.call('HSET',KEYS[3],'_initialized','1')
for i=4,#ARGV,2 do redis.call('HSET',KEYS[3],ARGV[i],'0') end
redis.call('HSET',KEYS[1],'month:'..ARGV[3],'1','write_in_progress','0')
return {'OK'}
