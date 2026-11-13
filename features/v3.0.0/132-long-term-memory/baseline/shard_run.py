"""Run backend pytest in N shards by top-level test entry; merge junit into one file.
usage: python shard_run.py <backend_dir> <out.xml> [N]"""
import os, subprocess, sys, xml.etree.ElementTree as ET
backend, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
entries = sorted(e for e in os.listdir(os.path.join(backend, "test"))
                 if (e.startswith("test_") and e.endswith(".py")) or
                 (os.path.isdir(os.path.join(backend, "test", e)) and not e.startswith(("_", ".")) and e not in ("fixtures", "e2e")))
shards = [entries[i::n] for i in range(n)]
env = {k: v for k, v in os.environ.items() if k.lower() not in ("all_proxy", "http_proxy", "https_proxy")}
procs = []
for i, shard in enumerate(shards):
    xml = f"{out}.shard{i}.xml"
    cmd = ["uv", "run", "--no-sync", "python", "-m", "pytest", *[f"test/{e}" for e in shard], "-m", "not e2e", "-q",
           "-p", "no:cacheprovider", "--continue-on-collection-errors", f"--junitxml={xml}"]
    log = open(f"{out}.shard{i}.log", "w")
    procs.append((subprocess.Popen(cmd, cwd=backend, env=env, stdout=log, stderr=subprocess.STDOUT), xml))
root = ET.Element("testsuites")
for p, xml in procs:
    p.wait()
    if os.path.exists(xml):
        root.extend(ET.parse(xml).getroot().iter("testsuite"))
ET.ElementTree(root).write(out, encoding="utf-8")
total = sum(1 for _ in root.iter("testcase"))
fail = sum(1 for c in root.iter("testcase") if any(ch.tag in ("failure", "error") for ch in c))
print(f"merged {total} cases, {fail} failed/errored -> {out}")
