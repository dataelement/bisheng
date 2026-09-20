-- 融合控制表, 建在 A 的 bisheng 库. 批次回滚只按这些表删除本批 INSERT 的资源.
-- 不给业务表加列, 避免改 A 原 schema.

CREATE TABLE IF NOT EXISTS fusion_batch (
  id BIGINT NOT NULL AUTO_INCREMENT,
  batch_no VARCHAR(64) NOT NULL,
  phase VARCHAR(32) NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL DEFAULT 'open',
  note VARCHAR(512) NULL,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_batch_no (batch_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='B到A融合批次';

CREATE TABLE IF NOT EXISTS fusion_map (
  id BIGINT NOT NULL AUTO_INCREMENT,
  batch_no VARCHAR(64) NOT NULL,
  entity VARCHAR(32) NOT NULL COMMENT 'user/dept/group/role/tenant/knowledge/file/flow/...',
  src_id VARCHAR(64) NOT NULL COMMENT 'B 源 ID',
  dst_id VARCHAR(64) NOT NULL COMMENT 'A 目标 ID',
  action VARCHAR(32) NOT NULL DEFAULT '',
  note VARCHAR(512) NULL,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_map (batch_no, entity, src_id),
  KEY idx_fusion_map_entity_dst (entity, dst_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='B到A ID 映射';

CREATE TABLE IF NOT EXISTS fusion_exception (
  id BIGINT NOT NULL AUTO_INCREMENT,
  batch_no VARCHAR(64) NOT NULL,
  kind VARCHAR(64) NOT NULL,
  src_entity VARCHAR(32) NULL,
  src_id VARCHAR(64) NULL,
  detail TEXT NULL,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_fusion_exc_batch (batch_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='融合例外/人工项';

CREATE TABLE IF NOT EXISTS fusion_a_baseline (
  id BIGINT NOT NULL AUTO_INCREMENT,
  captured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  metric VARCHAR(64) NOT NULL,
  value_num BIGINT NULL,
  value_txt VARCHAR(512) NULL,
  PRIMARY KEY (id),
  KEY idx_fusion_base_metric (metric, captured_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='A 保护基线计数';
