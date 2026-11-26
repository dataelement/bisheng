"""Allowlisted quota facts, never the Kubernetes response or resource names."""

import re

RESOURCE_KEYS = frozenset(
    {
        "cpu",
        "memory",
        "requests.cpu",
        "limits.cpu",
        "requests.memory",
        "limits.memory",
        "requests.storage",
        "pods",
        "count/pods",
        "persistentvolumeclaims",
        "count/persistentvolumeclaims",
    }
)
_QUANTITY = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+|[EPTGMKk]i?|[mun])?")
_SECTIONS = re.compile(
    r"\bexceeded quota:\s*[^,\r\n]{1,253},\s*requested:\s*(.+?),\s*used:\s*(.+?),\s*limited:\s*([^\r\n]+)",
    re.IGNORECASE,
)


def safe_quota(value):
    """Keep only bounded quantities for resources with a known public meaning."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for resource in sorted(RESOURCE_KEYS):
        item = value.get(resource)
        if not isinstance(item, dict):
            continue
        quantities = {key: item.get(key) for key in ("requested", "used", "limit")}
        if all(isinstance(x, str) and len(x) <= 32 and _QUANTITY.fullmatch(x) for x in quantities.values()):
            result[resource] = quantities
    return result


def quota_from_response(response):
    """Native admission and KubeSphere wrap the same exceeded-quota message.

    A Forbidden status alone proves no quota failure. Names, arbitrary messages,
    headers and every non-quantity response field are deliberately discarded.
    """
    if response.status_code != 403 or len(response.content) > 16384:
        return {}
    try:
        status = response.json()
    except (ValueError, UnicodeError):
        return {}
    if not isinstance(status, dict) or status.get("kind") != "Status" or status.get("reason") != "Forbidden":
        return {}
    message = status.get("message")
    if not isinstance(message, str) or len(message) > 8192:
        return {}
    match = _SECTIONS.search(message)
    if match is None:
        return {}
    values = {}
    for label, section in zip(("requested", "used", "limit"), match.groups(), strict=True):
        for pair in section.split(","):
            key, equals, quantity = pair.strip().partition("=")
            if equals and key in RESOURCE_KEYS:
                values.setdefault(key, {})[label] = quantity.strip()
    return safe_quota(values)
