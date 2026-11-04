"""Public current-execution facts; missing observations are never zero values."""

from datetime import UTC, datetime


def counter(value):
    return value if type(value) is int and value >= 0 else None


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.year <= 1 or parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def public_status(app_id, scope, observed, *, state="current"):
    running = observed.get("running")
    probe = observed.get("probe_state")
    if probe is None and observed.get("ready") is True:
        probe = "passed"
    health = {"passed": "healthy", "failed": "unhealthy", "pending": "starting"}.get(probe)
    phase = "running" if running else "stopped"
    if probe == "pending":
        phase = "starting"
    elif health == "unhealthy":
        phase = "unhealthy"
    if running is False and probe != "pending":
        phase, health = "stopped", None
    if state == "execution_missing":
        phase, health = "unhealthy", None
    return {
        "app_id": app_id,
        "generation": scope.get("generation"),
        "instance_id": scope.get("exec_ref"),
        "phase": phase,
        "health": health,
        "restart_count": counter(observed.get("restart_count")),
        "started_at": timestamp(observed.get("started_at")),
        "last_probe_at": timestamp(observed.get("last_probe_at")),
        "observation_state": state,
    }
