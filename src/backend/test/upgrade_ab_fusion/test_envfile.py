"""env.sh 只写入非密钥 export 行."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.envfile import upsert_export  # noqa: E402


def test_replaces_existing_export(tmp_path: Path):
    p = tmp_path / "env.sh"
    p.write_text('export A_SSH_USER="${A_SSH_USER:-}"\nexport DRILL=1\n', encoding="utf-8")
    upsert_export(p, "A_SSH_USER", "Oper1")
    text = p.read_text(encoding="utf-8")
    assert "export A_SSH_USER='Oper1'" in text
    assert "export DRILL=1" in text
    assert "${A_SSH_USER:-}" not in text


def test_appends_when_missing(tmp_path: Path):
    p = tmp_path / "env.sh"
    p.write_text("export DRILL=0\n", encoding="utf-8")
    upsert_export(p, "A_SSH_PORT", "52012")
    assert "export A_SSH_PORT='52012'\n" in p.read_text(encoding="utf-8")


def test_rejects_quote_in_value(tmp_path: Path):
    p = tmp_path / "env.sh"
    p.write_text("", encoding="utf-8")
    try:
        upsert_export(p, "A_SSH_HOST", "bad'host")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_rejects_newline_and_bad_key(tmp_path: Path):
    p = tmp_path / "env.sh"
    p.write_text("", encoding="utf-8")
    try:
        upsert_export(p, "A_SSH_HOST", "10.0.0.1\nexport X=1")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        upsert_export(p, "ssh-host", "10.0.0.1")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
