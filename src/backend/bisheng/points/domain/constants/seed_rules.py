"""积分规则与说明文案种子，迁移仅在租户为空时写入。"""

SEED_RULES = [
    {"rule_code": "G1", "rule_type": "earn", "name": "上传公共库文档", "score_expr": {"mode": "fixed", "score": 3}, "daily_cap": 15, "beneficiary": "uploader", "sort_order": 1},
    {"rule_code": "G2", "rule_type": "earn", "name": "上传部门库文档", "score_expr": {"mode": "fixed", "score": 2}, "daily_cap": 10, "beneficiary": "uploader", "sort_order": 2},
    # G3：终身档位上限在 score_expr.lifetime_cap；daily_cap 不承载终身 15（P3）。
    {"rule_code": "G3", "rule_type": "earn", "name": "文档被收藏", "score_expr": {"mode": "tier", "tiers": [{"threshold": 75, "score": 5}, {"threshold": 150, "score": 10}, {"threshold": 300, "score": 15}], "lifetime_cap": 15}, "daily_cap": None, "beneficiary": "uploader", "sort_order": 3},
    {"rule_code": "G4", "rule_type": "earn", "name": "回答被采纳", "score_expr": {"mode": "fixed", "score": 3}, "daily_cap": 15, "beneficiary": "answerer", "sort_order": 4},
    # G5/G6/G7：可增项规则；团队库/科室库入库与库间分享（非外链）。
    {"rule_code": "G5", "rule_type": "earn", "name": "上传团队库文档", "score_expr": {"mode": "fixed", "score": 2}, "daily_cap": 10, "beneficiary": "uploader", "sort_order": 5},
    {"rule_code": "G6", "rule_type": "earn", "name": "上传科室库文档", "score_expr": {"mode": "fixed", "score": 2}, "daily_cap": 10, "beneficiary": "uploader", "sort_order": 6},
    {"rule_code": "G7", "rule_type": "earn", "name": "文档库间分享", "score_expr": {"mode": "fixed", "score": 2}, "daily_cap": 10, "beneficiary": "uploader", "sort_order": 7},
    *[{"rule_code": f"R{i}", "rule_type": "deduct", "name": f"违规扣减 R{i}", "score_expr": {"mode": "fixed", "score": 100}, "daily_cap": None, "beneficiary": None, "sort_order": 20 + i} for i in range(1, 4)],
    {"rule_code": "M1", "rule_type": "admin_reward", "name": "公共库所有者月奖", "score_expr": {"mode": "fixed", "score": 200}, "daily_cap": None, "beneficiary": "subject", "sort_order": 31},
    {"rule_code": "M4", "rule_type": "admin_reward", "name": "部门管理员月奖", "score_expr": {"mode": "fixed", "score": 100}, "daily_cap": None, "beneficiary": "subject", "sort_order": 34},
    {"rule_code": "M6", "rule_type": "admin_reward", "name": "科室管理员月奖", "score_expr": {"mode": "fixed", "score": 50}, "daily_cap": None, "beneficiary": "subject", "sort_order": 36},
]

SEED_COPIES = [
    {"copy_key": "earn_intro", "content": "贡献知识可获得积分。", "sort_order": 1},
    {"copy_key": "deduct_intro", "content": "违规行为可按规则扣减积分。", "sort_order": 2},
    {"copy_key": "admin_reward_intro", "content": "管理员月度奖励按上月角色与活跃情况发放。", "sort_order": 3},
    {"copy_key": "usage", "content": "积分用于展示贡献与激励排名。", "sort_order": 4},
    {"copy_key": "appeal", "content": "如有疑问，请线下联系管理员。", "sort_order": 5},
]
