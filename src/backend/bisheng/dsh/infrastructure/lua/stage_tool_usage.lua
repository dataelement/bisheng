-- KEYS[1]=tool_settlements，KEYS[2]=events，KEYS[3]=projection_work
-- ARGV[1]=request_id，ARGV[2]=完整结算事件
local existing=redis.call('HGET',KEYS[1],ARGV[1])
if existing and existing~=ARGV[2] then return {'DENY','settlement_conflict'} end
if not existing then redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]) end
return {'OK'}
