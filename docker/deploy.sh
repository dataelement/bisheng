#!/usr/bin/env bash
# =============================================================
# BiSheng 运维管理脚本
# 用法: ./bisheng.sh <命令> [参数]
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
COMPOSE_CMD="docker compose -f ${COMPOSE_FILE}"

# 容器名常量（与 docker-compose.yml 对应）
BACKEND_CONTAINER="bisheng-backend"
WORKER_CONTAINER="bisheng-backend-worker"

# 所有可管理的 compose service 名称
ALL_SERVICES=(backend backend_worker frontend mysql redis elasticsearch minio milvus etcd)

# ─── 颜色输出 ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()   { echo -e "${GREEN}[INFO]${RESET} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
header() { echo -e "${CYAN}${BOLD}$*${RESET}"; }

# ─── 帮助 ────────────────────────────────────────────────────
usage() {
  header "═══════════════════════════════════════════════"
  header "   BiSheng 运维管理脚本"
  header "═══════════════════════════════════════════════"
  echo ""
  echo -e "${BOLD}查看日志：${RESET}"
  echo "  $0 logs backend              实时跟踪 backend 日志（默认最近 200 行）"
  echo "  $0 logs worker               实时跟踪 backend_worker 日志（默认最近 200 行）"
  echo "  $0 logs backend -n 0         实时跟踪 backend 所有历史日志"
  echo "  $0 logs worker  -n 500       查看 worker 最近 500 行日志"
  echo ""
  echo -e "${BOLD}镜像版本管理：${RESET}"
  echo "  $0 version                   查看当前配置的镜像版本"
  echo "  $0 version v3.0.0            修改 backend、worker、frontend 的版本为 v3.0.0"
  echo ""
  echo -e "${BOLD}进入容器 Shell：${RESET}"
  echo "  $0 exec backend              进入 backend 容器"
  echo "  $0 exec worker               进入 backend_worker 容器"
  echo ""
  echo -e "${BOLD}更新镜像并重启：${RESET}"
  echo "  $0 update                    拉取最新镜像并重启 backend + worker"
  echo "  $0 update backend            只更新并重启 backend"
  echo "  $0 update worker             只更新并重启 worker"
  echo ""
  echo -e "${BOLD}重启容器：${RESET}"
  echo "  $0 restart                   重启 backend + worker"
  echo "  $0 restart backend           重启 backend"
  echo "  $0 restart worker            重启 worker"
  echo "  $0 restart frontend          重启 frontend"
  echo "  $0 restart <service...>      重启任意多个 service"
  echo ""
  echo -e "${BOLD}可用 service 名称：${RESET}"
  echo "  ${ALL_SERVICES[*]}"
  echo ""
}

# ─── service 别名解析 ─────────────────────────────────────────
resolve_service() {
  case "$1" in
    backend)                echo "backend" ;;
    worker|backend_worker)  echo "backend_worker" ;;
    frontend)               echo "frontend" ;;
    mysql)                  echo "mysql" ;;
    redis)                  echo "redis" ;;
    es|elasticsearch)       echo "elasticsearch" ;;
    minio)                  echo "minio" ;;
    milvus)                 echo "milvus" ;;
    etcd)                   echo "etcd" ;;
    *)                      echo "$1" ;;  # 原样传入，让 docker compose 自行报错
  esac
}

# ─── 查看日志 ─────────────────────────────────────────────────
cmd_logs() {
  local target="${1:-}"
  shift || true

  local lines=200

  # 解析可选 -n <行数>
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n)
        lines="${2:-200}"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done

  local service
  case "$target" in
    backend)                service="backend" ;;
    worker|backend_worker)  service="backend_worker" ;;
    *)
      error "未知目标 '${target}'，请使用 backend 或 worker"
      exit 1
      ;;
  esac

  if [ "$lines" -eq 0 ]; then
    info "实时跟踪 ${service} 所有历史日志（Ctrl+C 退出）..."
    ${COMPOSE_CMD} logs -f "${service}"
  else
    info "实时跟踪 ${service} 最近 ${lines} 行日志（Ctrl+C 退出）..."
    ${COMPOSE_CMD} logs -f --tail="${lines}" "${service}"
  fi
}

