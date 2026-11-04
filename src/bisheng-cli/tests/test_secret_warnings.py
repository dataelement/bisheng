"""F055 AC-72: missing references warn once and never include values."""

import io

from bisheng_cli.commands import deploy
from bisheng_cli.output import Emitter


def test_missing_reference_warnings_are_name_only_and_not_repeated():
    output = io.StringIO()
    emitter = Emitter(stderr=output, stdout=io.StringIO())
    payload = {
        "secret_references": [
            {"name": "MISSING", "reason": "missing_value", "value": "never-show"},
            {"name": "READY", "reason": "ok"},
        ]
    }
    seen = set()
    deploy._emit_secret_warnings(payload, emitter, seen)
    deploy._emit_secret_warnings(payload, emitter, seen)
    assert output.getvalue().count("MISSING") == 1
    assert "READY" not in output.getvalue() and "never-show" not in output.getvalue()
