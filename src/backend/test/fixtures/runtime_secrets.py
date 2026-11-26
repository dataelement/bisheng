"""Runtime-layer secrets that the shipped config.yaml reads with ``!env``.

install.sh generates these into docker/.env before any credential step runs,
so tests that load the shipped template must supply them the same way.
"""

RUNTIME_SECRETS = {
    "BISHENG_RUNTIME_CONTROL_SECRET": "test-runtime-control",
    "BISHENG_APP_PROXY_HMAC_SECRET": "test-app-proxy",
    "BISHENG_APP_OBO_SECRET": "test-app-obo",
}
RUNTIME_SECRETS_ENV = "".join(f"{name}={value}\n" for name, value in RUNTIME_SECRETS.items())
