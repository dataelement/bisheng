"""Read-only egress projection. Expired or unreachable policy fails closed."""

from __future__ import annotations

import time

from runtime_manager.egress import PrincipalPolicy
from runtime_manager.platform_client import PlatformClient


class PlatformPolicyStore:
    def __init__(self, config, client=None, *, clock=time):
        self.client = client or PlatformClient(config)
        self.clock = clock
        self._items = {}
        self._expires = 0

    def refresh(self):
        before = self.clock.monotonic()
        document = self.client.egress_policies()
        now = self.clock.time()
        expiry = min(float(document["not_after"]) - now, 5)
        items = {}
        for row in document["policies"]:
            if float(row["not_after"]) <= now:
                continue
            items[row["principal"]] = (
                PrincipalPolicy.from_dict(
                    {
                        "principal": row["principal"],
                        "token_hash": row["credential_hash"],
                        "destinations": row["destinations"],
                    }
                ),
                before + min(expiry, float(row["not_after"]) - now),
            )
        self._items = items
        self._expires = before + max(0, expiry)

    def get(self, principal):
        now = self.clock.monotonic()
        if now >= self._expires:
            return None
        item = self._items.get(principal)
        return item[0] if item and item[1] > now else None
