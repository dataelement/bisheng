#!/usr/bin/env bash
# =============================================================================
# 应用工场运行时层（F054）compose 形态静态校验
#
# 为什么需要它：runtime-manager 与 app-proxy 的配置**全部走环境变量**，而两个
# 进程都是「配错了照样启动、照样 healthy」的形状——
#   · app-proxy 的密钥缺失只 logger.error，不退出（main.py），然后每个请求
#     fail-closed 渲染「暂时无法访问」；
#   · 变量名写错等同于没写，进程静静地用 127.0.0.1 默认值指向自己。
# 所以「容器 Up、systemd active」在这一层完全不构成证据。3.0 的 compose 文件
# 就是这样带着两个没人读的变量名（APP_PROXY_BACKEND_BASE_URL /
# APP_PROXY_HMAC_SECRET）、又漏掉 APP_PROXY_MANAGER_BASE 进了仓；
# systemd 那份单元文件早把这个坑逐字记下来并修了，compose 这份漏了。
#
# 这个脚本把「compose 写的」和「config.py 读的」对起来，不需要起任何容器。
#
# 用法：
#   bash docker/verify-app-runtime-compose.sh            # 跑静态校验
#   bash docker/verify-app-runtime-compose.sh --howto    # 打印最小真机验证步骤
# 退出码：0 = 全部通过；1 = 有断言失败；2 = 环境不满足（缺 docker compose 等）
#
# 静态校验管不到的部分（bind 真落在哪、两张网真通不通）照 --howto 跑一遍即可：
# 只需要构建 runtime-manager / app-proxy 两个很小的镜像，不必构建平台镜像。
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# 允许覆盖，方便对着改坏的副本做「这个门确实拦得住」的反向自测。
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/docker-compose.yml}"
PROFILE="app-runtime"

# 不带 profile 的 service 数 / 带 profile 的 service 数。
# 「整层不装」是产品明确支持的形态（GOV-10 / AC-59）：不带 --profile 起来时这两个
# service 根本不创建，平台其余部分零变化。这个不等式一旦被破坏（比如有人顺手把
# profiles 删了），默认装机就会多起两个容器并要求配密钥。
EXPECTED_SERVICES_WITHOUT_PROFILE=11
EXPECTED_SERVICES_WITH_PROFILE=13

RED='\033[0;31m'; GREEN='\033[0;32m'; BOLD='\033[1m'; RESET='\033[0m'

fail_count=0
pass()  { echo -e "  ${GREEN}✓${RESET} $*"; }
fail()  { echo -e "  ${RED}✗${RESET} $*"; fail_count=$((fail_count + 1)); }
head_() { echo -e "${BOLD}$*${RESET}"; }

# ─── 0. 环境 ────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo -e "${RED}[SKIP]${RESET} 找不到 docker，无法解析 compose 文件" >&2
  exit 2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo -e "${RED}[SKIP]${RESET} 找不到 docker compose v2+" >&2
  exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo -e "${RED}[SKIP]${RESET} 找不到 python3" >&2
  exit 2
fi

