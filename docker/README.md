# Existing-environment updates

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
