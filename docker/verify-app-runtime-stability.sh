#!/usr/bin/env bash
# =============================================================================
# 应用工场运行时层（F054）稳定性验收 —— 真机一遍过
#
# 这个脚本是 AC-49 的**形态适配器**，不是用例本身。
# 用例本身在 src/backend/test/app_runtime/test_stability_portable.py：那份文件
# 只用形态无关的意图 RPC 与 phase 取值，F059 的 k8s 形态原样跑同一份。但有三
# 件事任何 mock 都证明不了——真的杀掉执行体之后多久恢复、运行时服务重启期间
# 入口是否零中断、状态文件丢了之后会不会自己对齐——它们必须在真机上计时。
#
# 覆盖：AC-20（自愈 ≤5 分钟）· AC-22（运行时服务重启期间应用持续可用）·
#       AC-46（人为搞崩一个应用不影响平台与其它应用）· AC-50（对齐窗口内自动对齐）
# 不覆盖（写清楚而不是假装覆盖）：
#   · AC-20 第二类「进程活着但健康检查一直失败」——需要应用配合把健康端点改成
#     500，脚本无从代劳；--howto 给了手工步骤。
#   · AC-47 的限额生效——那是 `docker inspect` 的静态核对，属于 T075 的上线自检。
#
# 用法（在部署机上，如 114）：
#   bash docker/verify-app-runtime-stability.sh --slug <应用slug> --yes
#   bash docker/verify-app-runtime-stability.sh --howto
# 可选：--base-url https://127.0.0.1:4101（默认读 APP_ENTRY_BASE_URL 或 http://127.0.0.1:8090）
#
# ⚠️ 会真的杀掉这个应用的执行体、真的重启 runtime-manager。**不要在生产上跑**，
#    也不要挑一个正在被人用的应用。所以必须显式带 --yes。
# 退出码：0 = 全通过；1 = 有断言失败；2 = 环境不满足 / 用法不对
# =============================================================================

set -uo pipefail

SLUG=""
BASE_URL="${APP_ENTRY_BASE_URL:-http://127.0.0.1:8090}"
CONFIRMED=0
# AC-20 的预算：spec 写的是 5 分钟，留同样的 5 分钟，不放宽。
RECOVERY_BUDGET_SECONDS="${RECOVERY_BUDGET_SECONDS:-300}"
PLATFORM_URL="${PLATFORM_URL:-http://127.0.0.1:7860/api/v1/env}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BOLD='\033[1m'; RESET='\033[0m'
fail_count=0
pass()  { echo -e "  ${GREEN}✓${RESET} $*"; }
fail()  { echo -e "  ${RED}✗${RESET} $*"; fail_count=$((fail_count + 1)); }
note()  { echo -e "  ${YELLOW}·${RESET} $*"; }
head_() { echo -e "\n${BOLD}$*${RESET}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --slug)      SLUG="${2:-}"; shift 2 ;;
    --base-url)  BASE_URL="${2:-}"; shift 2 ;;
    --yes)       CONFIRMED=1; shift ;;
    --howto|-h|--help) HOWTO=1; shift ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

if [ "${HOWTO:-0}" = "1" ]; then
  cat <<'HOWTO'
═══ 手工补跑的两段（脚本代劳不了） ═══

1) AC-20 第二类：进程活着、健康检查一直失败 → 检测窗口内重建
   需要应用自己能把健康端点切成 500。带 /__fail_health 开关的示例应用最省事：

     curl -s "$BASE_URL/apps/<slug>/__fail_health"      # 应用从此对健康检查答 500
     date +%s; while ! curl -sf "$BASE_URL/apps/<slug>/" >/dev/null; do sleep 5; done; date +%s
     # 两个时间戳之差 ≤ 300。注意 docker 的 restart policy **不会**管这种情况，
     # 动手的是 runtime-manager 的 reconciler（连续 2 轮 unhealthy 即重建）。
     journalctl -u bisheng-runtime-manager | grep rtm.rebuild | tail -3

2) AC-47：限额真的落在这个应用上
     docker inspect "$(docker ps --filter label=bisheng.app-id=<app_id> -q)" \
       --format '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}} {{.HostConfig.ReadonlyRootfs}}'
   期望：与该应用档位的 vCPU / MiB 一致，且 ReadonlyRootfs=true。
HOWTO
  exit 0
fi

if [ -z "$SLUG" ]; then
  echo "用法：bash docker/verify-app-runtime-stability.sh --slug <应用slug> --yes" >&2
  exit 2
fi
if [ "$CONFIRMED" != "1" ]; then
  echo "这个脚本会杀执行体、重启 runtime-manager。确认不是生产环境后加 --yes 再跑。" >&2
  exit 2
fi
command -v docker >/dev/null 2>&1 || { echo "找不到 docker" >&2; exit 2; }
command -v curl   >/dev/null 2>&1 || { echo "找不到 curl" >&2; exit 2; }

