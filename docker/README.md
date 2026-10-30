# Deploy BiSheng

Run from the `docker/` directory:

```bash
cp .env.example .env
# Log in first if this host has not authenticated to the default registry:
docker login cr.dataelem.com
docker compose pull
docker compose up -d
```

`docker-compose` can be used in place of `docker compose` if the installed
version supports this Compose file (profiles and completion dependencies).
Compose V2 is recommended. `up -d` starts containers in the background; use
`ps` and `logs` to check readiness.

The optional wrapper is `bash docker/install.sh` from the checkout root. It
copies the template only when `.env` does not exist, validates configuration,
pulls images and runs `up -d`. Existing `.env` contents are preserved; there is
no automatic variable merge, mirror rewrite, architecture guess or credential
rotation. Deployment needs Bash and common system tools, not host Python or jq.
`--prepare-only` generates configuration without pulling or starting services.
For a first deployment, run `bash docker/install.sh` without arguments: Gateway
is disabled and there is no enable/disable prompt. An existing Gateway profile
in `.env` is preserved on subsequent runs; use `--no-gateway` to disable it.

All template images use `cr.dataelem.com`. Change complete `*_IMAGE` values in
`.env` to use another registry or an architecture-specific tag. MinIO retains
`minioadmin/minioadmin`, MySQL retains the existing `1234` password, and the
sandbox retains its existing development token. Keep existing deployment
credentials when upgrading. Image versions remain pinned; downloading a newer
source checkout does not rebuild the backend/frontend images.

Compose creates the platform bridge as `bisheng-network` (configurable with
`BISHENG_NETWORK_NAME`) and the sandbox bridge as `bisheng-sandbox`. The logical
Compose key `default` is explicitly named; no project-derived `*_default`
network is created. Existing application-runtime isolation networks remain
separate. Changing the network of an existing installation recreates attached
containers and can interrupt requests.

## Gateway (optional)

Gateway and its one-time database initializer are in the same Compose file,
behind the `gateway` profile. To configure and deploy:

```bash
bash docker/install.sh --gateway \
  --license-file /secure/path/license.txt \
  --public-url https://bisheng.example.com
```

Gateway requires a readable user-supplied **license file path**, passed through
`--license-file` or recorded in `.env` as `BISHENG_GATEWAY_LICENSE_FILE`. When Gateway is explicitly enabled, an
interactive installation can ask for this path; leaving it empty skips Gateway
and restores direct routing, even if an old license string is cached in `.env`.
Direct license-text input is not supported. A supplied but missing/unreadable or
empty file is an error. The original file is also mounted read-only, with host
path creation disabled, so an unknown path cannot silently create a directory.
Missing Gateway HMAC/database secrets are generated only for this
optional mode and are preserved on later runs. MySQL's existing health check,
`gateway-db-init`, and `depends_on` initialize the six Gateway tables and its
dedicated user before Gateway starts. The script starts Gateway before
recreating frontend and selects generated Nginx snippets for browser APIs and
WebSocket. Internal, app and MinIO routes keep their original targets. SSO
providers are configured separately in `gateway/config/application.yml`.

`--no-gateway` restores direct backend routing and removes only the `gateway`
profile from `.env`. Other profiles and database contents are preserved. It
does not stop an already-running Gateway; use `docker compose --profile gateway
stop gateway` if that is also required.

The wrapper checks that a license file was supplied and is readable. Gateway itself validates its
authenticity and expiry; inspect Gateway logs and the product before declaring
installation successful. The installer no longer parses license-status JSON or
performs full API readiness tests.

## Known prerequisites and gaps

- The registry requires authentication. A `401` is not proof that a tag is
  missing; authenticate and pull using your authorized registry account.
- The user-supplied temporary sandbox image is
  `cr.dataelem.com/dataelement/bisheng-sandbox:feat_3.0.0`. The authenticated
  2026-10-29 check found it and the other base-stack defaults present as AMD64.
  Sandbox ARM CI is still being developed; this deployment test is AMD64 only.
