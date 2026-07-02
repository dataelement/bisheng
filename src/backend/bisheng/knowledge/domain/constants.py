import re
from typing import Any, Optional


BUSINESS_DOMAIN_CODE_KEY = "business_domain_code"

BUSINESS_DOMAIN_OPTIONS = {
    "PP": "生产",
    "QM": "质量",
    "PM": "设备",
    "EM": "能源",
    "SA": "安全",
    "EN": "环保",
    "IM": "投资",
    "RD": "研发",
    "MM": "采购",
    "SD": "营销",
    "FI": "财务",
    "HR": "人力",
    "IT": "信息",
    "AD": "管理",
}

BUSINESS_DOMAIN_CODES = frozenset(BUSINESS_DOMAIN_OPTIONS.keys())


def normalize_business_domain_code(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    if re.fullmatch(r"[A-Z0-9_]{1,16}", code):
        return code
    return None
