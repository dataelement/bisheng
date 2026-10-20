"""Purpose-separated desktop signing using the platform's persistent master key."""

import hashlib
import hmac

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError

KEY_ID = "dsh-local-v1"
ISSUER = "bisheng-dsh"


class LocalTokenKeys:
    def __init__(self, secret_reader=None):
        self.secret_reader = secret_reader

    async def resolve(self, kid):
        if kid != KEY_ID:
            raise DshInvalidAccessTokenError()
        if self.secret_reader is None:
            from bisheng.user.domain.services.jwt_secret import resolve_jwt_secret

            reader = resolve_jwt_secret
        else:
            reader = self.secret_reader
        # Distinct from both Web JWT and the removed Gateway shared-secret key.
        import asyncio

        master = await asyncio.to_thread(reader)
        return hmac.digest(master.encode(), b"bisheng:dsh:local-access:v1", hashlib.sha256)
