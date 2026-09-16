-- BiSheng 3.0.0-beta1 permission configuration queries (DM8 dialect).
-- Identifiers user, group, mode and protected are double-quoted.

-- Q1 Resource grants: who was granted which permission model on which resource
SELECT
  g.tenant_id,
  g.resource_type,
  g.resource_id,
  COALESCE(k.name, f.file_name, w.name, s.name, t.name, c.name, b.title, sk.name) AS resource_name,
  CASE WHEN k.id IS NULL AND f.id IS NULL AND w.id IS NULL AND s.id IS NULL
            AND t.id IS NULL AND c.id IS NULL AND b.id IS NULL AND sk.id IS NULL
       THEN 0 ELSE 1 END AS resource_exists,
  g.model_key,
  pm.name AS model_name,
  a.subject_type,
  a.subject_id,
  CASE a.subject_type
    WHEN 'user' THEN u.user_name
    WHEN 'department' THEN d.name
    WHEN 'user_group' THEN ug.group_name
    WHEN 'service_account' THEN sa.name
  END AS subject_name,
  a.include_children,
  a.source_type,
  a."protected",
  a.create_time,
  a.update_time
FROM permission_grant g
JOIN permission_grant_assignee a
  ON a.grant_id = g.id AND a.state = 'ACTIVE'
LEFT JOIN permission_catalog_release r
  ON r.status = 'CURRENT'
LEFT JOIN permission_model pm
  ON pm.catalog_release_id = r.id AND pm.model_key = g.model_key
LEFT JOIN knowledge k
  ON g.resource_type IN ('knowledge_space', 'knowledge_library') AND CONCAT('', k.id) = g.resource_id
LEFT JOIN knowledgefile f
  ON g.resource_type IN ('folder', 'knowledge_file') AND CONCAT('', f.id) = g.resource_id
LEFT JOIN flow w
  ON g.resource_type = 'workflow' AND w.id = g.resource_id
LEFT JOIN assistant s
  ON g.resource_type = 'assistant' AND s.id = g.resource_id AND s.is_delete = 0
LEFT JOIN t_gpts_tools_type t
  ON g.resource_type = 'tool' AND CONCAT('', t.id) = g.resource_id AND t.is_delete = 0
LEFT JOIN channel c
  ON g.resource_type = 'channel' AND c.id = g.resource_id
LEFT JOIN dashboard b
  ON g.resource_type = 'dashboard' AND CONCAT('', b.id) = g.resource_id
LEFT JOIN linsight_skill sk
  ON g.resource_type = 'linsight_skill' AND CONCAT('', sk.id) = g.resource_id
LEFT JOIN "user" u
  ON a.subject_type = 'user' AND CONCAT('', u.user_id) = a.subject_id
LEFT JOIN department d
  ON a.subject_type = 'department' AND CONCAT('', d.id) = a.subject_id
LEFT JOIN "group" ug
  ON a.subject_type = 'user_group' AND CONCAT('', ug.id) = a.subject_id
LEFT JOIN service_account sa
  ON a.subject_type = 'service_account' AND CONCAT('', sa.id) = a.subject_id
WHERE g.state = 'ACTIVE'
ORDER BY g.tenant_id, g.resource_type, g.resource_id, pm.derived_level, a.subject_type, a.subject_id;

-- Q2 Permission models in effect and the actions each contains
SELECT pm.model_key, pm.name AS model_name, pm.kind, pm.derived_level, pm.active,
       pa.code AS action_code, pa.name AS action_name
FROM permission_catalog_release r
JOIN permission_model pm ON pm.catalog_release_id = r.id
LEFT JOIN permission_model_action pma ON pma.model_id = pm.id
LEFT JOIN permission_action pa ON pa.id = pma.action_id
WHERE r.status = 'CURRENT'
ORDER BY pm.derived_level, pm.model_key, pa.sort_order;

-- Q3 Inherit / custom mode of folders and files (and top-level resources)
SELECT m.tenant_id, m.resource_type, m.resource_id, m."mode", m.parent_type, m.parent_id, m.update_time
FROM resource_permission_mode m
ORDER BY m.tenant_id, m.resource_type, m.resource_id;

-- Q4 Knowledge space join policy
SELECT k.tenant_id, k.id AS space_id, k.name, k.auth_type
FROM knowledge k
WHERE k.type = 3
ORDER BY k.tenant_id, k.id;

-- Q5a User - department membership
SELECT ud.user_id, u.user_name, ud.department_id, d.name AS department_name, d.path, ud.is_primary
FROM user_department ud
JOIN "user" u ON u.user_id = ud.user_id
JOIN department d ON d.id = ud.department_id
ORDER BY ud.user_id, ud.is_primary DESC;

-- Q5b User - user group membership
SELECT x.user_id, u.user_name, x.group_id, g.group_name, x.is_group_admin
FROM usergroup x
JOIN "user" u ON u.user_id = x.user_id
JOIN "group" g ON g.id = x.group_id
ORDER BY x.group_id, x.user_id;

-- Q6a User - role
SELECT ur.user_id, u.user_name, ur.role_id, r.role_name, r.department_id AS role_department_id
FROM userrole ur
JOIN "user" u ON u.user_id = ur.user_id
JOIN role r ON r.id = ur.role_id
ORDER BY ur.user_id, ur.role_id;

-- Q6b Role - menu permissions (type 99 = web menu)
SELECT ra.role_id, r.role_name, ra.third_id AS menu_key
FROM roleaccess ra
JOIN role r ON r.id = ra.role_id
WHERE ra.type = 99
ORDER BY ra.role_id, ra.third_id;

-- Q6c Menu permissions granted to individual users through approval
SELECT uma.user_id, u.user_name, uma.menu_key, uma.menu_name, uma.grant_source, uma.create_time
FROM user_menu_access uma
JOIN "user" u ON u.user_id = uma.user_id
WHERE uma.status = 'active'
ORDER BY uma.user_id, uma.menu_key;

-- Q7a Department admins
SELECT dag.user_id, u.user_name, dag.department_id, d.name AS department_name, dag.grant_source
FROM department_admin_grant dag
JOIN "user" u ON u.user_id = dag.user_id
JOIN department d ON d.id = dag.department_id
ORDER BY dag.department_id, dag.user_id;

-- Q7b Super admins recorded in the business DB (legacy role 1)
SELECT ur.user_id, u.user_name
FROM userrole ur
JOIN "user" u ON u.user_id = ur.user_id
WHERE ur.role_id = 1;

-- Q7c Super admins / child-tenant admins recorded only in the OpenFGA datastore.
-- On DM8 deployments the datastore is the schema configured in OPENFGA_DATASTORE_URI, not the business schema.
SELECT object_type, object_id, relation, _user AS subject, inserted_at
FROM <openfga_schema>.tuple
WHERE (object_type = 'system' AND relation = 'super_admin')
   OR (object_type = 'tenant' AND relation = 'admin')
ORDER BY object_type, object_id;
