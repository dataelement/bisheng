from __future__ import annotations

SUPPORTED_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

EXCLUDED_EXACT_PATHS = frozenset(
    {
        "/health",
        "/openapi.json",
        "/api/v1/user/login",
        "/api/v1/user/logout",
        "/api/v1/admin/api-rate-limit/config",
        "/api/v1/admin/api-rate-limit/routes",
    }
)
EXCLUDED_PREFIXES = ("/docs", "/redoc", "/static", "/assets")


def is_api_rate_limit_excluded(path: str, method: str) -> bool:
    normalized_method = method.upper()
    return (
        normalized_method in {"OPTIONS", "HEAD"}
        or path in EXCLUDED_EXACT_PATHS
        or any(path == prefix or path.startswith(f"{prefix}/") for prefix in EXCLUDED_PREFIXES)
    )
