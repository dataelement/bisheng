-- hop 2.3-beta1：知识库/文件元数据。幂等：列已存在则跳过（由 shell 调 ADD）。
-- 官方文档：升级到 2.3.0-beta1
-- 禁止：在 2.5 容器里跑 convert_all 替代本步。

-- 以下 UPDATE 可重跑。
UPDATE knowledgefile SET user_metadata = extra_meta
WHERE extra_meta IS NOT NULL AND user_metadata IS NULL;

UPDATE knowledgefile f
JOIN `user` u ON f.user_id = u.user_id
SET f.user_name = u.user_name
WHERE f.user_id IS NOT NULL AND (f.user_name IS NULL OR f.user_name = '');

UPDATE knowledgefile
SET updater_id = user_id
WHERE updater_id IS NULL AND user_id IS NOT NULL;

UPDATE knowledgefile f
JOIN `user` u ON f.updater_id = u.user_id
SET f.updater_name = u.user_name
WHERE f.updater_id IS NOT NULL AND (f.updater_name IS NULL OR f.updater_name = '');
