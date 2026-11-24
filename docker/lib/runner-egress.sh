#!/usr/bin/env bash
# Host-owned Linux legacy iptables helper. Never run inside the runner.
# Product alignment: runner egress is unrestricted (intranet allowed), matching
# the pre-security-batch sandbox network policy. This helper still provisions
# the dedicated bridge/network and optional verify/start workflow.
set -euo pipefail
set +x
umask 077
BRIDGE=br-bsrunner
NETWORK=bisheng-runner
SUBNET=172.30.166.0/24
RUNNERS=(172.30.166.11 172.30.166.12)
STATE=/var/lib/bisheng-runner-egress
# Kept for journal compatibility with prior installs; no longer used to deny.
INTERNAL=${RUNNER_INTERNAL_CIDRS:-none}
fail() { printf 'runner-egress: %s\n' "$*" >&2; exit 1; }
rule() { "$@"; }
# Emit a deterministic command plan. No eval, no shell interpolation of input.
policy() {
  local ip
  rule iptables -N BSRE_FWD
  rule iptables -N BSRE_IN
  rule ip6tables -N BSRE6_FWD
  # Unrestricted outbound (incl. private/intranet). Retain ESTABLISHED REPLY so
  # controller→runner responses continue to work on the dedicated bridge.
  rule iptables -A BSRE_FWD -m conntrack --ctstate ESTABLISHED --ctdir REPLY -j ACCEPT
  rule iptables -A BSRE_IN -m conntrack --ctstate ESTABLISHED --ctdir REPLY -j ACCEPT
  rule iptables -A BSRE_IN -j ACCEPT
  rule iptables -A BSRE_FWD -j ACCEPT
  rule ip6tables -A BSRE6_FWD -j ACCEPT
  for ip in "${RUNNERS[@]}"; do
    rule iptables -I DOCKER-USER 1 -i "$BRIDGE" -s "$ip" -j BSRE_FWD
    rule iptables -I FORWARD 1 -i "$BRIDGE" -s "$ip" -j BSRE_FWD
    rule iptables -I INPUT 1 -i "$BRIDGE" -s "$ip" -j BSRE_IN
  done
  rule ip6tables -I FORWARD 1 -i "$BRIDGE" -j BSRE6_FWD
  rule ip6tables -I INPUT 1 -i "$BRIDGE" -j BSRE6_FWD
}
preflight() {
  [[ $(uname -s) == Linux && $EUID == 0 ]] || fail 'Linux root host required'
  for cmd in iptables ip6tables docker flock sha256sum sysctl; do command -v "$cmd" >/dev/null || fail "missing $cmd"; done
  [[ $(sysctl -n net.bridge.bridge-nf-call-iptables) == 1 ]] || fail 'bridge IPv4 netfilter must be enabled'
  [[ $(sysctl -n net.bridge.bridge-nf-call-ip6tables) == 1 ]] || fail 'bridge IPv6 netfilter must be enabled'
  iptables -S DOCKER-USER >/dev/null || fail 'Docker DOCKER-USER missing'
  [[ "$INTERNAL" == none || "$INTERNAL" =~ ^[0-9./\ ]+$ ]] || fail 'invalid internal CIDRs'
}
stopped() {
  local name
  for name in bisheng-code-runner-1 bisheng-code-runner-2; do
    [[ $(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true) != true ]] || fail "stop $name before changing policy"
  done
}
snapshot() {
  iptables -S BSRE_FWD; iptables -S BSRE_IN
  iptables -S DOCKER-USER; iptables -S FORWARD; iptables -S INPUT
  ip6tables -S BSRE6_FWD; ip6tables -S FORWARD; ip6tables -S INPUT
}
owned_snapshot() {
  snapshot
}
verify() {
  [[ -f "$STATE/policy.sha256" && -f "$STATE/rules.sha256" ]] || fail 'no applied policy journal'
  [[ $(sha256sum "${BASH_SOURCE[0]}" | cut -d ' ' -f1) == "$(<"$STATE/policy.sha256")" ]] || fail 'helper changed; review/reapply while runners stopped'
  [[ "$INTERNAL" == "$(<"$STATE/internal-cidrs")" ]] || fail 'internal CIDR review differs'
  [[ $(owned_snapshot | sha256sum | cut -d ' ' -f1) == "$(<"$STATE/rules.sha256")" ]] || fail 'policy missing or changed'
  local bin chain first
  for bin in iptables ip6tables; do
    for chain in FORWARD INPUT; do
      first=$("$bin" -S "$chain" | sed -n '2p')
      [[ "$first" == *"-i $BRIDGE "* && "$first" == *BSRE* ]] || fail 'policy hook is not first'
    done
  done
  local actual
  actual=$(docker network inspect -f '{{.Driver}}|{{.Internal}}|{{.EnableIPv6}}|{{index .Options "com.docker.network.bridge.name"}}|{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$NETWORK")
  [[ "$actual" == "bridge|false|false|$BRIDGE|$SUBNET" ]] || fail 'unexpected dedicated network topology'
  printf 'runner-egress: verified host policy (unrestricted; live packet tests still required)\n'
}
rollback() {
  stopped
  [[ -f "$STATE/undo.sh" ]] || fail 'no rollback journal'
  bash "$STATE/undo.sh"
  printf 'runner-egress: removed only owned rules; runners remain stopped\n'
}
case ${1:-} in
  plan)
    rule() { printf '%q ' "$@"; printf '\n'; }; policy; exit 0 ;;
  apply|verify|rollback|start) ;;
  *) fail 'usage: runner-egress.sh plan|apply|verify|start|rollback' ;;
