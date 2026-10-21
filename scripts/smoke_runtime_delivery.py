#!/usr/bin/env python3
"""Native container integration, invoked inside the manager image on a disposable CI host.

Uses the real Engine and preparation/launch/data code with an in-memory artifact port.
It is not a deployed backend/approval E2E test. All containers carry a unique suite node.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path
from uuid import uuid4

from runtime_manager.appdb import PlatformAppDb
from runtime_manager.bundle_inputs import archive_directory
from runtime_manager.bundle_launch import BundleLauncher
from runtime_manager.bundle_preparer import BundlePreparer
from runtime_manager.config import Config
from runtime_manager.container_runner import ContainerRunner
from runtime_manager.data_executor import DataExecutor
from runtime_manager.docker_backend import _RealDockerBackend


class Artifacts:
    def __init__(self):
        self.files = {}
        self.plans = {}
        self.cache_hits = 0

    def upload(self, operation, path, *, kind, **kwargs):
        data = Path(path).read_bytes()
        ident = hashlib.sha256(data).hexdigest()
        result = {
            "artifact_id": ident,
            "kind": kind,
            "state": "verified",
            "confirmed_at": "ci-confirmed",
        }
        self.files[ident] = (data, result)
        return result

    def download(self, operation, ident, path, **kwargs):
        data, result = self.files[ident]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return result

    def dependencies(self, operation, key, *, artifact_id=None, verified=False):
        if artifact_id:
            self.plans[key] = artifact_id
        elif self.plans.get(key):
            self.cache_hits += 1
        return {"artifact_id": self.plans.get(key)}


def read(url):
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        url, timeout=5
    ) as response:
        return response.read()


def run_suite(inventory, root):
    engine = _RealDockerBackend(base_url=os.environ.get("RTM_DOCKER_HOST"))
    suite = "e2e-f086-" + uuid4().hex[:12]
    network = engine._client().create_network(
        suite, internal=True, labels={"bisheng.test": suite}
    )["Id"]
    cfg = Config(
        data_root=root,
        host_data_root=root,
        node_id=suite,
        network=suite,
        image_pull_policy="never",
        reserve_mb=256,
        build_reserve_mb=1024,
        data_helper_image=inventory["images"]["runtime-manager"]["image_id"],
        probe_timeout_seconds=30,
    )
    platform = Artifacts()
    runner = ContainerRunner(cfg, engine)
    preparer = BundlePreparer(cfg, platform, runner=runner)
    launcher = BundleLauncher(cfg, runner=runner)
    results = []
    profiles = {}
    before = {image["Id"] for image in engine.list_images()}
    try:
        for language, runtime, preparation, filename, content in [
            (
                "python3.11",
                "app-python",
                "app-python-preparer",
                "main.py",
                """import os, sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
with sqlite3.connect('/data/app.db') as c:
    c.execute('CREATE TABLE IF NOT EXISTS data (id INTEGER PRIMARY KEY, value TEXT)')
    c.execute("INSERT OR IGNORE INTO data VALUES (1, 'retained')")
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with sqlite3.connect('/data/app.db') as c:
            value=c.execute('SELECT value FROM data').fetchone()[0]
        self.send_response(200); self.end_headers(); self.wfile.write(('version-1:'+value).encode())
