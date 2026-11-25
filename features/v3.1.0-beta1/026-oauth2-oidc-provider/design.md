# Design: OAuth 2.0 / OIDC Provider (SSO Server)

References: [spec.md](./spec.md) · [docs/constitution.md](../../../docs/constitution.md) (C1–C8).

## 1. Architecture & Boundaries

- New backend module: `src/backend/bisheng/oauth2_provider/` following DDD layering (`api → domain/services → domain/repositories → domain/models`, C1).
- Application endpoints live under `/api/v1/oauth2/**`; standard OIDC discovery is `/.well-known/openid-configuration`, with `/.well-known/oauth-authorization-server` retained for compatibility. The standards-defined discovery path is the explicit exception to the application URL naming rule; deployment proxies must forward these exact root paths.
- Java Gateway proxies `/api/v1/**` transparently, so both Gateway-fronted and standalone deployments work identically without touching Gateway.

## 2. Data Models (Dual-DB C2)

- `oauth2_client` (`OAuth2Client`): platform-scoped table (not tenant-filtered so unauthenticated `/authorize` and `/token` can resolve `client_id` before tenant context). Uses `dialect_helpers.JsonType` for `redirect_uris`, `allowed_scopes`, `grant_types`.
- `oauth2_session` (`OAuth2Session`): stores `session_id`, `client_id`, `tenant_id`, `user_id`, `scope`, `state` (`ACTIVE`/`REVOKED`), `created_at`, `expires_at`, `revoked_at`.
- `oauth2_refresh_token` (`OAuth2RefreshToken`): stores SHA-256 `token_hash`, `session_id`, `client_id`, `tenant_id`, `generation`, `state` (`ACTIVE`/`USED`/`REVOKED`), `expires_at`.
- Redis (`OAuth2CodeRepository`): stores pending authorization requests (`oauth2:req:{request_id}`, TTL 300s) and one-time authorization codes (`oauth2:code:{code}`, TTL 120s, atomic `GETDEL`).

## 3. Signing & Security (C6 / C7)

- `OAuth2KeyService` derives the ES256 P-256 private scalar from `HMAC-SHA256(jwt_master_secret, "bisheng:oauth2:es256:v1")`, reduced into the valid P-256 scalar range. Replicas using the same persistent master secret expose the same public JWK (`kty: EC`, `crv: P-256`, `alg: ES256`, `kid: bisheng-oauth2-es256-v1`) without local key files. Master-secret rotation changes this signing key; overlapping OAuth key rotation is not implemented.
- Confidential client secrets are hashed using `hashlib.pbkdf2_hmac("sha256", secret, salt, 200_000)` and verified with `hmac.compare_digest`.
- Browser consent POST requires `application/json` and rejects a supplied Origin unless it matches the resolved public origin. Browser cookies and the existing authenticated-user dependency protect the consent endpoint; non-browser clients may omit Origin.
- Redirect URI matching is exact-string comparison; when `allow_loopback_port=True`, `http://127.0.0.1:{any_port}{path}` matches registered `http://127.0.0.1{path}` per RFC 8252 §7.3.

## 4. DSH Migration (Backward-Compatible)

- Built-in client `dsh-desktop` is ensured in `oauth2_client` (`is_builtin=True`, `client_type="public"`, `allow_loopback_port=True`, `redirect_uris=["http://127.0.0.1/dsh/callback"]`, `require_pkce=True`, `require_consent=True`).
- `DshAuthorizationService` delegates client lookup, enabled check, and redirect URI validation to `OAuth2ClientService` (falling back to built-in defaults only in isolated unit tests without DB).
- `DshAuthorizationService.resolve` returns `require_consent` and `client_name`; the existing `/desktop-login` UI retains its confirmation behavior. Automatic approval from `require_consent=False` is implemented in the standard OAuth `/authorize` and `/oauth-consent` flow; old Desktop UI auto-approval remains outside the verified delivery.

## 5. Verified hardening (2026-11-25)

- Public OAuth routes use a dedicated `OAuth2ProtocolRoute` so real platform global exception handlers cannot turn OAuth protocol failures into HTTP 200 envelopes. Protocol replies carry `Cache-Control: no-store`; admin and consent retain the platform envelope.
- Auto-approval reuses browser JWT version validation and the existing `UserPayload` authentication path. Identity resolution requires a real human user, an active tenant and its current active `UserTenant` membership.
- Refresh and revoke lock/update the session family before tokens; token consumption uses conditional updates and successor insertion is in the same transaction. Reuse revokes the family. Session expiry covers outstanding access tokens, while refresh expiry remains independent.
- UserInfo intersects signed and persisted scopes before returning profile/email. Confidential-client revocation authenticates the owning client. Invalid URI parsing is a domain error or non-match rather than HTTP 500.
- The OAuth page saves an exact same-origin return target through the existing 10-minute one-time return mechanism before the first identity request. Ordinary users can reach the consent page without being granted management-route access.
- 115 delivery uses a 23-file backend overlay on its exact running image and a platform build based on its existing source commit `0a9256a234`; it does not replace all backend sources with the newer feature branch. Shared six-file integration retains the old server composition interfaces.
- MySQL/DM8 portability uses the existing dialect helpers and conditional SQLAlchemy UPDATE/CASE. Local concurrency tests use SQLite; DM8 actual execution remains outside this deployment.

## 6. Error Codes (C5)

Module `281` in `src/backend/bisheng/common/errcode/oauth2_provider.py` (`28101`–`28114`), with matching `zh-Hans`, `en`, `ja` entries in `src/frontend/packages/locales/`.

## Revision history

- 2026-11-25: corrected discovery/key metadata descriptions and hardened authorization, scopes, token concurrency, protocol responses and login return paths before the 115 verification deployment.
