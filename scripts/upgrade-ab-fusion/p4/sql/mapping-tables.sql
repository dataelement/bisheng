-- 融合映射表。落在 B 的 bisheng 库。无业务外键，仅追溯。P4 起用。
CREATE TABLE IF NOT EXISTS fusion_batch (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '批次主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '迁移批次号',
  phase VARCHAR(32) NOT NULL COMMENT 'p4_identity / p5_space / p6_incr',
  status VARCHAR(16) NOT NULL DEFAULT 'open' COMMENT 'open/applied/verified/rolled_back',
  note VARCHAR(512) NULL COMMENT '备注',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_batch_no (batch_no)
) COMMENT='融合批次';

CREATE TABLE IF NOT EXISTS fusion_user_map (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_user_id INT NOT NULL COMMENT 'A 环境 user_id',
  b_user_id INT NOT NULL COMMENT 'B 环境 user_id，接管后保持不变',
  employee_code VARCHAR(255) NULL COMMENT '首钢员工编码',
  action VARCHAR(32) NOT NULL COMMENT 'takeover/create_on_b/keep_local/skip',
  a_source VARCHAR(32) NULL COMMENT 'A 的 source：local/sg，双行须映到同一 b_user_id',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_a_user (a_user_id),
  KEY idx_fusion_b_user (b_user_id)
) COMMENT='A用户到B用户映射';

CREATE TABLE IF NOT EXISTS fusion_dept_map (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_dept_pk INT NOT NULL COMMENT 'A department.id',
  b_dept_pk INT NULL COMMENT 'B department.id，未建则为空',
  external_id VARCHAR(128) NULL COMMENT '部门外部编码',
  action VARCHAR(32) NOT NULL COMMENT 'bind/create/keep/skip',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_a_dept (a_dept_pk)
) COMMENT='A部门到B部门映射';
