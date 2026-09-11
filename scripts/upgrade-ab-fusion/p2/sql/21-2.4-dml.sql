-- hop 2.4 正式版结构变更（官方「升级到 2.4.0」）。列由 shell 按需 ADD。
-- 本文件只含可重跑的 DML / 修改列类型 / 删索引由 shell 执行。

INSERT INTO config (`key`, `value`)
SELECT 'workstation_linsight',
       JSON_UNQUOTE(JSON_EXTRACT(CAST(value AS JSON), '$.linsightConfig'))
FROM config
WHERE `key` = 'workstation'
  AND NOT EXISTS (SELECT 1 FROM config c2 WHERE c2.`key` = 'workstation_linsight');

-- 官方 2.4.0: 先把日常第一个模型放进变量, 再 UPDATE. 禁止在 UPDATE config 的同时 FROM config, MySQL 会 1093.
SET @knowldge_space_llm = (
  SELECT JSON_OBJECT('id', JSON_EXTRACT(CAST(value AS JSON), '$.models[0].id'))
  FROM config
  WHERE `key` = 'workstation'
);

UPDATE config
SET value = JSON_SET(CAST(value AS JSON), '$.knowledge_space_llm', CAST(@knowldge_space_llm AS JSON))
WHERE `key` = 'linsight_llm';

UPDATE config
SET value = JSON_SET(CAST(value AS JSON), '$.chat_title_llm', CAST(@knowldge_space_llm AS JSON))
WHERE `key` = 'linsight_llm';

UPDATE message_session SET name = flow_name WHERE name IS NULL;

INSERT INTO `roleaccess` (`role_id`, `type`, `third_id`)
SELECT r.id, 99, 'knowledge_space'
FROM role r
WHERE NOT EXISTS (
  SELECT 1 FROM roleaccess a
  WHERE a.role_id = r.id AND a.type = 99 AND a.third_id = 'knowledge_space'
);

-- 升级库不会走 2.4 启动时的 create_all (Redis init_default_data 已存在). 列用 varchar, 兼容官方 SPACE 与模型 space.
CREATE TABLE IF NOT EXISTS space_channel_member (
  id int NOT NULL AUTO_INCREMENT COMMENT '主键',
  business_id char(36) NOT NULL COMMENT '业务ID, 知识空间为 knowledge.id',
  business_type varchar(32) NOT NULL COMMENT 'SPACE 或 CHANNEL',
  user_id int NOT NULL COMMENT '用户ID',
  user_role varchar(32) NOT NULL COMMENT 'CREATOR/ADMIN/MEMBER',
  status varchar(32) NOT NULL DEFAULT 'ACTIVE' COMMENT '成员状态',
  is_pinned tinyint(1) NOT NULL DEFAULT 0 COMMENT '是否置顶',
  create_time datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time datetime NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY ix_space_channel_member_business_id (business_id),
  KEY ix_space_channel_member_business_type (business_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识空间或频道成员';
