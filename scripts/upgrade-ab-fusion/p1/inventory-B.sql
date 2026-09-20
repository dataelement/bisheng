-- P1 B（2.2 侧，只读）。在 B 的 bisheng 库执行。
SELECT 'B_USER_COUNTS' AS section;
SELECT COUNT(*) AS user_total,
       SUM(CASE WHEN `delete` = 0 THEN 1 ELSE 0 END) AS user_active
FROM `user`;

SELECT 'B_USER_DUP_NAME' AS section;
SELECT user_name, COUNT(*) AS cnt FROM `user` GROUP BY user_name HAVING COUNT(*) > 1;

SELECT 'B_FLOW' AS section;
SELECT flow_type, COUNT(*) AS cnt FROM flow GROUP BY flow_type;

SELECT 'B_KNOWLEDGE_BY_TYPE' AS section;
SELECT type, COUNT(*) AS knowledge_cnt FROM knowledge GROUP BY type;

SELECT 'B_KNOWLEDGE_TYPE2' AS section;
SELECT k.id, k.name, k.type, k.user_id, k.state,
       (SELECT COUNT(*) FROM knowledgefile f WHERE f.knowledge_id = k.id) AS file_cnt
FROM knowledge k
WHERE k.type = 2
ORDER BY k.id;

SELECT 'B_KNOWLEDGEFILE' AS section;
SELECT COUNT(*) AS file_total FROM knowledgefile;

SELECT 'B_SESSION' AS section;
SELECT (SELECT COUNT(*) FROM message_session) AS session_cnt,
       (SELECT COUNT(*) FROM chatmessage) AS chatmessage_cnt;

SELECT 'B_ORPHAN' AS section;
SELECT
  (SELECT COUNT(*) FROM flow f LEFT JOIN `user` u ON f.user_id = u.user_id
     WHERE f.user_id IS NOT NULL AND u.user_id IS NULL) AS orphan_flow,
  (SELECT COUNT(*) FROM knowledge k LEFT JOIN `user` u ON k.user_id = u.user_id
     WHERE k.user_id IS NOT NULL AND u.user_id IS NULL) AS orphan_knowledge;

SELECT 'B_USER_LIST' AS section;
SELECT user_id, user_name, email, phone_number, `delete`, create_time
FROM `user`
ORDER BY user_id;
