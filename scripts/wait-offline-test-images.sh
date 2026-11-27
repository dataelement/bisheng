#!/usr/bin/env bash
# Wait for this test tag's native images, fail early when an upstream build failed.
set -euo pipefail
python3 - "$@" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

images = [line.split()[2] for line in Path(sys.argv[1]).read_text().splitlines()
          if line.startswith('BISHENG_')]
deadline = time.monotonic() + 5400
while True:
    missing = []
    for image in images:
        result = subprocess.run(['docker', 'manifest', 'inspect', image], capture_output=True, timeout=60)
        if result.returncode:
            missing.append(image)
    if not missing:
        print('Native images ready for offline test bundle', flush=True)
        break
    url = ('https://api.github.com/repos/%s/actions/runs?head_sha=%s&event=push&per_page=100'
           % (os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']))
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        runs = json.load(response)['workflow_runs']
    failed = [run for run in runs if run['name'] in ('CI', 'Runtime delivery images')
              and run['head_branch'] == os.environ['VERSION']
              and run['status'] == 'completed' and run['conclusion'] != 'success']
    if failed:
        raise SystemExit('Upstream image build failed: ' + ', '.join(run['html_url'] for run in failed)
                         + '\nMissing: ' + ', '.join(missing))
    if time.monotonic() >= deadline:
        raise SystemExit('Timed out waiting for native images: ' + ', '.join(missing))
    print('Waiting for native images: ' + ', '.join(missing), flush=True)
    time.sleep(30)
PY
