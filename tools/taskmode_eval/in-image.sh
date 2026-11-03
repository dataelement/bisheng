#!/usr/bin/env bash
# Run a harness script inside the platform's backend image (for docker-compose deployments whose
# host Python lacks python-docx/python-pptx/openpyxl/httpx). The pack directory is bind-mounted at
# the same path and the host network is used, so --base-url http://127.0.0.1:<backend port> works.
#
#   harness/in-image.sh setup_env.py --base-url http://127.0.0.1:7861 ...
#   harness/in-image.sh run.py --cases core
#
# BACKEND_CONTAINER (default bisheng-test-backend) picks the image; DB_URL is passed through if set.
set -euo pipefail
HARNESS="$(cd "$(dirname "$0")" && pwd)"
PACK="$(dirname "$HARNESS")"
CONTAINER="${BACKEND_CONTAINER:-bisheng-test-backend}"
IMAGE="$(docker inspect "$CONTAINER" --format '{{.Config.Image}}')"
SCRIPT="$1"; shift
exec docker run --rm --network host -e TZ=Asia/Taipei ${DB_URL:+-e DB_URL} \
  -v "$PACK:$PACK" -w "$PACK" --entrypoint python "$IMAGE" -I "$HARNESS/$SCRIPT" "$@"
