
ALTER TABLE knowledge_space_tag_library
ADD COLUMN ai_tags JSON COMMENT 'AI生成的标签',
ADD COLUMN ai_tag_count INT DEFAULT 0 COMMENT 'AI标签数量';


ALTER TABLE tag
ADD COLUMN resource_type VARCHAR(60) NOT NULL DEFAULT 'manual_tag' COMMENT '资源类型';

update config set value = '{"system_prompt": "# \u89d2\u8272\n\u4f60\u662f\u4e00\u4e2a\u4e25\u8c28\u7684AI\u95ee\u7b54\u52a9\u624b\uff0c\u4f60\u7684\u4efb\u52a1\u662f\u6839\u636e\u7528\u6237\u95ee\u9898\u4ee5\u53ca\u76f8\u5173\u8d44\u6599\u8fdb\u884c\u56de\u7b54\u3002\n\u5728\u56de\u7b54\u65f6\uff0c\u8bf7\u6ce8\u610f\u4ee5\u4e0b\u51e0\u70b9\uff1a\n1. \u8bf7\u4f7f\u7528\u7528\u6237\u6240\u4f7f\u7528\u7684\u8bed\u8a00\u8fdb\u884c\u56de\u7b54\u3002\n2. \u5f53\u3010\u53c2\u8003\u8d44\u6599\u3011\u4e2d\u6709\u660e\u786e\u4e0e\u95ee\u9898\u76f8\u5173\u7684\u4fe1\u606f\u65f6\u624d\u8fdb\u884c\u56de\u7b54\uff0c\u4fdd\u6301\u7b54\u6848\u4e25\u8c28\u3001\u4e13\u4e1a\uff0c\u4e0d\u5141\u8bb8\u81ea\u884c\u63a8\u6d4b\uff0c\u5728\u56de\u7b54\u4e2d\u6807\u6ce8\u53c2\u8003\u8d44\u6599\u51fa\u5904\u3002\u5982\u679c\u4e0d\u540c\u7684\u53c2\u8003\u6765\u6e90\u6709\u5dee\u5f02\u751a\u81f3\u51b2\u7a81\uff0c\u5219\u5e94\u90fd\u5217\u4e3e\u51fa\u6765\u3002\n3. \u5982\u679c\u3010\u53c2\u8003\u8d44\u6599\u3011\u4e0e\u7528\u6237\u95ee\u9898\u65e0\u5173\uff0c\u5219\u56de\u590d\u201c\u6ca1\u6709\u627e\u5230\u76f8\u5173\u5185\u5bb9\u201d\u6216\u662f\u201cno content found\"\u3002\n4. \u82e5\u6587\u7ae0\u5185\u5bb9\u4e2d\u5305\u542b\u56fe\u7247\u5f15\u7528\uff08\u4f8b\u5982\uff1a![image](\u8def\u5f84/IMAGE_1.png)\uff09\uff0c\u8bf7\u4ecd\u7136\u4f7f\u7528 Markdown \u683c\u5f0f\u6e32\u67d3\u56fe\u7247\uff0c\u4e0d\u8981\u4fee\u6539\u6216\u5220\u9664\u3002\n5. \u5f53\u524d\u65f6\u95f4\u662f{cur_date}\u3002", "user_prompt": "# \u53c2\u8003\u8d44\u6599\n```\n{retrieved_file_content}\n```\n# \u7528\u6237\u95ee\u9898\n{question}", "max_chunk_size": 15000, "auto_tag_visible": true, "review_tag_visible": true}'
where key = "workstation_knowledge_space";

update tag set resource_type = 'system_tag'
where name in ("政策制度", "产品资料", "技术文档", "项目资料", "财务资料", "人力资源", "市场销售", "客户案例", "培训资料", "其他");

DROP TABLE IF EXISTS `review_tag_link`;
CREATE TABLE `review_tag_link` (
  `tag_id` int NOT NULL,
  `resource_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `resource_type` int NOT NULL,
  `user_id` int NOT NULL,
  `tenant_id` int NOT NULL DEFAULT '1' COMMENT 'Tenant ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` int NOT NULL AUTO_INCREMENT,
  `is_deleted` tinyint DEFAULT '0',
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `resource_tag_uniq` (`resource_id`,`resource_type`,`tag_id`),
  KEY `ix_taglink_tenant_id` (`tenant_id`),
  KEY `ix_taglink_tag_id` (`tag_id`),
  KEY `ix_taglink_id` (`id`),
  KEY `ix_taglink_create_time` (`create_time`),
  KEY `idx_taglink_tenant_id` (`tenant_id`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


DROP TABLE IF EXISTS `review_tag`;
CREATE TABLE `review_tag` (
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `business_type` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `business_id` varchar(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `resource_type` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_id` int NOT NULL,
  `tenant_id` int NOT NULL DEFAULT '1' COMMENT 'Tenant ID',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `id` int NOT NULL AUTO_INCREMENT,
  `is_deleted` tinyint DEFAULT '0',
  `review_status` tinyint DEFAULT '0',
  `reject_reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `review_time` datetime DEFAULT NULL,
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_tag_id` (`id`),
  KEY `ix_tag_create_time` (`create_time`),
  KEY `ix_tag_tenant_id` (`tenant_id`),
  KEY `ix_tag_name` (`name`),
  KEY `idx_tag_tenant_id` (`tenant_id`)
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;