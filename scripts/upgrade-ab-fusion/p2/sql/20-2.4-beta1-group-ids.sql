-- hop 2.4-beta1：会话用户组。大表可按 create_time 分批，把下面 WHERE 再加上时间窗。
-- JSON_ARRAYAGG 是合法函数名（官方文档被飞书转成了 *JSON_ARRAYAGG*）。

UPDATE message_session m
LEFT JOIN (
  SELECT ms.chat_id, JSON_ARRAYAGG(ug.group_id) AS group_ids
  FROM message_session AS ms
  JOIN usergroup AS ug ON ms.user_id = ug.user_id
  GROUP BY ms.chat_id
) mg ON m.chat_id = mg.chat_id
SET m.group_ids = mg.group_ids
WHERE m.group_ids IS NULL;
