"""One presentation status derived exclusively from saved audit facts."""


def audit_status_facts(row):
    reasons = []
    axes = (
        ("model_result", {"RUNNING", "SUCCEEDED"}, {"FAILED", "CANCELLED", "UNKNOWN"}),
        ("response_result", {"RUNNING", "COMPLETED"}, {"ERROR", "INTERRUPTED", "UNKNOWN"}),
        ("usage_settlement", {"PENDING", "SETTLED"}, {"USAGE_UNKNOWN", "UNCERTAIN"}),
    )
    for axis, normal, abnormal in axes:
        value = getattr(row, axis)
        if value not in normal:
            reasons.append(f"{axis}:{value}" if value in abnormal else "INVALID_STATE")
    mode, content = row.effective_mode, row.content_status
    if mode == "METADATA":
        if content != "NOT_CAPTURED":
            reasons.append("INVALID_STATE")
    elif mode == "CONTENT":
        if getattr(row, "capture_failed", False):
            reasons.append("CAPTURE_FAILED")
        if content not in {"PENDING", "COMPLETE"}:
            reasons.append(f"content_status:{content}" if content in {"PARTIAL", "NOT_CAPTURED"} else "INVALID_STATE")
    else:
        reasons.append("INVALID_STATE")
    pending = row.model_result == "RUNNING" or row.response_result == "RUNNING" or row.usage_settlement == "PENDING"
    pending |= mode == "CONTENT" and content == "PENDING"
    return ("ABNORMAL" if reasons else "NORMAL"), list(dict.fromkeys(reasons)), pending


def refresh_audit_status(row):
    row.audit_status = audit_status_facts(row)[0]
    if row.conversation_key and row.group_indexed_status != row.audit_status:
        row.group_index_pending = True
