-- 手动删除历史「默认用户组」（名称 Default user group / 默认用户组）。
-- 执行前请备份数据库；若启用 OpenFGA，建议仍运行 scripts/remove_default_user_group.py 以清理 FGA 元组。

DELETE gr FROM group_resource gr
INNER JOIN `group` g
  ON g.group_name IN ('Default user group', '默认用户组')
  AND gr.group_id = CAST(g.id AS CHAR);

DELETE ug FROM user_group ug
INNER JOIN `group` g ON g.id = ug.group_id
WHERE g.group_name IN ('Default user group', '默认用户组');

DELETE FROM `group`
WHERE group_name IN ('Default user group', '默认用户组');
