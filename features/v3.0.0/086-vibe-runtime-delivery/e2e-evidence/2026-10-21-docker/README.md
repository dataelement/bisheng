# 2026-10-21 Docker follow-up evidence

Checkpoint: `5131b81194a5fa390593e58d822bcbde52b6ca64` plus the six uncommitted bootstrap fix/test files hashed in `quality-and-startup-observation.json`.

Only whitelisted, sanitized outputs are retained. No environment file, identity/password file, desired-state backup, Docker Config.Env, HMAC secret or runtime credential is included. `sha256-export.json` hashes every evidence file except itself. Local temporary drivers used the real public APIs; SQL fault injection was restricted to the disposable `e2e_f086_platform` database and the listed test apps. CONNECT policy revocation used a scoped SQL fault; WebSocket visitor revocation used the formal permission Grant API.

The first fresh-start log was inspected before service replacement; its observed values are explicitly recorded as an observation. Backend/worker mounted the current checkout source. Other v2 service/runtime images reused the already verified cached native amd64 builds. The legacy manager image used source from `4aa9ce69b2830b81162fe631b9c801057c40ee8b`, with its original MinIO dependencies supplied for the isolated v1 migration test. No public image was released.

`upgrade-first-apply.json` is the first import; `upgrade-apply.json` is the idempotent repeat. Rollback was tested before import for the legacy application, and does not claim that an old manager can manage bundle deployments. Historical version comparisons include frozen payloads and terminal state, excluding mutable update_time. The retained attachment was read with SDK 0.1.1 through the new backend endpoint after rebind.

`docker-cleanup.json` confirms all dedicated services/networks/data/credentials were removed and all 26 original business containers retained identical full IDs. Cached images were preserved. See ../../live-validation.md for remaining gates; this directory does not establish full feature delivery.
