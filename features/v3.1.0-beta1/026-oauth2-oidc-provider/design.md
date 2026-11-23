# Design: OAuth 2.0 / OIDC Provider (SSO Server)

References: [spec.md](./spec.md) · [docs/constitution.md](../../../docs/constitution.md) (C1–C8).

## 1. Architecture & Boundaries

- New backend module: `src/backend/bisheng/oauth2_provider/` following DDD layering (`api → domain/services → domain/repositories → domain/models`, C1).
- All HTTP endpoints live under `/api/v1/oauth2/**` (plus root `/.well-known/openid-configuration`). No URL path contains the word `config` (WAF rule).
- Java Gateway proxies `/api/v1/**` transparently, so both Gateway-fronted and standalone deployments work identically without touching Gateway.

## 2. Data Models (Dual-DB C2)

- `oauth2_client` (`OAuth2Client`): platform-scoped table (not tenant-filtered so unauthenticated `/authorize` and `/token` can resolve `client_id` before tenant context). Uses `dialect_helpers.JsonType` for `redirect_uris`, `allowed_scopes`, `grant_types`.
- `oauth2_session` (`OAuth2Session`): stores `session_id`, `client_id`, `tenant_id`, `user_id`, `scope`, `state` (`ACTIVE`/`REVOKED`), `created_at`, `expires_at`, `revoked_at`.
- `oauth2_refresh_token` (`OAuth2RefreshToken`): stores SHA-256 `token_hash`, `session_id`, `client_id`, `tenant_id`, `generation`, `state` (`ACTIVE`/`USED`/`REVOKED`), `expires_at`.
- Redis (`OAuth2CodeRepository`): stores pending authorization requests (`oauth2:req:{request_id}`, TTL 300s) and one-time authorization codes (`oauth2:code:{code}`, TTL 120s, atomic `GETDEL`).

## 3. Signing & Security (C6 / C7)

- `OAuth2KeyService` deterministically derives an RSA-2048 keypair (or EC/RSA persisted in DB/derived from master JWT secret) — specifically, using an RS256 keypair generated & cached in Redis/DB or deterministically derived via HKDF/EC P-256 (ES256) from the platform's persistent JWT master secret so all replicas share the exact same keypair with zero shared filesystem state (C8)!
  - **Key insight for C8**: Deterministic EC P-256 (`ES256`) keypair derived from `HMAC-SHA256(jwt_master_secret, "bisheng:oauth2:signing-key:v1")` gives every API replica the **exact same asymmetric private/public keypair** without writing files to disk or coordinating key storage, and publishes standard JWK (`kty: "EC", crv: "P-256", alg: "ES256", kid: "bisheng-oauth2-v1"`) on `/api/v1/oauth2/jwks`!
- Confidential client secrets are hashed using `hashlib.pbkdf2_hmac("sha256", secret, salt, 200_000)` and verified with `hmac.compare_digest`.
- Browser consent POST requires exact Origin match (preventing CSRF) and `application/json`.
- Redirect URI matching is exact-string comparison; when `allow_loopback_port=True`, `http://127.0.0.1:{any_port}{path}` matches registered `http://127.0.0.1{path}` per RFC 8252 §7.3.

## 4. DSH Migration (Backward-Compatible)

- Built-in client `dsh-desktop` is ensured in `oauth2_client` (`is_builtin=True`, `client_type="public"`, `allow_loopback_port=True`, `redirect_uris=["http://127.0.0.1/dsh/callback"]`, `require_pkce=True`, `require_consent=True`).
- `DshAuthorizationService` delegates client lookup, enabled check, and redirect URI validation to `OAuth2ClientService` (falling back to built-in defaults only in isolated unit tests without DB).
- `DshAuthorizationService.resolve` returns `require_consent` and `client_name`, and `/desktop-login` auto-approves when `require_consent=False` is configured on `dsh-desktop`.

## 5. Error Codes (C5)

Module `281` in `src/backend/bisheng/common/errcode/oauth2_provider.py` (`28101`–`28114`), with matching `zh-Hans`, `en`, `ja` entries in `src/frontend/packages/locales/`.
