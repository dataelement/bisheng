-- 示例：将主部门为「前端组」的用户「前端张三」同时挂到「后端组」为附属部门（is_primary=0）。
-- 若库中部门名或用户名不一致，请先 SELECT 修正 WHERE 条件后再执行。

INSERT INTO user_department (user_id, department_id, is_primary, source)
SELECT u.user_id, d_back.id, 0, 'local'
FROM user u
JOIN user_department ud_primary
  ON ud_primary.user_id = u.user_id AND ud_primary.is_primary = 1
JOIN department d_front ON d_front.id = ud_primary.department_id AND d_front.name = '前端组'
JOIN department d_back ON d_back.name = '后端组' AND d_back.status = 'active'
WHERE u.user_name = '前端张三' AND IFNULL(u.delete, 0) = 0
  AND NOT EXISTS (
    SELECT 1 FROM user_department x
    WHERE x.user_id = u.user_id AND x.department_id = d_back.id
  );
