"""Operational bounds for DSH scans and the default Compose deployment."""

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def test_usage_scan_cursor_continuations_are_throttled():
    tree = ast.parse((ROOT / "src/backend/bisheng/worker/dsh/registry.py").read_text(encoding="utf-8"))
    continuations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            node.func.attr == "apply_async"
            and isinstance(owner, ast.Name)
            and owner.id
            in {
                "scan_usage",
                "inspect_usage",
            }
        ):
            continuations.append(node)
    assert len(continuations) == 2
    for call in continuations:
        countdown = next((item.value for item in call.keywords if item.arg == "countdown"), None)
        assert isinstance(countdown, ast.Constant) and countdown.value == 1


def test_default_backend_containers_have_hard_stdout_rotation():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8"))
    for service in ("backend", "backend_worker"):
        logging = compose["services"][service]["logging"]
        assert logging == {"driver": "json-file", "options": {"max-size": "100m", "max-file": "5"}}


def test_shipped_container_config_does_not_enable_debug_logging():
    # BaseLoader keeps deployment-only !env values inert; this assertion does
    # not need or resolve any production secret.
    config = yaml.load((ROOT / "docker/bisheng/config/config.yaml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert config["logger_conf"]["level"] == "INFO"
    main, statistic = config["logger_conf"]["handlers"]
    assert (main["rotation"], main["retention"]) == ("100 MB", "3 Days")
    assert (statistic["rotation"], statistic["retention"]) == ("100 MB", "3 Days")
