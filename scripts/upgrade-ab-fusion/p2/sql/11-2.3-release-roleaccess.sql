-- hop 2.3 release：历史角色补工作台/管理后台菜单。可重跑。
INSERT INTO `roleaccess` (`role_id`, `type`, `third_id`)
SELECT r.id, 99, 'frontend'
FROM role r
WHERE NOT EXISTS (
  SELECT 1 FROM roleaccess a
  WHERE a.role_id = r.id AND a.type = 99 AND a.third_id = 'frontend'
);

INSERT INTO `roleaccess` (`role_id`, `type`, `third_id`)
SELECT r.id, 99, 'backend'
FROM role r
WHERE NOT EXISTS (
  SELECT 1 FROM roleaccess a
  WHERE a.role_id = r.id AND a.type = 99 AND a.third_id = 'backend'
);
