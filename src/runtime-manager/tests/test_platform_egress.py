"""覆盖 AC: AC-43、AC-47、AC-50。"""

import hashlib

from runtime_manager.config import Config
from runtime_manager.platform_egress import PlatformPolicyStore


class Clock:
    def __init__(self):
        self.now = 100

    def time(self):
        return self.now

    def monotonic(self):
        return self.now


def test_policy_deadline_is_hard_even_during_platform_outage():
    clock = Clock()

    class Client:
        def egress_policies(self):
            return {
                "not_after": 105,
                "policies": [
                    {
                        "principal": "app",
                        "credential_hash": hashlib.sha256(b"token").hexdigest(),
                        "destinations": [{"host": "example.com", "ports": [443], "trusted": False}],
                        "not_after": 105,
                    }
                ],
            }

    store = PlatformPolicyStore(Config(), Client(), clock=clock)
    store.refresh()
    policy = store.get("app")
    assert policy.authenticates("token")
    assert policy.token == ""
    clock.now = 105
    assert store.get("app") is None
