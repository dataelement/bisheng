#!/usr/bin/env bash
# 可选。正常升级直接跑对应 hop，不必单独跑本脚本。
# 用法: bash set-images.sh 2.3-beta1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# 默认值可被环境变量覆盖；compose 路径一律自动发现，不写死。
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${IMAGE_2_3_BETA1:=dataelement/bisheng-backend:v2.3.0-beta1}"
: "${IMAGE_FRONTEND_2_3_BETA1:=dataelement/bisheng-frontend:v2.3.0-beta1}"
: "${IMAGE_2_3:=dataelement/bisheng-backend:v2.3.0}"
: "${IMAGE_FRONTEND_2_3:=dataelement/bisheng-frontend:v2.3.0}"
: "${IMAGE_2_4_BETA1:=dataelement/bisheng-backend:v2.4.0-beta1}"
: "${IMAGE_FRONTEND_2_4_BETA1:=dataelement/bisheng-frontend:v2.4.0-beta1}"
: "${IMAGE_2_4:=dataelement/bisheng-backend:v2.4.0}"
: "${IMAGE_FRONTEND_2_4:=dataelement/bisheng-frontend:v2.4.0}"
: "${TARGET_BACKEND_IMAGE:=dataelement/bisheng-backend:v2.4.0}"
: "${TARGET_FRONTEND_IMAGE:=dataelement/bisheng-frontend:v2.4.0}"
# shellcheck disable=SC1091
source "${ROOT}/lib/common.sh"
load_env
discover_deployment

hop="${1:-}"
case "${hop}" in
  2.3-beta1) be="${IMAGE_2_3_BETA1}"; fe="${IMAGE_FRONTEND_2_3_BETA1}" ;;
  2.3)       be="${IMAGE_2_3}"; fe="${IMAGE_FRONTEND_2_3}" ;;
  2.4-beta1) be="${IMAGE_2_4_BETA1}"; fe="${IMAGE_FRONTEND_2_4_BETA1}" ;;
  2.4)       be="${IMAGE_2_4}"; fe="${IMAGE_FRONTEND_2_4}" ;;
  2.5)       be="${TARGET_BACKEND_IMAGE}"; fe="${TARGET_FRONTEND_IMAGE}" ;;
  *)
    echo "用法: bash set-images.sh 2.3-beta1|2.3|2.4-beta1|2.4|2.5" >&2
    exit 2
    ;;
esac

rewrite_compose_images "${be}" "${fe}"
grep -n "image:" "${COMPOSE_FILE}" | grep -E "bisheng-backend|bisheng-frontend" || true
