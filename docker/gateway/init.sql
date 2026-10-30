-- MySQL deployment schema from bisheng-gateway v1.8.0 (2995df6f), covering
-- init.sql, update_v_1.0.sql and update_v_2.5.sql. Existing tables are preserved.
CREATE DATABASE IF NOT EXISTS bisheng_gateway
    CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE bisheng_gateway;

CREATE TABLE IF NOT EXISTS gt_group_resource (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_id INT NOT NULL,
    resource_id VARCHAR(256) NOT NULL,
    resource_limit INT NOT NULL DEFAULT 0,
    resource_type TINYINT NOT NULL
);
CREATE TABLE IF NOT EXISTS gt_sensitive_words (
    id INT AUTO_INCREMENT PRIMARY KEY,
    resource_id VARCHAR(256) NOT NULL,
    resource_type TINYINT,
    auto_words TEXT,
    words TEXT,
    words_types VARCHAR(32),
    is_check TINYINT NOT NULL DEFAULT 0,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    logic_delete TINYINT NOT NULL DEFAULT 0,
    auto_reply VARCHAR(128)
);
CREATE TABLE IF NOT EXISTS gt_user_group (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_name VARCHAR(256) NOT NULL,
    admin_user VARCHAR(512),
    admin_user_id VARCHAR(512),
    group_limit INT NOT NULL DEFAULT 0,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    logic_delete TINYINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gt_block_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chat_id VARCHAR(64),
    user_input TEXT,
    system_out TEXT,
    block_words TEXT,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL,
    resource_id VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS gt_department (
    id INT PRIMARY KEY,
    dept_name VARCHAR(256) NOT NULL,
    dept_limit INT NOT NULL DEFAULT 0,
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS gt_department_resource (
    id INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    resource_id VARCHAR(256) NOT NULL,
    resource_limit INT NOT NULL DEFAULT 0,
    resource_type TINYINT NOT NULL,
    INDEX idx_dept_resource (department_id, resource_id)
);
