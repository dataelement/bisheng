#!/usr/bin/env bash
# =============================================================
# BiSheng 运维管理脚本
# 用法: ./bisheng.sh <命令> [参数]
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
COMPOSE_CMD=(docker compose -f "${COMPOSE_FILE}")

# 容器名常量（与 docker-compose.yml 对应）
BACKEND_CONTAINER="bisheng-backend"
WORKER_CONTAINER="bisheng-backend-worker"

# 所有可管理的 compose service 名称
ALL_SERVICES=(backend backend_worker frontend mysql redis elasticsearch minio milvus etcd runtime-manager app-proxy)

# 挂在 compose profile 后面的 service。它们默认**不启动**——「应用工场运行时层
# 整层不装」是产品明确支持的形态（F054 GOV-10 / AC-59）。要带上它们，所有
# compose 命令都得加 --profile，否则 docker compose 会说 "no such service"。
PROFILE_SERVICES=(runtime-manager app-proxy)
APP_RUNTIME_PROFILE="app-runtime"

# 若参数里出现任何 profile service，就给 compose 命令补上 --profile。
# 返回补好的 compose 前缀，调用方直接用。
compose_with_profile() {
  local svc p
  local profile_args=()
  for svc in "$@"; do
    for p in "${PROFILE_SERVICES[@]}"; do
      if [[ "$svc" = "$p" ]]; then
        profile_args=(--profile "${APP_RUNTIME_PROFILE}")
        break 2
      fi
    done
  done
  if (( ${#profile_args[@]} )); then
    "${COMPOSE_CMD[@]}" "${profile_args[@]}" "$@"
  else
    "${COMPOSE_CMD[@]}" "$@"
  fi
}

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
  echo "  $0 upgrade-preview           使用目标镜像预览知识工具升级，读取 Store ID"
  echo "  $0 update --confirm-store-id <Store ID> --operator-id <用户 ID>"
  echo "                               更新服务并完成知识工具登记和权限校准"
  echo "  $0 update backend --confirm-store-id <Store ID> --operator-id <用户 ID>"
  echo "                               更新 backend 并完成知识工具升级"
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
    rtm|runtime-manager)    echo "runtime-manager" ;;
    proxy|app-proxy)        echo "app-proxy" ;;
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
    compose_with_profile logs -f "${service}"
  else
    info "实时跟踪 ${service} 最近 ${lines} 行日志（Ctrl+C 退出）..."
    compose_with_profile logs -f --tail="${lines}" "${service}"
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
  warn "版本配置已保存。请先运行 '$0 upgrade-preview'，再携带 Store ID 和操作人 ID 执行 update。"
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
cmd_upgrade_preview() {
  if [[ $# -gt 0 ]]; then
    error "用法：$0 upgrade-preview"
    return 2
  fi
  info "使用目标 backend 镜像及服务配置预览知识工具升级"
  compose_with_profile pull backend
  compose_with_profile run --rm --no-deps -T --pull never backend \
    python scripts/register_work_knowledge_tool.py
}

cmd_update() {
  local targets=()
  local remaining=()
  local store_id="" operator_id="" has_backend=false
  local target

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --confirm-store-id|--operator-id)
        if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
          error "$1 需要参数值"
          return 2
        fi
        if [[ "$1" == --confirm-store-id ]]; then store_id="$2"; else operator_id="$2"; fi
        shift 2
        ;;
      --*) error "未知参数：$1"; return 2 ;;
      *) targets+=("$(resolve_service "$1")"); shift ;;
    esac
  done
  if [[ ${#targets[@]} -eq 0 ]]; then
    targets=("backend" "backend_worker" "frontend")
  fi
  for target in "${targets[@]}"; do
    if [[ "$target" == backend ]]; then has_backend=true; else remaining+=("$target"); fi
  done
  if [[ "$has_backend" == true ]]; then
    if [[ -z "$store_id" || ! "$operator_id" =~ ^[1-9][0-9]*$ ]]; then
      error "backend 更新需要 --confirm-store-id 和正整数 --operator-id；先运行 '$0 upgrade-preview'"
      return 2
    fi
  elif [[ -n "$store_id" || -n "$operator_id" ]]; then
    error "知识工具升级参数需要同时选择 backend"
    return 2
  fi

  info "拉取最新镜像：${targets[*]}"
  compose_with_profile pull "${targets[@]}"

  if [[ "$has_backend" == true ]]; then
    # API startup owns schema migration; maintenance uses the resulting live configuration.
    info "启动 backend 并等待服务就绪"
    compose_with_profile up -d --no-deps --pull never --wait --wait-timeout 180 backend
    info "执行知识工具登记和权限校准"
    if compose_with_profile exec -T backend python scripts/register_work_knowledge_tool.py \
        --apply --confirm-store-id "$store_id" --operator-id "$operator_id"; then
      info "知识工具升级已完成"
    else
      local upgrade_status=$?
      error "backend 已更新，知识工具升级失败。请保持维护窗口，处理上方错误后重试本次 update。"
      return "$upgrade_status"
    fi
  fi
  if [[ ${#remaining[@]} -gt 0 ]]; then
    info "更新其余服务：${remaining[*]}"
    compose_with_profile up -d --no-deps --pull never --wait --wait-timeout 180 "${remaining[@]}"
  fi

  compose_with_profile ps "${targets[@]}"
  info "✅ 更新完成"
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
  compose_with_profile restart "${targets[@]}"

  info "✅ 重启完成"
  compose_with_profile ps "${targets[@]}"
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
    upgrade-preview) cmd_upgrade_preview "$@" ;;
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