esac
preflight
mkdir -p "$STATE"
[[ ! -L "$STATE" && $(stat -c %u "$STATE") == 0 ]] || fail 'unsafe state directory'
chmod 700 "$STATE"
exec 9>"$STATE/lock"
flock -x 9
case $1 in
  verify) verify ;;
  start)
    verify
    ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
    docker compose --env-file "$ROOT/.env" -f "$ROOT/docker-compose.yml" up -d code-runner-1 code-runner-2 ;;
  rollback) rollback ;;
  apply)
    stopped
    if [[ -f "$STATE/rules.sha256" ]]; then verify; exit 0; fi
    for chain in BSRE_FWD BSRE_IN; do ! iptables -S "$chain" >/dev/null 2>&1 || fail 'foreign/stale owned-name chain; do not overwrite'; done
    ! ip6tables -S BSRE6_FWD >/dev/null 2>&1 || fail 'foreign/stale IPv6 chain'
    [[ ! -e "$STATE/undo.sh" ]] || fail 'incomplete journal; review rollback before retry'
    printf '#!/usr/bin/env bash\nset -euo pipefail\n' > "$STATE/undo.sh"
    rule() {
      "$@"
      local -a undo=("$@")
      case ${undo[1]} in
        -N) undo[1]=-X ;;
        -A) undo[1]=-D ;;
        -I) undo[1]=-D; unset 'undo[3]' ;;
        *) fail 'unsupported journal operation' ;;
      esac
      local prior; prior=$(<"$STATE/undo.sh")
      { printf '#!/usr/bin/env bash\nset -euo pipefail\n'; printf '%q ' "${undo[@]}"; printf '\n'; printf '%s\n' "$prior" | tail -n +3; } > "$STATE/undo.next"
      mv "$STATE/undo.next" "$STATE/undo.sh"
    }
    if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
      docker network create --driver bridge --subnet "$SUBNET" --opt com.docker.network.bridge.name="$BRIDGE" "$NETWORK" >/dev/null
    fi
    policy
    sha256sum "${BASH_SOURCE[0]}" | cut -d ' ' -f1 > "$STATE/policy.sha256"
    owned_snapshot | sha256sum | cut -d ' ' -f1 > "$STATE/rules.sha256"
    printf '%s' "$INTERNAL" > "$STATE/internal-cidrs"
    verify ;;
esac
