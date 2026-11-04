#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo 'Run on the Docker host as root.' >&2
  exit 1
fi
python_path=${1:?Usage: install-host-isolation.sh /absolute/path/to/python}
if [[ ! ${python_path} =~ ^/[A-Za-z0-9_./-]+$ || ! -x ${python_path} ]]; then
  echo 'A valid absolute Python executable is required.' >&2
  exit 1
fi
"${python_path}" -c 'import runtime_manager.host_isolation'
for required_file in /etc/bisheng/runtime-host-isolation.json /etc/bisheng/runtime-host-isolation.env; do
  test -f "${required_file}"
  chown root:root "${required_file}"
  chmod 600 "${required_file}"
done
unit_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sed "s|@PYTHON@|${python_path}|g" "${unit_dir}/bisheng-host-isolation.service" > /etc/systemd/system/bisheng-host-isolation.service
install -m 0644 "${unit_dir}/bisheng-host-isolation.timer" /etc/systemd/system/bisheng-host-isolation.timer
systemctl daemon-reload
systemctl start bisheng-host-isolation.service
systemctl enable --now bisheng-host-isolation.timer
