CREATE DATABASE IF NOT EXISTS `bisheng_gateway` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

USE `bisheng_gateway`;

CREATE TABLE IF NOT EXISTS `gt_group_resource`
(
    `id`             int auto_increment primary key,
    `group_id`       int           not null,
    `resource_id`    varchar(256)  not null,
    `resource_limit` int default 0 not null,
    `resource_type`  tinyint       not null
);

CREATE TABLE IF NOT EXISTS `gt_sensitive_words`
(
    `id`            int auto_increment primary key,
    `resource_id`   varchar(256)      not null,
    `resource_type` tinyint           null,
    `auto_words`    text              null,
    `words`         text              null,
    `words_types`   varchar(32)       null,
    `is_check`      tinyint default 0 not null,
    `create_time`   datetime          not null,
    `update_time`   datetime          not null,
    `logic_delete`  tinyint default 0 not null,
    `auto_reply`    varchar(128)      null
);

CREATE TABLE IF NOT EXISTS `gt_user_group`
(
    `id`            int auto_increment primary key,
    `group_name`    varchar(256)      not null,
    `admin_user`    varchar(512)      null,
    `admin_user_id` varchar(512)      null,
    `group_limit`   int     default 0 not null,
    `create_time`   datetime          not null,
    `update_time`   datetime          not null,
    `logic_delete`  tinyint default 0 not null
);

CREATE TABLE IF NOT EXISTS `gt_block_record`
(
    `id`          int auto_increment primary key,
    `chat_id`     varchar(64) null,
    `user_input`  text        null,
    `system_out`  text        null,
    `block_words` text        null,
    `create_time` datetime    not null,
    `update_time` datetime    not null,
    `resource_id` varchar(64) null
);
