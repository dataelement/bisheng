"""积分规则与说明文案种子。

默认启用（系统内置）：
- G1–G4：获取类内置规则
- M1 / M4 / M6：月奖内置规则
- R1–R3：扣减默认规则

其余 G5–G7、M2/M3/M5/M7/M8 仍入库，默认 disabled，可由运营启用。
迁移补种按 rule_code 幂等插入；状态同步见 f080。
"""

# --- 获取 G* ---
SEED_RULES = [
    {
        "rule_code": "G1",
        "rule_type": "earn",
        "name": "发布/上传到公共库",
        "score_expr": {"mode": "fixed", "score": 3},
        "daily_cap": 15,
        "beneficiary": "uploader",
        "status": "enabled",
        "sort_order": 1,
    },
    {
        "rule_code": "G2",
        "rule_type": "earn",
        "name": "发布/上传到部门库",
        "score_expr": {"mode": "fixed", "score": 2},
        "daily_cap": 10,
        "beneficiary": "uploader",
        "status": "enabled",
        "sort_order": 2,
    },
    # G3：终身档位上限在 score_expr.lifetime_cap；daily_cap 不承载终身 15（P3）。
    {
        "rule_code": "G3",
        "rule_type": "earn",
        "name": "文档被收藏",
        "score_expr": {
            "mode": "tier",
            "tiers": [
                {"threshold": 75, "score": 5},
                {"threshold": 150, "score": 10},
                {"threshold": 300, "score": 15},
            ],
            "lifetime_cap": 15,
        },
        "daily_cap": None,
        "beneficiary": "uploader",
        "status": "enabled",
        "sort_order": 3,
    },
    {
        "rule_code": "G4",
        "rule_type": "earn",
        "name": "问答被采纳",
        "score_expr": {"mode": "fixed", "score": 3},
        "daily_cap": 15,
        "beneficiary": "answerer",
        "status": "enabled",
        "sort_order": 4,
    },
    {
        "rule_code": "G5",
        "rule_type": "earn",
        "name": "上传团队库文档",
        "score_expr": {"mode": "fixed", "score": 2},
        "daily_cap": 10,
        "beneficiary": "uploader",
        "status": "disabled",
        "sort_order": 5,
    },
    {
        "rule_code": "G6",
        "rule_type": "earn",
        "name": "上传科室库文档",
        "score_expr": {"mode": "fixed", "score": 2},
        "daily_cap": 10,
        "beneficiary": "uploader",
        "status": "disabled",
        "sort_order": 6,
    },
    {
        "rule_code": "G7",
        "rule_type": "earn",
        "name": "知识分享",
        "score_expr": {"mode": "fixed", "score": 2},
        "daily_cap": 10,
        "beneficiary": "uploader",
        "status": "disabled",
        "sort_order": 7,
    },
    # --- 扣减 R*（系统默认）---
    {
        "rule_code": "R1",
        "rule_type": "deduct",
        "name": "色情低俗/暴力违法",
        "score_expr": {"mode": "fixed", "score": 100},
        "daily_cap": None,
        "beneficiary": None,
        "status": "enabled",
        "sort_order": 21,
    },
    {
        "rule_code": "R2",
        "rule_type": "deduct",
        "name": "不当言论",
        "score_expr": {"mode": "fixed", "score": 100},
        "daily_cap": None,
        "beneficiary": None,
        "status": "enabled",
        "sort_order": 22,
    },
    {
        "rule_code": "R3",
        "rule_type": "deduct",
        "name": "其他违反规范",
        "score_expr": {"mode": "fixed", "score": 100},
        "daily_cap": None,
        "beneficiary": None,
        "status": "enabled",
        "sort_order": 23,
    },
    # --- 月奖 M*：仅 M1/M4/M6 默认启用 ---
    {
        "rule_code": "M1",
        "rule_type": "admin_reward",
        "name": "公共库所有者月奖",
        "score_expr": {"mode": "fixed", "score": 200},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "enabled",
        "sort_order": 31,
    },
    {
        "rule_code": "M2",
        "rule_type": "admin_reward",
        "name": "公共库管理员月奖",
        "score_expr": {"mode": "fixed", "score": 150},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "disabled",
        "sort_order": 32,
    },
    {
        "rule_code": "M3",
        "rule_type": "admin_reward",
        "name": "部门库所有者月奖",
        "score_expr": {"mode": "fixed", "score": 120},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "disabled",
        "sort_order": 33,
    },
    {
        "rule_code": "M4",
        "rule_type": "admin_reward",
        "name": "部门库管理员月奖",
        "score_expr": {"mode": "fixed", "score": 100},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "enabled",
        "sort_order": 34,
    },
    {
        "rule_code": "M5",
        "rule_type": "admin_reward",
        "name": "科室库所有者月奖",
        "score_expr": {"mode": "fixed", "score": 80},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "disabled",
        "sort_order": 35,
    },
    {
        "rule_code": "M6",
        "rule_type": "admin_reward",
        "name": "科室库管理员月奖",
        "score_expr": {"mode": "fixed", "score": 50},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "enabled",
        "sort_order": 36,
    },
    {
        "rule_code": "M7",
        "rule_type": "admin_reward",
        "name": "团队库所有者月奖",
        "score_expr": {"mode": "fixed", "score": 70},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "disabled",
        "sort_order": 37,
    },
    {
        "rule_code": "M8",
        "rule_type": "admin_reward",
        "name": "团队库管理员月奖",
        "score_expr": {"mode": "fixed", "score": 40},
        "daily_cap": None,
        "beneficiary": "subject",
        "status": "disabled",
        "sort_order": 38,
    },
]

# 系统默认启用的编码（便于迁移/脚本对齐）。
DEFAULT_ENABLED_RULE_CODES = frozenset({"G1", "G2", "G3", "G4", "R1", "R2", "R3", "M1", "M4", "M6"})

# 种子入库时展示名与默认名一致；运营后续只改 display_name。
for _seed in SEED_RULES:
    _seed["display_name"] = _seed["name"]


def seed_default_name(rule_code: str) -> str | None:
    """按规则编码取种子默认名；未知编码返回 None。"""
    code = (rule_code or "").strip().upper()
    for row in SEED_RULES:
        if row["rule_code"] == code:
            return str(row["name"])
    return None


# Single rich-text guide for the public rules modal (Portal admin edits `guide` only).
SEED_COPIES = [
    {
        "copy_key": "guide",
        "content": (
            "<p><strong>1. 积分获取：</strong>用户通过发布优质内容、参与互动等方式获取积分，"
            "每日设有上限，防止刷分行为。</p>"
            "<p><strong>2. 积分扣减：</strong>对于违反平台规范的行为，将扣除相应积分作为惩戒，"
            "严重违规将额外处理。</p>"
            "<p><strong>3. 管理员奖励：</strong>不同层级的管理员根据其管理职责，每月可获得固定积分奖励。</p>"
            "<p><strong>4. 积分用途：</strong>本平台积分会定期发送到协同办公平台，用于党群礼物兑换。</p>"
            "<p><strong>5. 申诉机制：</strong>如对积分变动有异议，可在7个工作日内向管理员提出申诉。</p>"
        ),
        "sort_order": 1,
    },
]
