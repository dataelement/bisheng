"""Explicit platform-only activity declarations; legacy DSH policy stays frozen."""

from bisheng.core.session_activity import ActivityPolicy


def declare_platform_activity(router, *names):
    remaining = set(names)
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if getattr(endpoint, "__name__", None) in remaining:
            endpoint.__platform_session_activity_policy__ = ActivityPolicy(http=True)
            remaining.remove(endpoint.__name__)
    if remaining:
        raise ValueError(f"Unknown platform activity entrances: {sorted(remaining)}")