ENTRY="${BASE_URL%/}/apps/${SLUG}/"

# systemd 形态用 systemctl，compose 形态用 docker compose；两种都不在就退 2，
# 不要猜——猜错的后果是「重启了个不相干的东西，然后报告零中断」。
if systemctl is-active bisheng-runtime-manager >/dev/null 2>&1; then
  FORM="systemd"
  restart_runtime() { systemctl restart bisheng-runtime-manager; }
  stop_runtime()    { systemctl stop bisheng-runtime-manager; }
  start_runtime()   { systemctl start bisheng-runtime-manager; }
elif docker ps --format '{{.Names}}' | grep -qx bisheng-runtime-manager; then
  FORM="compose"
  restart_runtime() { docker restart bisheng-runtime-manager >/dev/null; }
  stop_runtime()    { docker stop bisheng-runtime-manager >/dev/null; }
  start_runtime()   { docker start bisheng-runtime-manager >/dev/null; }
else
  echo "runtime-manager 既不是 active 的 systemd 单元，也没有同名容器——先确认这台机器装了运行时层" >&2
  exit 2
fi

entry_ok() { curl -sf -o /dev/null --max-time 10 "$ENTRY"; }
platform_ok() { curl -sf -o /dev/null --max-time 10 "$PLATFORM_URL"; }

app_exec_body() {
  # 执行体的名字是 bisheng-app-{slug}-g{generation}，重建会换名字，所以每次重新查。
  docker ps --format '{{.Names}}' | grep -E "^bisheng-app-${SLUG}(-|$)" | head -1
}

echo -e "${BOLD}形态=${FORM}  入口=${ENTRY}  恢复预算=${RECOVERY_BUDGET_SECONDS}s${RESET}"

head_ "0. 前置：应用现在是可访问的"
if entry_ok; then pass "入口 200"; else fail "入口现在就打不开，先修好再谈稳定性"; exit 1; fi
BODY="$(app_exec_body)"
if [ -n "$BODY" ]; then pass "执行体：$BODY"; else fail "找不到该应用的执行体"; exit 1; fi

head_ "1. AC-20 第一类 + AC-46：杀掉执行体，计时到恢复"
docker kill "$BODY" >/dev/null 2>&1 || true
started=$(date +%s)
platform_broken=0
recovered=0
while [ $(( $(date +%s) - started )) -lt "$RECOVERY_BUDGET_SECONDS" ]; do
  platform_ok || platform_broken=1
  if entry_ok; then recovered=1; break; fi
  sleep 5
done
elapsed=$(( $(date +%s) - started ))
if [ "$recovered" = "1" ]; then
  pass "AC-20：${elapsed}s 内自动恢复（预算 ${RECOVERY_BUDGET_SECONDS}s）"
else
  fail "AC-20：${RECOVERY_BUDGET_SECONDS}s 内没有恢复"
fi
if [ "$platform_broken" = "0" ]; then
  pass "AC-46：恢复期间平台主功能持续可用"
else
  fail "AC-46：恢复期间平台自身出现不可用——一个应用崩溃不该波及平台"
fi

head_ "2. AC-22：重启运行时服务，期间持续请求入口"
restart_runtime
misses=0
for _ in $(seq 1 20); do
  entry_ok || misses=$((misses + 1))
  sleep 1
done
if [ "$misses" = "0" ]; then
  pass "AC-22：20 次连续请求零中断（运行时服务不在请求路径上）"
else
  fail "AC-22：重启期间有 ${misses}/20 次请求失败——说明入口链路依赖了这个进程"
fi

head_ "3. AC-50：运行时服务不在时删掉执行体，起回来后应自动对齐"
stop_runtime
BODY="$(app_exec_body)"
if [ -n "$BODY" ]; then docker rm -f "$BODY" >/dev/null 2>&1 || true; fi
start_runtime
started=$(date +%s)
aligned=0
while [ $(( $(date +%s) - started )) -lt "$RECOVERY_BUDGET_SECONDS" ]; do
  if entry_ok; then aligned=1; break; fi
  sleep 5
done
elapsed=$(( $(date +%s) - started ))
if [ "$aligned" = "1" ]; then
  pass "AC-50：启动对齐在 ${elapsed}s 内重建了缺失的实例，无人工干预"
else
  fail "AC-50：${RECOVERY_BUDGET_SECONDS}s 内没有自动对齐"
fi

head_ "4. 未覆盖的两段"
note "AC-20 第二类（健康检查持续失败）与 AC-47（限额核对）：bash $0 --howto"

echo
if [ "$fail_count" = "0" ]; then
  echo -e "${GREEN}${BOLD}全部通过${RESET}"
  exit 0
fi
echo -e "${RED}${BOLD}${fail_count} 条失败${RESET}"
exit 1