- ARM needs compatible images for every enabled service. Multi-architecture
  tags are selected by Docker automatically; single-architecture tags need
  explicit replacement. Gateway v1.8.0 uses `v1.8.0-arm64`. Current base-stack
  CR defaults were observed as AMD64, not multi-architecture indexes.
- VibeApp's default CR runtime-manager/app-proxy/socket-proxy addresses are
  not published at the configured tags and return 404. Older Docker Hub
  `v3.0.0-test-vibe-{amd64,arm64}` images exist for all seven Docker runtime
  component families; they are not substituted automatically for the current
  release. See the [image audit](../features/v3.0.0/114-compose-install/vibe-image-audit.md).
- Port conflicts, host resources, Elasticsearch host settings, startup/migration
  errors and unavailable external model/document services can still prevent a
  working product. First registration and model configuration remain required.

A real empty-data AMD64 deployment on 192.168.106.166 passed base-service, first
registration/login and both sandbox execution checks. Image downloading needed
verified cache preloading due to that host's Docker transport problems; see the
[deployment record](../features/v3.0.0/114-compose-install/deployment-166.md) for scope.

## VibeApp image publishing

The Runtime delivery images workflow publishes nine BiSheng image families to
both Docker Hub and `cr.dataelem.com`, using native AMD64/ARM64 runners. It runs
on `v*` tag pushes or a manual dispatch with a new `version`; branch pushes and
PRs do not publish images. The four service images also receive a two-platform
version index. `runtime-profiles-cr` contains the CR release/profile catalogs.
This change does not backfill missing releases or mirror third-party
socket-proxy images. See the [CI/CD flow](../features/v3.0.0/114-compose-install/runtime-image-cicd.md)
for the build order, credentials, tags and failure behavior.

## Existing-environment updates

Compose image references live in `.env`; use the template when adding new
settings manually. `BISHENG_SANDBOX_IMAGE` replaces `SANDBOX_IMAGE_TAG`.

Use `deploy.sh` from the matching release checkout to update an existing Compose
deployment. Keep the release's Compose file, mounted entrypoint and image versions
together. Run one deployment job in a maintenance window; control ingress and
queue consumers according to the environment's release procedure.

## Work knowledge retrieval

The backend image must include the Work knowledge registration script from PR
#2546. Set the intended image version with `bash docker/deploy.sh version <tag>`,
then preview the target image against the service's existing configuration:

```bash
bash docker/deploy.sh upgrade-preview
```

This pulls the configured backend image and runs a read-only catalog/permission
preview in a disposable container with the backend service's mounts, environment
and network. Existing infrastructure must be running. The preview requires a
compatible database schema and CURRENT F048 permission runtime; complete their
version-specific prerequisites when the preview reports an error.

Use the preview's Store ID and the actual audit operator's user ID to update:

```bash
bash docker/deploy.sh update --confirm-store-id <store-id> --operator-id <user-id>
# To update only the backend:
bash docker/deploy.sh update backend --confirm-store-id <store-id> --operator-id <user-id>
```

For an update containing `backend`, the release script:

1. Validates the required confirmation arguments before Docker operations.
2. Pulls the selected images, starts the backend and waits up to 180 seconds for
   readiness. The API entrypoint owns the schema migration.
3. Executes the knowledge tool's registration and permission reconciliation using
   the running backend's configuration. Apply exits successfully only after the
   tool exists and its permission projection is CURRENT.
4. Updates the remaining selected services, waits for readiness, and reports
   completion after the service status command succeeds.

Any failed stage returns a nonzero exit status and stops subsequent stages. If
knowledge maintenance fails, the backend has already been updated; maintain the
release window, resolve the reported error and repeat the same update command.
Registration and permission reconciliation support repeated execution. The
deployment script leaves schema/data recovery to the release operator.

Worker-only and frontend-only updates retain their selected service scope.
`restart` restarts the existing deployment. Direct `docker compose up` and external
deployment pipelines must explicitly run the same maintenance operation and
require its successful exit before declaring their release complete; see
[`src/backend/scripts/README.md`](../src/backend/scripts/README.md).

After deployment, verify ordinary-user tool discovery and single-space plus K1/K2
multi-space retrieval with the expected document citations. Deployment checks and
real-account acceptance are recorded separately.
