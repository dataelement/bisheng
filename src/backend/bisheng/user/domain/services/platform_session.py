"""One platform session engine for browsers and native clients."""

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.domain.const import FIRST_PARTY_CLIENT_IDS, NATIVE_CLIENT_IDS
from bisheng.user.domain.models.platform_session import PlatformRefreshToken, PlatformSession, PlatformWebTicket
from bisheng.user.domain.schemas.credential_reference import valid_browser_reference_shape
from bisheng.user.domain.services.session_rotation import rotation_decision, unspent_successor


def iso(value):
    return value.replace(tzinfo=UTC).isoformat()


class PlatformSessionService:
    def __init__(
        self,
        repository_scope,
        *,
        secret,
        now=datetime.utcnow,
        access_seconds=2592000,
        idle_seconds=7776000,
        grace_seconds=86400,
        absolute_seconds=None,
        allow_multi_login=True,
        login_policy_reader=None,
        issuance_enabled_reader=None,
    ):
        self.repository_scope = repository_scope
        self.now = now
        self.access_seconds = access_seconds
        self.idle_seconds = idle_seconds
        self.grace_seconds = grace_seconds
        self.absolute_seconds = absolute_seconds
        self.allow_multi_login = allow_multi_login
        self.login_policy_reader = login_policy_reader
        self.issuance_enabled_reader = issuance_enabled_reader
        self.keys = {
            purpose: hmac.new(
                secret.encode(), ("bisheng/platform/" + purpose + "/v1").encode(), hashlib.sha256
            ).digest()
            for purpose in ("access", "refresh", "binding", "csrf")
        }

    async def run(self, action, *, read_only=False):
        def transaction():
            error = None
            with self.repository_scope() as repo:
                try:
                    result = action(repo)
                except PlatformAuthError as exc:
                    error = exc
            if error is not None:
                raise error
            return result

        try:
            operation = asyncio.to_thread(transaction)
            return await asyncio.wait_for(operation, timeout=2.0) if read_only else await operation
        except TimeoutError as exc:
            logger.warning("Platform authentication storage exceeded its time budget")
            raise PlatformAuthError("auth_service_unavailable") from exc
        except SQLAlchemyError as exc:
            logger.exception("Platform authentication database unavailable")
            raise PlatformAuthError("auth_service_unavailable") from exc

    @staticmethod
    def digest(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise PlatformAuthError("invalid_refresh_token")
        return hashlib.sha256(value.encode()).hexdigest()

    def derive(self, purpose, value):
        return (
            base64.urlsafe_b64encode(hmac.new(self.keys[purpose], value.encode(), hashlib.sha256).digest())
            .decode()
            .rstrip("=")
        )

    def decode(self, token, *, check_exp=True):
        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") != "bisheng-platform-access+jwt" or header.get("kid") != "platform-access-v1":
                raise PlatformAuthError("legacy_web_token_rejected")
            claims = jwt.decode(
                token,
                self.keys["access"],
                algorithms=["HS256"],
                audience="bisheng-platform-api",
                issuer="bisheng-platform",
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "require": [
                        "sub",
                        "tenant_id",
                        "session_id",
                        "session_version",
                        "token_version",
                        "client_id",
                        "iat",
                        "exp",
                        "jti",
                    ],
                },
            )
            if not re.fullmatch(r"[0-9a-f]{32}", claims["session_id"]):
                raise ValueError("sid")
            if check_exp and int(claims["exp"]) <= int(self.now().replace(tzinfo=UTC).timestamp()):
                raise PlatformAuthError("web_bootstrap_expired" if claims.get("bootstrap_only") else "access_expired")
            return claims
        except (jwt.PyJWTError, TypeError, ValueError, KeyError) as exc:
            raise PlatformAuthError() from exc

    def locked(self, repo, sid):
        candidate = repo.get(sid)
        if candidate is None:
            return None
        # Every transition takes the same user -> session -> refresh lock order.
        # Identity current reads also replace a pre-lock REPEATABLE READ snapshot.
        repo.identity(candidate.user_id, candidate.tenant_id, lock=True)
        return repo.get(sid, lock=True)

    def checked(self, repo, session, *, claims=None, pending=False):
        if session is None or session.state != "ACTIVE":
            raise PlatformAuthError("session_revoked")
        now = self.now()  # Called after the row lock, never before waiting.
        if session.expires_at <= now:
            raise PlatformAuthError("session_expired")
        if claims is not None and (
            str(session.user_id) != claims["sub"]
            or str(session.tenant_id) != claims["tenant_id"]
            or session.version != claims["session_version"]
            or session.token_version != claims["token_version"]
        ):
            raise PlatformAuthError("session_revoked")
        identity = repo.identity(session.user_id, session.tenant_id, lock=True)
        if not identity or identity["token_version"] != session.token_version:
            session.state = "REVOKED"
            repo.add(session)
            raise PlatformAuthError("session_revoked")
        if not pending and (session.delivery_state == "PENDING_WEB_BIND" or (claims and claims.get("bootstrap_only"))):
            raise PlatformAuthError("web_bootstrap_required")
        if session.parent_session_id:
            parent = repo.get(session.parent_session_id, lock=True)
            if not parent or parent.state != "ACTIVE" or parent.expires_at <= now:
                raise PlatformAuthError("session_revoked")
        return identity

    def response(self, session, identity, refresh=None, *, bootstrap_only=False):
        now = self.now()
        expiry = min(now + timedelta(seconds=session.access_ttl_seconds), session.expires_at)
        if bootstrap_only:
            expiry = min(expiry, session.created_at + timedelta(seconds=300))
        claims = {
            "iss": "bisheng-platform",
            "aud": "bisheng-platform-api",
            "sub": str(session.user_id),
            "tenant_id": str(session.tenant_id),
            "session_id": session.session_id,
            "session_version": session.version,
            "token_version": session.token_version,
            "client_id": session.client_id,
            "iat": int(now.replace(tzinfo=UTC).timestamp()),
            "exp": int(expiry.replace(tzinfo=UTC).timestamp()),
            "jti": secrets.token_hex(16),
        }
        if bootstrap_only:
            claims["bootstrap_only"] = True
        token = jwt.encode(
            claims,
            self.keys["access"],
            algorithm="HS256",
            headers={"typ": "bisheng-platform-access+jwt", "kid": "platform-access-v1"},
        )
        result = {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": int((expiry - now).total_seconds()),
            "access_expires_at": iso(expiry),
            "refresh_expires_in": int((session.expires_at - now).total_seconds()),
            "refresh_expires_at": iso(session.expires_at),
            "session_id": session.session_id,
            "session_expires_at": iso(session.expires_at),
            "cookie_retention_seconds": session.idle_ttl_seconds + session.access_ttl_seconds + 86400,
            "delivery_state": session.delivery_state,
            "refresh_mode": "host"
            if session.parent_session_id
            else "native"
            if session.client_id in NATIVE_CLIENT_IDS
            else "cookie",
            "csrf_token": self.derive("csrf", f"{session.session_id}:{session.version}"),
            "user": {"id": identity["id"], "user_name": identity["user_name"]},
            "tenant": {"id": session.tenant_id, "name": identity["tenant_name"]},
            "default_entry": "/workspace",
        }
        if refresh is not None:
            result["refresh_token"] = refresh
        result["auth_source"] = "platform"
        return result

    async def issue(
        self,
        user_id,
        tenant_id,
        client_id,
        *,
        pending=False,
        device_label=None,
        client_version=None,
        parent_session_id=None,
    ):
        if self.issuance_enabled_reader and not self.issuance_enabled_reader():
            raise PlatformAuthError("auth_service_unavailable")
        if client_id not in FIRST_PARTY_CLIENT_IDS:
            raise PlatformAuthError("invalid_auth_request")
        allow_multi_login = await self.login_policy_reader() if self.login_policy_reader else self.allow_multi_login

        def action(repo):
            identity = repo.identity(user_id, tenant_id, lock=True)
            if not identity:
                raise PlatformAuthError("session_revoked")
            now = self.now()
            if not allow_multi_login:
                for old in repo.sessions(user_id):
                    old.state = "REVOKED"
                    repo.add(old)
            absolute = now + timedelta(seconds=self.absolute_seconds) if self.absolute_seconds else None
            expires = now + timedelta(seconds=self.idle_seconds)
            row = PlatformSession(
                session_id=secrets.token_hex(16),
                user_id=user_id,
                tenant_id=tenant_id,
                token_version=identity["token_version"],
                client_id=client_id,
                access_ttl_seconds=self.access_seconds,
                idle_ttl_seconds=self.idle_seconds,
                refresh_grace_seconds=self.grace_seconds,
                device_label=device_label,
                client_version=client_version,
                created_at=now,
                last_activity_at=now,
                expires_at=min(expires, absolute) if absolute else expires,
                absolute_expires_at=absolute,
                delivery_state="PENDING_WEB_BIND" if pending else "BOUND",
                parent_session_id=parent_session_id,
            )
            repo.add(row)
            refresh = None if pending else secrets.token_urlsafe(32)
            if refresh:
                repo.add(
                    PlatformRefreshToken(
                        token_hash=self.digest(refresh),
                        tenant_id=tenant_id,
                        session_id=row.session_id,
                        generation=1,
                        expires_at=row.expires_at,
                    )
                )
            repo.flush()
            return self.response(row, identity, refresh, bootstrap_only=pending)

        return await self.run(action)

    async def refresh(self, credential):
        digest = self.digest(credential)

        def action(repo):
            located = repo.refresh(digest)
            if located is None:
                raise PlatformAuthError("invalid_refresh_token")
            session = self.locked(repo, located.session_id)
            identity = self.checked(repo, session)
            current = repo.refresh(digest, lock=True)
            if current.tenant_id != session.tenant_id:
                raise PlatformAuthError("invalid_refresh_token")
            now = self.now()
            successor = self.derive("refresh", credential)
            next_row = repo.generation(session.session_id, current.generation + 1)
            decision = rotation_decision(
                session_state=session.state,
                session_expired=session.expires_at <= now,
                token_state=current.state,
                token_expired=current.expires_at <= now,
                generation=current.generation,
                recoverable=bool(
                    next_row
                    and unspent_successor(
                        now=now,
                        used_at=current.used_at,
                        grace_seconds=session.refresh_grace_seconds,
                        successor_state=next_row.state,
                    )
                    and next_row.token_hash == self.digest(successor)
                ),
            )
            if decision == "recover":
                return self.response(session, identity, successor)
            if decision == "revoke":
                session.state = "REVOKED"
                repo.add(session)
                raise PlatformAuthError("refresh_token_reused")
            if decision != "rotate":
                raise PlatformAuthError(decision)
            current.state, current.used_at = "USED", now
            repo.add(current)
            repo.add(
                PlatformRefreshToken(
                    token_hash=self.digest(successor),
                    tenant_id=session.tenant_id,
                    session_id=session.session_id,
                    generation=current.generation + 1,
                    expires_at=session.expires_at,
                )
            )
            repo.flush()
            return self.response(session, identity, successor)

        return await self.run(action)

    async def inspect(self, token, *, pending=False):
        claims = self.decode(token)

        def action(repo):
            session = self.locked(repo, claims["session_id"])
            identity = self.checked(repo, session, claims=claims, pending=pending)
            if claims.get("bootstrap_only") and self.now() > session.created_at + timedelta(seconds=300):
                raise PlatformAuthError("web_bootstrap_expired")
            result = self.response(session, identity, bootstrap_only=bool(claims.get("bootstrap_only")))
            result["access_token"] = token
            if claims.get("bootstrap_only"):
                result["delivery_state"] = "PENDING_WEB_BIND"
            result["access_expires_at"] = iso(datetime.fromtimestamp(claims["exp"], UTC).replace(tzinfo=None))
            result["expires_in"] = max(0, claims["exp"] - int(self.now().replace(tzinfo=UTC).timestamp()))
            return result

        return await self.run(action, read_only=True)

    async def browser_entry_token(self, selected, fixed):
        """Recover a newer gateway entry while its first refresh generation remains unused."""
        if not fixed:
            return selected
        try:
            claims = self.decode(fixed)
        except PlatformAuthError:
            return selected
        if not claims.get("bootstrap_only"):
            return selected
        if not selected:
            return fixed
        try:
            previous = self.decode(selected, check_exp=False)
        except PlatformAuthError:
            return fixed
        if previous["session_id"] == claims["session_id"]:
            return selected

        def action(repo):
            pending = repo.get(claims["session_id"])
            current = repo.get(previous["session_id"])
            if (
                pending
                and pending.state == "ACTIVE"
                and pending.created_at + timedelta(seconds=300) > self.now()
                and (current is None or pending.issuance_order > current.issuance_order)
            ):
                if pending.delivery_state == "PENDING_WEB_BIND":
                    return fixed
                if pending.delivery_state == "BOUND":
                    first = repo.generation(pending.session_id, 1)
                    if first is not None and first.state == "ACTIVE":
                        return fixed
            return selected

        return await self.run(action, read_only=True)

    async def bootstrap(self, token):
        claims = self.decode(token)
        if not claims.get("bootstrap_only"):
            raise PlatformAuthError("invalid_auth_request")

        def action(repo):
            row = self.locked(repo, claims["session_id"])
            identity = self.checked(repo, row, claims=claims, pending=True)
            if self.now() > row.created_at + timedelta(seconds=300):
                raise PlatformAuthError("web_bootstrap_expired")
            refresh = self.derive("binding", row.session_id)
            first = repo.generation(row.session_id, 1)
            if first and first.state != "ACTIVE":
                raise PlatformAuthError("web_binding_completed")
            if not first:
                repo.add(
                    PlatformRefreshToken(
                        token_hash=self.digest(refresh),
                        tenant_id=row.tenant_id,
                        session_id=row.session_id,
                        generation=1,
                        expires_at=row.expires_at,
                    )
                )
            row.delivery_state = "BOUND"
            repo.add(row)
            repo.flush()
            return self.response(row, identity, refresh)

        return await self.run(action)

    async def activity(self, token):
        claims = self.decode(token)

        def action(repo):
            row = self.locked(repo, claims["session_id"])
            self.checked(repo, row, claims=claims)
            now = self.now()
            family = [row]
            if row.parent_session_id:
                parent = repo.get(row.parent_session_id, lock=True)
                self.checked(repo, parent)
                family.insert(0, parent)
            for current in family:
                expires = now + timedelta(seconds=current.idle_ttl_seconds)
                current.expires_at = (
                    min(expires, current.absolute_expires_at) if current.absolute_expires_at else expires
                )
                current.last_activity_at = now
                repo.add(current)
                for refresh in repo.active_refreshes(current.session_id):
                    refresh.expires_at = current.expires_at
                    repo.add(refresh)

        await self.run(action)

    async def refresh_session(self, credential):
        digest = self.digest(credential)

        def action(repo):
            refresh = repo.refresh(digest)
            if not refresh or refresh.state not in {"ACTIVE", "USED"}:
                raise PlatformAuthError("invalid_refresh_token")
            row = repo.get(refresh.session_id)
            identity = self.checked(repo, row)
            if refresh.tenant_id != row.tenant_id:
                raise PlatformAuthError("invalid_refresh_token")
            if refresh.state == "USED":
                successor = repo.generation(row.session_id, refresh.generation + 1)
                if (
                    not refresh.used_at
                    or self.now() > refresh.used_at + timedelta(seconds=row.refresh_grace_seconds)
                    or not successor
                    or successor.state != "ACTIVE"
                ):
                    raise PlatformAuthError("invalid_refresh_token")
            return self.response(row, identity)

        return await self.run(action, read_only=True)

    async def logout(self, credential, *, refresh=False, all_sessions=False):
        digest = self.digest(credential) if refresh else None
        claims = None if refresh else self.decode(credential, check_exp=False)

        def action(repo):
            token = repo.refresh(digest) if refresh else None
            if refresh and not token:
                return
            row = self.locked(repo, token.session_id if token else claims["session_id"])
            if not row:
                return
            if token and token.tenant_id != row.tenant_id:
                raise PlatformAuthError("invalid_refresh_token")
            if claims and (
                str(row.user_id) != claims["sub"]
                or str(row.tenant_id) != claims["tenant_id"]
                or row.version != claims["session_version"]
            ):
                raise PlatformAuthError("invalid_access_token")
            if all_sessions:
                self.checked(repo, row, claims=claims)
            for target in repo.sessions(row.user_id) if all_sessions else [row]:
                target.state = "REVOKED"
                repo.add(target)

        await self.run(action)

    async def logout_csrf(self, credential, *, refresh=False):
        if not refresh:
            claims = self.decode(credential, check_exp=False)
            return {"csrf_token": self.derive("csrf", f"{claims['session_id']}:{claims['session_version']}")}
        digest = self.digest(credential)

        def action(repo):
            token = repo.refresh(digest)
            if not token:
                raise PlatformAuthError("invalid_refresh_token")
            row = repo.get(token.session_id)
            if not row:
                raise PlatformAuthError("invalid_refresh_token")
            # Revocation changes state without invalidating the self-proof
            # nonce, so the same protected logout can be repeated safely.
            return {"csrf_token": self.derive("csrf", f"{row.session_id}:{row.version}")}

        return await self.run(action, read_only=True)

    async def create_ticket(self, token, origin):
        claims = self.decode(token)

        def action(repo):
            row = self.locked(repo, claims["session_id"])
            self.checked(repo, row, claims=claims)
            if row.client_id not in NATIVE_CLIENT_IDS or row.parent_session_id:
                raise PlatformAuthError("invalid_auth_request")
            ticket = secrets.token_urlsafe(32)
            repo.cleanup_tickets(self.now(), limit=100)
            host_sid = secrets.token_hex(16)
            repo.add(
                PlatformWebTicket(
                    token_hash=self.digest(ticket),
                    tenant_id=row.tenant_id,
                    session_id=row.session_id,
                    host_session_id=host_sid,
                    origin=origin,
                    expires_at=self.now() + timedelta(seconds=60),
                )
            )
            return {
                "ticket": ticket,
                "consume_url": f"{origin}/api/v1/auth/web-session/consume?ticket={ticket}",
                "expires_in": 60,
                "session_id": host_sid,
            }

        return await self.run(action)

    async def consume_ticket(self, ticket, origin):
        digest = self.digest(ticket)

        def action(repo):
            ticket_row = repo.ticket(digest)
            if (
                not ticket_row
                or ticket_row.consumed
                or ticket_row.expires_at <= self.now()
                or ticket_row.origin != origin
            ):
                raise PlatformAuthError("invalid_access_token")
            parent = self.locked(repo, ticket_row.session_id)
            identity = self.checked(repo, parent)
            if ticket_row.tenant_id != parent.tenant_id:
                raise PlatformAuthError("invalid_access_token")
            ticket_row.consumed = True
            repo.add(ticket_row)
            # Host sessions are access-only views of the native parent. Their
            # lifetime and revocation never outlive that parent.
            now = self.now()
            row = PlatformSession(
                session_id=ticket_row.host_session_id,
                tenant_id=parent.tenant_id,
                user_id=parent.user_id,
                token_version=parent.token_version,
                access_ttl_seconds=parent.access_ttl_seconds,
                idle_ttl_seconds=parent.idle_ttl_seconds,
                refresh_grace_seconds=parent.refresh_grace_seconds,
                client_id="bisheng-web",
                created_at=now,
                last_activity_at=now,
                expires_at=parent.expires_at,
                absolute_expires_at=parent.absolute_expires_at,
                parent_session_id=parent.session_id,
            )
            repo.add(row)
            repo.flush()
            return self.response(row, identity)

        return await self.run(action)

    async def desktop_sessions(self, user_id, *, cursor=None, limit=20):
        """Device management reads only Desktop sessions in the caller's tenant scope."""

        def action(repo):
            rows = repo.desktop_sessions(user_id, cursor=cursor, limit=limit)
            return {
                "items": [
                    {
                        "session_id": row.session_id,
                        "device_label": row.device_label,
                        "client_version": row.client_version,
                        "state": row.state,
                        "expires_at": iso(row.expires_at),
                        "created_at": iso(row.created_at),
                        "last_seen_at": iso(row.last_activity_at),
                    }
                    for row in rows[:limit]
                ],
                "has_more": len(rows) > limit,
                "next_cursor": rows[limit - 1].session_id if len(rows) > limit else None,
            }

        return await self.run(action, read_only=True)

    async def revoke_desktop_session(self, user_id, tenant_id, session_id):
        """A browser may revoke only its own native Desktop device, including expired devices."""

        def action(repo):
            row = self.locked(repo, session_id)
            if (
                row is None
                or row.user_id != user_id
                or row.tenant_id != tenant_id
                or row.client_id != "bisheng-desktop"
                or row.parent_session_id is not None
            ):
                return False
            row.state = "REVOKED"
            repo.add(row)
            return True

        return await self.run(action)

    async def validate_reference(self, reference):
        try:
            if not valid_browser_reference_shape(reference):
                raise PlatformAuthError()
            expires = datetime.fromisoformat(reference["expires_at"]).replace(tzinfo=None)
            if expires <= self.now() or reference["kind"] != "platform_session":
                raise PlatformAuthError("access_expired")

            def action(repo):
                row = self.locked(repo, reference["session_id"])
                claims = {
                    "sub": str(reference["user_id"]),
                    "tenant_id": str(reference["tenant_id"]),
                    "session_version": reference["session_version"],
                    "token_version": reference["token_version"],
                }
                return self.checked(repo, row, claims=claims)

            return await self.run(action, read_only=True)
        except (ValueError, TypeError, KeyError) as exc:
            raise PlatformAuthError() from exc