# ─── 修改版本号 ───────────────────────────────────────────────
cmd_version() {
  local new_version="${1:-}"

  if [[ -z "$new_version" ]]; then
    info "当前 docker-compose.yml 配置的版本："
    grep -E "image:.*dataelement/bisheng-(backend|frontend):" "$COMPOSE_FILE" | awk '{$1=$1};1'
    return 0
  fi

  info "正在将 backend, backend_worker, frontend 版本修改为: ${new_version}"

  # 兼容 macOS 和 Linux 的 sed -i 用法
  if sed --version 2>/dev/null | grep -q GNU; then
    sed -i -E "s|(image: dataelement/bisheng-backend):.*|\1:${new_version}|g" "$COMPOSE_FILE"
    sed -i -E "s|(image: dataelement/bisheng-frontend):.*|\1:${new_version}|g" "$COMPOSE_FILE"
  else
    # macOS/BSD sed
    sed -i '' -E "s|(image: dataelement/bisheng-backend):.*|\1:${new_version}|g" "$COMPOSE_FILE"
    sed -i '' -E "s|(image: dataelement/bisheng-frontend):.*|\1:${new_version}|g" "$COMPOSE_FILE"
  fi

  info "✅ 版本修改完成："
  grep -E "image:.*dataelement/bisheng-(backend|frontend):" "$COMPOSE_FILE" | awk '{$1=$1};1'
  warn "注意：只是修改了配置文件，若要生效请执行 '$0 update'"
}

# ─── 进入容器 ─────────────────────────────────────────────────
cmd_exec() {
  local target="${1:-}"
  local container

  case "$target" in
    backend)                container="${BACKEND_CONTAINER}" ;;
    worker|backend_worker)  container="${WORKER_CONTAINER}" ;;
    *)
      error "未知目标 '${target}'，请使用 backend 或 worker"
      exit 1
      ;;
  esac

  info "进入容器 ${container} ..."
  docker exec -it "${container}" /bin/bash 2>/dev/null \
    || docker exec -it "${container}" /bin/sh
}

# ─── 更新镜像并重启 ───────────────────────────────────────────
cmd_update() {
  local targets=()

  if [[ $# -eq 0 ]]; then
    targets=("backend" "backend_worker" "frontend")
  else
    for t in "$@"; do
      targets+=("$(resolve_service "$t")")
    done
  fi

  info "拉取最新镜像：${targets[*]}"
  ${COMPOSE_CMD} pull "${targets[@]}"

  info "重启服务（不重建依赖）：${targets[*]}"
  ${COMPOSE_CMD} up -d --no-deps "${targets[@]}"

  info "✅ 更新完成"
  ${COMPOSE_CMD} ps "${targets[@]}"
}

# ─── 重启容器 ─────────────────────────────────────────────────
cmd_restart() {
  local targets=()

  if [[ $# -eq 0 ]]; then
    targets=("backend" "backend_worker" "frontend")
  else
    for t in "$@"; do
      targets+=("$(resolve_service "$t")")
    done
  fi

  info "重启服务：${targets[*]}"
  ${COMPOSE_CMD} restart "${targets[@]}"

  info "✅ 重启完成"
  ${COMPOSE_CMD} ps "${targets[@]}"
}

# ─── 入口 ────────────────────────────────────────────────────
main() {
  if [[ $# -eq 0 ]]; then
    usage
    exit 0
  fi

  local cmd="$1"; shift

  case "$cmd" in
    logs)           cmd_logs "$@" ;;
    version)        cmd_version "$@" ;;
    exec)           cmd_exec "$@" ;;
    update)         cmd_update "$@" ;;
    restart)        cmd_restart "$@" ;;
    help|-h|--help) usage ;;
    *)
      error "未知命令: ${cmd}"
      usage
      exit 1
      ;;
  esac
}

main "$@"