# ─── --howto：最小真机验证 ───────────────────────────────────────────────────
if [ "${1:-}" = "--howto" ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  cat <<'HOWTO'
═══ 只起这两个新 service 做一次最小验证 ═══

前提：本机有 docker + docker compose v2。**不需要**构建或拉取平台镜像
（backend / frontend / milvus 一个都不起）。

  cd docker

# 0) 静态门先过
  bash verify-app-runtime-compose.sh

# 1) 只构建这两个（build context 是 ../src/{runtime-manager,app-proxy}，都很小）
  docker compose --profile app-runtime build runtime-manager app-proxy

# 2) 只起这两个。--no-deps 是关键：app-proxy depends_on backend，
#    不加的话 compose 会把 backend 连同 mysql/redis/openfga 一起拖起来。
#    密钥随便给，两边一致即可；数据根指一个本机可写的绝对路径
#    （macOS 上 /opt 默认不在 Docker Desktop 的共享目录里，务必改）。
  export BISHENG_RTM_HMAC_SECRET=dev-rtm-secret
  export BISHENG_APP_PROXY_HMAC_SECRET=dev-proxy-secret
  export BISHENG_APP_DATA_ROOT=/tmp/bisheng-app-data
  docker compose --profile app-runtime up -d --no-deps runtime-manager app-proxy

# 3) 断言。注意：**「容器 Up / healthy」在这一层不构成任何证据**——
#    两个进程都是「配错了照样启动」的形状，所以下面每条都要亲眼看输出。

# 3.1 网络存在、实名没被项目名前缀污染（缺陷 2）
  docker network inspect bisheng-apps --format '{{.Name}}'
  # 期望：bisheng-apps

# 3.2 两个容器都接在 bisheng-apps 与 docker_default 上（缺陷 2）
  docker inspect bisheng-runtime-manager --format '{{range $n,$_ := .NetworkSettings.Networks}}{{$n}} {{end}}'
  docker inspect bisheng-app-proxy       --format '{{range $n,$_ := .NetworkSettings.Networks}}{{$n}} {{end}}'
  # 期望两行都含：bisheng-apps docker_default

# 3.3 变量名真的被读进去了（缺陷 1）——只有这一条能证明；env 里有变量不算
  docker exec bisheng-app-proxy python -c "from app_proxy.config import load_config as l; c=l(); print(c.backend_base, c.manager_base, bool(c.backend_secret), bool(c.manager_secret))"
  # 期望：http://backend:7860 http://runtime-manager:8091 True True
  # 若看到 http://127.0.0.1:7860 ... False False，就是变量名又漂了。

  docker exec bisheng-runtime-manager python -c "from runtime_manager.config import load_config as l; c=l(); print(c.data_root, c.host_data_root, bool(c.hmac_secret))"
  # 期望：/app-data /tmp/bisheng-app-data True

# 3.4 两个进程活着（/healthz 是唯一免签名的端点）
  docker exec bisheng-runtime-manager python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8091/healthz').read())"
  docker exec bisheng-app-proxy       python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8090/healthz').read())"

# 3.5 预检自检。/v1/runtime/status 要 HMAC 签名，签名串 = METHOD + \n + PATH + \n + body
  docker exec bisheng-runtime-manager python -c '
import hashlib, hmac, json, os, urllib.request
secret = os.environ["RTM_HMAC_SECRET"]; path = "/v1/runtime/status"
sig = hmac.new(secret.encode(), ("GET\n" + path + "\n").encode(), hashlib.sha256).hexdigest()
req = urllib.request.Request("http://127.0.0.1:8091" + path, headers={"X-Signature": sig})
for c in json.load(urllib.request.urlopen(req))["preflight"]:
    print(("OK  " if c["ok"] else "FAIL"), c["name"], "-", c["detail"])
'
  # 期望：application_network / host_data_root_mapping / data_root_writable 三条都 OK。
  # base_images 会 FAIL（本机还没拉运行时基础镜像），与本次修复无关。

# 3.6 bind 语义（缺陷 3）——容器内写的东西必须出现在**宿主**的数据根下
  docker exec bisheng-runtime-manager sh -c 'mkdir -p /app-data/apps/probe/db && echo hi > /app-data/apps/probe/db/x'
  cat "${BISHENG_APP_DATA_ROOT}/apps/probe/db/x"     # 期望：hi
  # 反例长什么样：修复前 manager 交给宿主 dockerd 的 bind 源写的是容器内路径，
  # 宿主会在 /app-data/... 凭空建一个空目录，上面这个 cat 会找不到文件。

# 4) 收
  docker compose --profile app-runtime down

# 5) 端到端（真发一个应用）还需要 backend：backend 侧要有
#    app_runtime.enabled=true / manager_base_url=http://runtime-manager:8091 /
#    manager_hmac_secret 与 proxy_hmac_secret 与上面两个环境变量一致。
#    模板见 docker/bisheng/config/config.yaml 的 app_runtime: 段（默认 enabled: false）。
#    ⚠️ 那段配置要求 backend 镜像已认识 app_runtime 这个顶级键（v3.0+）；
#    加在旧镜像上后端会拒绝启动（表现为容器反复重启，不是"功能没生效"）。
HOWTO
  exit 0
fi

head_ "═══ 应用工场运行时层 compose 校验 ═══"
echo "compose: ${COMPOSE_FILE}"
echo ""

# ─── 1. compose 可解析（两种 profile 组合都要过）──────────────────────────────
head_ "[1/4] compose 语法与插值"
if err=$(docker compose -f "${COMPOSE_FILE}" config -q 2>&1); then
  pass "不带 profile 解析通过"
else
  fail "不带 profile 解析失败：${err}"
fi
if err=$(docker compose -f "${COMPOSE_FILE}" --profile "${PROFILE}" config -q 2>&1); then
  pass "带 --profile ${PROFILE} 解析通过"
else
  fail "带 --profile ${PROFILE} 解析失败：${err}"
fi

# ─── 2. profile 表达仍然成立 ─────────────────────────────────────────────────
head_ "[2/4] profile 计数（「整层不装」形态）"
n_without=$(docker compose -f "${COMPOSE_FILE}" config --services 2>/dev/null | grep -c . || true)
n_with=$(docker compose -f "${COMPOSE_FILE}" --profile "${PROFILE}" config --services 2>/dev/null | grep -c . || true)
if [ "${n_without}" = "${EXPECTED_SERVICES_WITHOUT_PROFILE}" ]; then
  pass "默认（不带 profile）= ${n_without} 个 service"
else
  fail "默认 service 数 = ${n_without}，期望 ${EXPECTED_SERVICES_WITHOUT_PROFILE}（改了 service 数就同步改本脚本的期望值）"
fi
if [ "${n_with}" = "${EXPECTED_SERVICES_WITH_PROFILE}" ]; then
  pass "带 --profile ${PROFILE} = ${n_with} 个 service"
else
  fail "带 profile 的 service 数 = ${n_with}，期望 ${EXPECTED_SERVICES_WITH_PROFILE}"
fi

# ─── 3/4. 环境变量契约 + 网络（交给 python 做，需要读 config.py 的 AST）──────
head_ "[3/4] 环境变量名 ↔ config.py 读取点"
compose_json="$(docker compose -f "${COMPOSE_FILE}" --profile "${PROFILE}" config --format json 2>/dev/null)"
if [ -z "${compose_json}" ]; then
  fail "无法导出 compose JSON"
  echo ""
  echo -e "${RED}校验失败${RESET}"
  exit 1
fi

# 2>&1：python 侧真炸了要看得见 traceback，而不是静悄悄少几行断言。
python_out=$(printf '%s' "${compose_json}" | python3 "${SCRIPT_DIR}/verify_app_runtime_compose.py" "${REPO_ROOT}" 2>&1)
python_rc=$?
echo "${python_out}"
if [ "${python_rc}" -ne 0 ]; then
  fail_count=$((fail_count + python_rc))
fi

echo ""
if [ "${fail_count}" -eq 0 ]; then
  echo -e "${GREEN}${BOLD}全部通过${RESET}"
  exit 0
fi
echo -e "${RED}${BOLD}${fail_count} 项失败${RESET}"
exit 1
