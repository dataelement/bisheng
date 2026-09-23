local gt=redis.call('TYPE',KEYS[1]).ok
if gt=='hash' then
  if redis.call('HGET',KEYS[1],'epoch')==ARGV[1] then return {'OK'} end
  return {'DENY','epoch_conflict'}
end
if gt~='none' or redis.call('EXISTS',KEYS[2])~=0 or redis.call('EXISTS',KEYS[3])~=0 then return {'DENY','unexpected_user_history'} end
redis.call('HSET',KEYS[1],'state','READY','running_index','1','running_count','0','epoch',ARGV[1],'version','0','limit','0','generation','0','initialized_by_operation',ARGV[2])
return {'OK'}
