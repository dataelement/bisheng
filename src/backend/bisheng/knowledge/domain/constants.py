import json
import re
from typing import Any

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


def normalize_business_domain_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    if re.fullmatch(r"[A-Z0-9_]{1,16}", code):
        return code
    return None


def get_business_domain_code_from_split_rule(split_rule: Any) -> str | None:
    if isinstance(split_rule, str) and split_rule.strip():
        try:
            split_rule = json.loads(split_rule)
        except Exception:
            return None
    if not isinstance(split_rule, dict):
        return None
    return normalize_business_domain_code(split_rule.get(BUSINESS_DOMAIN_CODE_KEY))


def parse_shougang_file_encoding_codes(item: Any) -> tuple[str, str]:
    """Parse the existing Shougang ``category-domain-serial`` tail."""
    if isinstance(item, dict):
        encoding = str(
            item.get("file_encoding")
            or item.get("fileEncoding")
            or item.get("document_code")
            or item.get("file_no")
            or ""
        )
    else:
        encoding = str(getattr(item, "file_encoding", "") or "")
    parts = [part.strip() for part in encoding.split("-") if part.strip()]
    if len(parts) < 4:
        return "", ""
    business_index = len(parts) - 1
    while business_index >= 0 and re.fullmatch(r"\d{3,}", parts[business_index]):
        business_index -= 1
    document_index = business_index - 1
    if document_index < 0:
        return "", ""
    business_domain_code = normalize_business_domain_code(parts[business_index])
    if not business_domain_code:
        return "", ""
    document_code = str(parts[document_index]).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{1,16}", document_code):
        document_code = ""
    return document_code, business_domain_code


def get_business_domain_code_from_file(item: Any) -> str | None:
    split_rule = item.get("split_rule") if isinstance(item, dict) else getattr(item, "split_rule", None)
    return get_business_domain_code_from_split_rule(split_rule) or parse_shougang_file_encoding_codes(item)[1]
