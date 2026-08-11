"""积分站内信模板；文案随代码发布，不允许后台动态修改。"""

NOTIFY_TEMPLATES = {
    "earn_publish": "你因「{rule_name}」获得 {delta} 积分。",
    "earn_share": "你因知识库间分享获得 {delta} 积分。",
    "earn_favorite": "你的文档被收藏，获得 {delta} 积分。",
    "earn_adopt": "你的回答被采纳，获得 {delta} 积分。",
    "deduct_admin": "因「{rule_name}」扣减 {delta} 积分。原因：{reason}",
    "adjust_admin": "管理员调整了你的积分 {delta}。原因：{reason}",
}
POINTS_CHANGED_ACTION_CODE = "points_changed"
