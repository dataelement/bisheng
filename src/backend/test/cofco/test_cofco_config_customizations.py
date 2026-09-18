"""The 909 line's own entries in docker/bisheng/config/config.yaml.

909 keeps configuration the main line has no reason to carry. A three-way merge
cannot tell "the other side never had this" from "the other side deleted this",
so merging the main line in silently drops those entries - without a conflict,
because there is nothing to conflict with.

Nothing else catches it. The code that reads these settings merges cleanly and
keeps working against its defaults, so types check, every suite passes and the
build succeeds while the behaviour quietly changes. It happened on 2026-09-17:
knowledge_space_read_bypass vanished from the 923 branch and space 311 started
being gated again, in silence.

This test is the guard. It fails on the merge commit, before anyone deploys.
Add a case whenever the 909 line gains configuration of its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[4] / "docker" / "bisheng" / "config" / "config.yaml"


class _EnvTolerantLoader(yaml.SafeLoader):
    """The file uses `!env` for values the deployment supplies; shape is all we check."""


_EnvTolerantLoader.add_constructor("!env", lambda loader, node: "")


@pytest.fixture(scope="module")
def config() -> dict:
    assert CONFIG.is_file(), f"deployment config is missing: {CONFIG}"
    return yaml.load(CONFIG.read_text(encoding="utf-8"), Loader=_EnvTolerantLoader)


def test_the_read_bypass_whitelist_survives(config):
    """5cb130f98: selected spaces skip the read permission check.

    The service code defaults to disabled, so losing this block does not fail
    anywhere - the whitelisted space simply stops being reachable.
    """
    bypass = config.get("knowledge_space_read_bypass")

    assert bypass is not None, "knowledge_space_read_bypass was dropped from config.yaml"
    assert bypass.get("enabled") is True
    assert bypass.get("space_ids"), "the whitelist is empty, which disables the bypass"


def test_the_gateway_hmac_secret_is_still_set(config):
    """The customer's gateway signs its SSO pushes with this.

    The main line ships it empty on purpose; this line must not inherit that.
    Empty here is fail-closed, so every SSO login and org sync would be refused.
    """
    secret = config.get("sso_sync", {}).get("gateway_hmac_secret")

    assert secret, "sso_sync.gateway_hmac_secret is empty - the main line's value was merged in"
