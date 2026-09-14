-- 知识空间 ID 映射。A 主键不得写入 B 原值。
CREATE TABLE IF NOT EXISTS fusion_space_map (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_space_id INT NOT NULL COMMENT 'A knowledge.id（type=3）',
  b_space_id INT NULL COMMENT 'B 新空间 id',
  status VARCHAR(16) NOT NULL DEFAULT 'planned' COMMENT 'planned/hidden/indexed/verified/published/rolled_back',
  note VARCHAR(512) NULL COMMENT '冲突或后缀说明',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_a_space (a_space_id)
) COMMENT='知识空间映射';

CREATE TABLE IF NOT EXISTS fusion_file_map (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_file_id INT NOT NULL COMMENT 'A knowledgefile.id',
  b_file_id INT NULL COMMENT 'B 新文件 id',
  src_object_key VARCHAR(512) NULL COMMENT 'A MinIO 对象键',
  dst_object_key VARCHAR(512) NULL COMMENT 'B MinIO 对象键',
  size_bytes BIGINT NULL COMMENT '字节数',
  content_sha256 CHAR(64) NULL COMMENT '内容哈希',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_a_file (a_file_id)
) COMMENT='知识空间文件与对象映射';

CREATE TABLE IF NOT EXISTS fusion_exception (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_space_id INT NULL COMMENT 'A 知识空间 id',
  a_file_id INT NULL COMMENT 'A 文件 id, 空间级例外可空',
  kind VARCHAR(32) NOT NULL COMMENT '例外类型: owner_unmapped/dept_unmapped/violation/name_suffix/minio_missing/tag_unmapped/relation_unmapped/points_unmapped',
  detail VARCHAR(1024) NULL COMMENT '例外说明',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_fusion_exc_batch (batch_no),
  KEY idx_fusion_exc_space (a_space_id)
) COMMENT='融合例外清单, 不阻断用户成员时记录部门授权等残留';

CREATE TABLE IF NOT EXISTS fusion_document_map (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_doc_id INT NOT NULL COMMENT 'A knowledge_document.id',
  b_doc_id INT NOT NULL COMMENT 'B 新文档 id',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_a_doc (a_doc_id)
) COMMENT='知识文档映射, 供收藏引用回写';

CREATE TABLE IF NOT EXISTS fusion_tag_map (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  batch_no VARCHAR(64) NOT NULL COMMENT '批次号',
  a_tag_id INT NOT NULL COMMENT 'A knowledge_space_tag_library.id',
  b_tag_id INT NOT NULL COMMENT 'B 标签库 id',
  action VARCHAR(32) NOT NULL COMMENT 'bind/create/create_private',
  name VARCHAR(200) NULL COMMENT '标签库名称',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fusion_a_tag (a_tag_id)
) COMMENT='标签库映射';