HTTPServer(('0.0.0.0', int(os.environ['PORT'])), Handler).serve_forever()
""",
            ),
            (
                "node20",
                "app-node",
                "app-node-preparer",
                "server.js",
                "require('http').createServer((q,r)=>r.end('version-1')).listen(process.env.PORT,'0.0.0.0');",
            ),
            (
                "static",
                "app-static",
                "app-node-preparer",
                "index.html",
                "<h1>version-1</h1>",
            ),
        ]:
            app = suite + "-" + language.replace(".", "")
            source = root / "sources" / app
            source.mkdir(parents=True)
            (source / "bisheng-app.yaml").write_text("manifest_version: 2\n")
            (source / filename).write_text(content)
            if language == "python3.11":
                (source / "requirements.txt").write_text("")
            if language == "node20":
                (source / "package.json").write_text(
                    '{"name":"e2e-f086","version":"1.0.0","scripts":{"start":"node server.js"}}'
                )
                (source / "package-lock.json").write_text(
                    json.dumps(
                        {
                            "name": "e2e-f086",
                            "version": "1.0.0",
                            "lockfileVersion": 3,
                            "requires": True,
                            "packages": {"": {"name": "e2e-f086", "version": "1.0.0"}},
                        }
                    )
                )
            run_image, prep_image = (
                inventory["images"][runtime],
                inventory["images"][preparation],
            )
            profile = {
                "profile_id": "ci-" + language,
                "profile_digest": "ci-local",
                "platform": inventory["platform"],
                "language": language,
                "abi": language,
                "runtime_image": run_image["image"],
                "runtime_image_id": run_image["image_id"],
                "preparer_image": prep_image["image"],
                "preparer_image_id": prep_image["image_id"],
                "uid": 10001,
                "gid": 10001,
            }
            profiles[language] = profile
            deliveries = []
            hits_before = platform.cache_hits
            for version in [1, 2]:
                (source / filename).write_text(
                    content.replace("version-1", f"version-{version}")
                )
                package = archive_directory(source, root / (app + f"-{version}.tar.gz"))
                artifact = platform.upload("source", package, kind="source")
                operation = {
                    "operation_id": uuid4().hex,
                    "app_id": app,
                    "version_id": str(version),
                    "generation": version,
                    "owner_epoch": 1,
                    "payload": {
                        "tenant_id": 1,
                        "source_artifact_id": artifact["artifact_id"],
                        "profile": profile,
                        "offline": True,
                        "port": 8080,
                        "delivery": {
                            "startup": {"command": ["python", "main.py"]}
                            if language == "python3.11"
                            else {}
                        },
                    },
                }
                delivery = preparer.prepare(operation)
                deliveries.append(delivery)
                operation["payload"]["resolved_delivery"] = delivery
                ready = launcher.start(
                    operation, delivery, **preparer.restore(operation, delivery)
                )
                value = read(f"http://{ready['target']['host']}:8080/").decode()
                assert f"version-{version}" in value, value
                engine.stop_container(ready["exec_ref"], timeout=5)
                engine.remove_container(ready["exec_ref"])
                if language == "python3.11":
                    assert "retained" in value
                    data = DataExecutor(cfg, engine)
                    tables = data.call(app, "tables", {})
                    assert tables["tables"]
                    backup = PlatformAppDb(cfg, platform, operation).backup()
                    assert backup["confirmed_at"]
            assert (
                deliveries[0]["dependency_artifact_id"]
                == deliveries[1]["dependency_artifact_id"]
            )
            assert platform.cache_hits > hits_before, (
                "same bytes alone do not prove a dependency cache hit"
            )
            assert deliveries[0]["environment_key"] == deliveries[1]["environment_key"]
            results.append(
                {
                    "language": language,
                    "offline": True,
                    "code_update": True,
                    "dependency_reuse": True,
                }
            )
        # A frontend install hook and build execute offline. Source-dependent
        # hook results must be regenerated rather than reused across revisions.
        app = suite + "-frontend"
        source = root / "sources" / app
        source.mkdir(parents=True)
        (source / "bisheng-app.yaml").write_text("manifest_version: 2\n")
        (source / "package.json").write_text(
            json.dumps(
                {
                    "name": "e2e-f086-frontend",
                    "version": "1.0.0",
                    "scripts": {
                        "postinstall": "node postinstall.js",
                        "build": "node build.js",
                    },
                }
            )
        )
        (source / "package-lock.json").write_text(
            json.dumps(
                {
                    "name": "e2e-f086-frontend",
                    "version": "1.0.0",
                    "lockfileVersion": 3,
                    "requires": True,
                    "packages": {
                        "": {
                            "name": "e2e-f086-frontend",
                            "version": "1.0.0",
                            "hasInstallScript": True,
                        }
                    },
                }
            )
        )
        (source / "build.js").write_text(
            "const f=require('fs');f.mkdirSync('dist',{recursive:true});"
            "f.writeFileSync('dist/index.html',f.readFileSync('value.txt','utf8')+f.readFileSync('hook.txt','utf8'));"
        )
        artifacts = []
        for version in [1, 2]:
            (source / "postinstall.js").write_text(
                f"require('fs').writeFileSync('hook.txt','hook-{version}');"
            )
            (source / "value.txt").write_text(f"frontend-{version}:")
            package = archive_directory(source, root / f"frontend-{version}.tar.gz")
            artifact = platform.upload("source", package, kind="source")
            operation = {
                "operation_id": uuid4().hex,
                "app_id": app,
                "version_id": str(version),
                "generation": version,
                "owner_epoch": 1,
                "payload": {
                    "tenant_id": 1,
                    "source_artifact_id": artifact["artifact_id"],
                    "profile": profile,
                    "offline": True,
                    "port": 8080,
                    "delivery": {},
                },
            }
            delivery = preparer.prepare(operation)
            artifacts.append(delivery["dependency_artifact_id"])
            operation["payload"]["resolved_delivery"] = delivery
            ready = launcher.start(
                operation, delivery, **preparer.restore(operation, delivery)
            )
            assert (
                read(f"http://{ready['target']['host']}:8080/").decode()
                == f"frontend-{version}:hook-{version}"
            )
            engine.stop_container(ready["exec_ref"], timeout=5)
            engine.remove_container(ready["exec_ref"])
        assert artifacts[0] != artifacts[1], (
            "source-dependent install output must not be reused"
        )
        results.append(
            {
                "language": "static",
                "offline": True,
                "install_hook": True,
                "frontend_build": True,
                "source_change_invalidates_dependency": True,
            }
        )
        # Build a real CPython extension offline, then change its source while
        # keeping the package version unchanged to exercise environment fencing.
        app = suite + "-native"
        source = root / "sources" / app
        source.mkdir(parents=True)
        (source / "bisheng-app.yaml").write_text("manifest_version: 2\n")
        (source / "requirements.txt").write_text(".\n")
        (source / "pyproject.toml").write_text(
            '[build-system]\nrequires=["setuptools==80.9.0","wheel==0.45.1"]\nbuild-backend="setuptools.build_meta"\n'
        )
        (source / "setup.py").write_text(
            "from setuptools import setup,Extension\n"
            "setup(name='e2e-native',version='1.0',ext_modules=[Extension('e2e_native',['native.c'])])\n"
        )
        (source / "main.py").write_text(
            "import e2e_native,os\nfrom http.server import BaseHTTPRequestHandler,HTTPServer\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n"
            "  self.send_response(200);self.end_headers();self.wfile.write(str(e2e_native.answer()).encode())\n"
            "HTTPServer(('0.0.0.0',int(os.environ['PORT'])),Handler).serve_forever()\n"
        )
        native_artifacts = []
        for answer in [42, 43]:
            (source / "native.c").write_text(
                "#include <Python.h>\n"
                f"static PyObject *answer(PyObject *self, PyObject *args){{return PyLong_FromLong({answer});}}\n"
                'static PyMethodDef methods[]={{"answer",answer,METH_NOARGS,NULL},{NULL,NULL,0,NULL}};\n'
                'static struct PyModuleDef module={PyModuleDef_HEAD_INIT,"e2e_native",NULL,-1,methods};\n'
                "PyMODINIT_FUNC PyInit_e2e_native(void){return PyModule_Create(&module);}\n"
            )
            package = archive_directory(source, root / f"native-{answer}.tar.gz")
            artifact = platform.upload("source", package, kind="source")
            operation = {
                "operation_id": uuid4().hex,
                "app_id": app,
                "version_id": str(answer),
                "generation": answer,
                "owner_epoch": 1,
                "payload": {
                    "tenant_id": 1,
                    "source_artifact_id": artifact["artifact_id"],
                    "profile": profiles["python3.11"],
                    "offline": True,
                    "port": 8080,
                    "delivery": {"startup": {"command": ["python", "main.py"]}},
                },
            }
            delivery = preparer.prepare(operation)
            native_artifacts.append(delivery["dependency_artifact_id"])
            operation["payload"]["resolved_delivery"] = delivery
            ready = launcher.start(
                operation, delivery, **preparer.restore(operation, delivery)
            )
            assert read(f"http://{ready['target']['host']}:8080/").decode() == str(
                answer
            )
            engine.stop_container(ready["exec_ref"], timeout=5)
            engine.remove_container(ready["exec_ref"])
        assert native_artifacts[0] != native_artifacts[1], (
            "changed native code must rebuild the dependency artifact"
        )
        results.append(
            {
                "language": "python3.11",
                "offline": True,
                "local_native_wheel": True,
                "source_change_invalidates_dependency": True,
            }
        )
        assert {image["Id"] for image in engine.list_images()} == before, (
            "bundle releases must not build OCI images"
        )
        print(json.dumps({"platform": inventory["platform"], "checks": results}))
    finally:
        for container in engine.list_containers(
            filters={"label": [f"bisheng.runtime.node={suite}"]}
        ):
            engine.remove_container(container["Id"], force=True)
        engine._client().remove_network(network)
        shutil.rmtree(root / "sources", ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    run_suite(
        json.loads(Path(args.inventory).read_text()), Path(args.data_root).resolve()
    )
