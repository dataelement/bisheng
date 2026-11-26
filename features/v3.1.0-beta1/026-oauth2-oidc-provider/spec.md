# OAuth 2.0 / OIDC Provider (SSO Server)

Version: `v3.1.0-beta1` · Feature: `026-oauth2-oidc-provider` · Branch: `feat/026-oauth2-oidc-provider`

## 1. Goal

Provide a standard OAuth 2.0 / OpenID Connect (OIDC) Provider inside `bisheng-backend` so external applications, third-party services, and native desktop clients (including DSH) authenticate against BiSheng using configurable `client_id` / `redirect_uri` / `scopes` instead of bespoke per-client authorization protocols. No changes to Java Gateway are required; all endpoints live under `/api/v1/oauth2/**` (plus `/.well-known/openid-configuration`) and work both behind Gateway and in standalone deployments.

## 2. Acceptance Criteria

- **AC-01**: WHEN an administrator creates, updates, toggles, rotates secret for, or deletes an OAuth2 client via `/api/v1/oauth2/clients`, THE SYSTEM SHALL persist the client in `oauth2_client` (MySQL + DM8 compatible), store `client_secret` only as a salted hash, return the plaintext secret only once at creation/rotation, and prevent deletion of built-in clients (`is_builtin=True`).
- **AC-02**: WHEN a client initiates `GET /api/v1/oauth2/authorize` with `response_type=code`, valid `client_id`, registered `redirect_uri`, allowed `scope`, `state`, and PKCE `code_challenge` (`S256`) when required, THE SYSTEM SHALL persist a short-lived authorization request in Redis and either auto-approve (when user is logged in and `require_consent=False`) or redirect to `/oauth-consent?request_id=...`.
- **AC-03**: WHEN a logged-in browser user approves or denies a pending request on `/oauth-consent` (`POST /api/v1/oauth2/consent/{request_id}`), THE SYSTEM SHALL issue a one-time authorization `code` (TTL 120s) on approval or `error=access_denied` on denial and return the exact callback URL with `state`.
- **AC-04**: WHEN a client calls `POST /api/v1/oauth2/token` with `grant_type=authorization_code`, valid `code`, matching `client_id`, `redirect_uri`, PKCE `code_verifier` (when required), and `client_secret` (for confidential clients), THE SYSTEM SHALL atomically consume `code`, create an `oauth2_session` + `oauth2_refresh_token`, and return `access_token`, `token_type`, `expires_in`, `refresh_token` (when `offline_access` granted), `scope`, and OIDC `id_token` (when `openid` granted).
- **AC-05**: WHEN a client calls `POST /api/v1/oauth2/token` with `grant_type=refresh_token`, THE SYSTEM SHALL validate the refresh token hash, rotate the refresh token, reject reused/revoked tokens, and issue a new `access_token` + `refresh_token`.
- **AC-06**: WHEN a client calls `GET /api/v1/oauth2/userinfo` with a valid OAuth2 Bearer `access_token`, THE SYSTEM SHALL verify the token and active user/session and return standard OIDC claims (`sub`, `preferred_username`, `name`, `email`, `tenant_id`, `tenant_name`).
- **AC-07**: WHEN a client calls `POST /api/v1/oauth2/revoke`, THE SYSTEM SHALL revoke the matching refresh token / session (RFC 7009 idempotent 200).
- **AC-08**: WHEN `GET /.well-known/openid-configuration` or `GET /api/v1/oauth2/jwks` is requested, THE SYSTEM SHALL return valid OIDC discovery metadata and JWKS public keys matching `id_token` / `access_token` verification.
- **AC-09**: THE SYSTEM SHALL automatically seed/ensure the built-in `dsh-desktop` public PKCE client (`allow_loopback_port=True`, `redirect_uris=["http://127.0.0.1/dsh/callback"]`), and DSH login (`/api/v1/dsh/authorizations` + `/desktop-login`) SHALL delegate client validation, enabled status, redirect URI matching, and `require_consent` policy to `oauth2_provider` while preserving 100% backward compatibility with existing DSH desktop clients.
- **AC-10**: Platform frontend SHALL provide an OAuth2 Client management tab under System Settings (super admin only) and an `/oauth-consent` browser authorization page with full `zh-Hans`, `en`, and `ja` i18n coverage.
