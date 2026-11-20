#!/usr/bin/env bash
# 向飞书报告离线包结果。webhook 缺失或发送失败都退出 0，不改变打包 job 的结果。
set -u

webhook="${FEISHU_WEBHOOK:-${WEBHOOK_URL:-}}"
status="${BUNDLE_STATUS:-unknown}"
version="${VERSION:-}"
arch="${ARCH:-}"
run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
text="毕昇离线包 ${version} ${arch}：${status} ${run_url}"

if [[ -z "$webhook" ]]; then
  printf '[notify-lark] 未配置 FEISHU_WEBHOOK，跳过通知\n' >&2
  exit 0
fi

payload="$(python3 -c 'import json,sys; print(json.dumps({"msg_type":"text","content":{"text":sys.argv[1]}}))' "$text" 2>/dev/null || true)"
if [[ -z "$payload" ]]; then
  printf '[notify-lark] 无法编码通知内容，跳过\n' >&2
  exit 0
fi
if ! curl -fsS -m 20 -X POST -H 'Content-Type: application/json' --data "$payload" "$webhook" >/dev/null; then
  printf '[notify-lark] webhook 发送失败，不改变打包结果\n' >&2
fi
exit 0
