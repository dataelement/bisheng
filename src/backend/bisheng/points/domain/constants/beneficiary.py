"""按规则编码约束可配置的积分受益人。"""

BENEFICIARY_OPTIONS = {
    "G1": ("uploader", "publisher"), "G2": ("uploader", "publisher"),
    "G5": ("uploader", "publisher"), "G6": ("uploader", "publisher"),
    "G7": ("uploader", "sharer"), "G3": ("uploader",), "G4": ("answerer",),
}


def allowed_beneficiaries(rule_code: str) -> tuple[str, ...]:
    """返回规则允许的受益人；月奖固定为事件主体。"""
    return ("subject",) if rule_code.startswith("M") else BENEFICIARY_OPTIONS.get(rule_code, ())
