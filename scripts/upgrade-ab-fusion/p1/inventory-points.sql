-- 积分只读盘点（2.5 才有表）。无 DDL。
-- 表：user_point_account / user_point_log（用户账，D11b 要迁）
--     point_rule（规则，另定覆盖还是留 hop 种子）
--     其余为派生/队列，先计数不迁。
SET NAMES utf8mb4;

SELECT 'POINTS_ACCOUNT' AS section;
SELECT COUNT(*) AS account_rows,
       COUNT(DISTINCT user_id) AS users_with_account,
       SUM(balance) AS balance_sum,
       SUM(lifetime_earned) AS earned_sum,
       SUM(lifetime_deducted) AS deducted_sum,
       SUM(CASE WHEN balance <> 0 THEN 1 ELSE 0 END) AS nonzero_balance_rows
FROM user_point_account;

SELECT 'POINTS_LOG' AS section;
SELECT COUNT(*) AS log_rows,
       COUNT(DISTINCT user_id) AS users_with_log,
       MIN(occurred_at) AS first_occurred_at,
       MAX(occurred_at) AS last_occurred_at
FROM user_point_log;

SELECT 'POINTS_LOG_BY_SOURCE' AS section;
SELECT source, direction, COUNT(*) AS cnt, SUM(delta) AS delta_sum
FROM user_point_log
GROUP BY source, direction
ORDER BY cnt DESC;

SELECT 'POINTS_RULE' AS section;
SELECT COUNT(*) AS rule_rows,
       SUM(CASE WHEN status = 'enabled' THEN 1 ELSE 0 END) AS enabled_cnt
FROM point_rule;

SELECT 'POINTS_RULE_CODES' AS section;
SELECT tenant_id, rule_code, status, display_name FROM point_rule ORDER BY tenant_id, rule_code;

SELECT 'POINTS_OTHER' AS section;
SELECT
  (SELECT COUNT(*) FROM point_copy) AS point_copy_cnt,
  (SELECT COUNT(*) FROM point_rank_snapshot) AS rank_snapshot_cnt,
  (SELECT COUNT(*) FROM point_favorite_tier_award) AS favorite_tier_award_cnt,
  (SELECT COUNT(*) FROM point_sync_outbox) AS sync_outbox_cnt;
