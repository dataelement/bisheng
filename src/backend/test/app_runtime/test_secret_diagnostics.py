"""Backend diagnostics never persist raw business values. 覆盖 AC: AC-68, AC-71, AC-82, AC-86."""

from types import SimpleNamespace


def test_bound_secret_is_redacted_before_tail_and_missing_context_is_omitted(monkeypatch):
    from cryptography.fernet import Fernet

    from bisheng.app_runtime.domain.services.runtime_payload import seal
    from bisheng.app_runtime.domain.services.runtime_secret_diagnostics import safe_diagnostic_tail
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    op = SimpleNamespace(payload={"sensitive_env_names": ["COLOR"], "sealed_env": seal({"COLOR": "xyz"})})
    assert "xyz" not in safe_diagnostic_tail("x" * 17000 + "xyz", op)
    assert len(safe_diagnostic_tail("long log", op)) <= 16384
    assert safe_diagnostic_tail("xyz", SimpleNamespace(payload={"sensitive_env_names": ["COLOR"]})) == ""
