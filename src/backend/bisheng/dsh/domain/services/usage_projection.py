"""Project immutable usage counters onto the user's current effective policy."""


def apply_current_policy_limits(snapshot: dict, policy, *, model_id: int | None = None) -> dict:
    current_limits = {str(item.model_id): item.monthly_token_limit for item in policy.model_configs}
    models = snapshot.get("models")
    ledger_limits = snapshot.get("model_limits") or {}
    projected = {**snapshot, "model_limits": current_limits}

    if model_id is not None:
        model_key = str(model_id)
        limit = current_limits[model_key]
        if models is None or (model_key not in models and model_key in ledger_limits):
            return {
                **projected,
                "used": None,
                "limit": limit,
                "remaining": None,
                "quota_state": "unavailable",
            }
        used = models.get(model_key, 0)
        return {**projected, "used": used, "limit": limit, "remaining": max(limit - used, 0)}

    limit = sum(current_limits.values())
    if models is not None and all(key in models or key not in ledger_limits for key in current_limits):
        return {
            **projected,
            "limit": limit,
            "remaining": sum(max(value - models.get(key, 0), 0) for key, value in current_limits.items()),
        }
    if len(current_limits) == 1 and snapshot.get("used") is not None:
        value = next(iter(current_limits.values()))
        return {**projected, "limit": value, "remaining": max(value - snapshot["used"], 0)}
    return {**projected, "limit": limit, "remaining": None, "quota_state": "unavailable"}
