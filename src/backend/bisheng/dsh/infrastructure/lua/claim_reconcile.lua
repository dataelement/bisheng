if redis.call('TYPE',KEYS[1]).ok~='hash' or redis.call('TYPE',KEYS[2]).ok~='hash' then return {'DENY','missing_ledger'} end
if redis.call('HGET',KEYS[2],'epoch')~=ARGV[4] then return {'DENY','epoch_conflict'} end
local owner=redis.call('HGET',KEYS[1],'reconcile_owner')
local generation=redis.call('HGET',KEYS[1],'reconcile_generation') or '0'
if owner and owner~=ARGV[1] then return {'DENY','reconciliation_conflict'} end
if #ARGV[3]<#generation or (#ARGV[3]==#generation and ARGV[3]<generation) then return {'DENY','stale_worker'} end
if owner and redis.call('HGET',KEYS[1],'reconcile_hash')~=ARGV[2] then return {'DENY','payload_conflict'} end
redis.call('HSET',KEYS[1],'reconcile_owner',ARGV[1],'reconcile_hash',ARGV[2],'reconcile_generation',ARGV[3])
return {'OK'}
