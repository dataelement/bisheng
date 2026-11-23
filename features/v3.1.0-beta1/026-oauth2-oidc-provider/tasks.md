# Tasks: OAuth 2.0 / OIDC Provider (SSO Server)

- [x] Wave 1.1: Add error codes (`28101`–`28114`) in `common/errcode/oauth2_provider.py`
- [x] Wave 1.2: Implement `oauth2_provider` SQLModel models (`oauth2_client`, `oauth2_session`, `oauth2_refresh_token`) and repositories
- [x] Wave 1.3: Implement `OAuth2KeyService` (deterministic ES256 + JWKS), `OAuth2ClientService`, `OAuth2AuthService`
- [x] Wave 1.4: Implement `/api/v1/oauth2/**` & `/.well-known/oauth-authorization-server` endpoints, register in `api/router.py`, `main.py`, and `http_middleware.py`
- [x] Wave 2.1: Integrate `DshAuthorizationService` & `DshLogin` with built-in `dsh-desktop` OAuth2 client (`require_consent`, `enabled`, `redirect_uris`)
- [x] Wave 3.1: Add frontend API client, `/oauth-consent` page, SystemPage OAuth2 Clients tab, and `zh-Hans`/`en-US`/`ja` locales + `api_errors`
- [x] Wave 4.1: Write backend unit/integration tests (`test/oauth2_provider/`) and verify `pytest`, `arch-guard.sh`, `ruff`, `typecheck`, `eslint`, `check-i18n`
- [ ] Wave 4.2: Commit, push `feat/026-oauth2-oidc-provider`, and open PR to `main`
