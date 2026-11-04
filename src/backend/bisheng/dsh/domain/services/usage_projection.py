"""Project the shared personal allowance onto immutable usage counters."""


def apply_current_policy_limits(snapshot: dict, policy, *, model_id: int | None = None) -> dict:
    # A selected model changes usage breakdowns, never the shared balance.
    limit = policy.monthly_token_limit
    used = snapshot.get("used")
    return {
        **snapshot,
        "limit": limit,
        "remaining": max(limit - used, 0) if used is not None else None,
        "model_limits": {str(item.model_id): limit for item in policy.model_configs},
    }
