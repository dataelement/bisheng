"""校验 G1–G7 系统默认名与产品文案一致。"""

from bisheng.points.domain.constants.seed_rules import SEED_RULES, seed_default_name

# 产品给定的获取类规则默认名（point_rule.name）
EXPECTED_G_DEFAULT_NAMES = {
    "G1": "发布/上传文档到公共库",
    "G2": "发布/上传文档到部门库",
    "G3": "文档被收藏",
    "G4": "问答被采纳",
    "G5": "发布/上传文档团队库",
    "G6": "发布/上传文档科室库",
    "G7": "知识分享",
}


def test_seed_rules_g1_g7_default_names_match_product_copy():
    """SEED_RULES 中 G1–G7 的 name 必须与产品文案一致。"""
    by_code = {r["rule_code"]: r["name"] for r in SEED_RULES}
    for code, expected in EXPECTED_G_DEFAULT_NAMES.items():
        assert by_code.get(code) == expected, f"{code} seed name mismatch"
        assert seed_default_name(code) == expected
        assert len(expected) <= 40
