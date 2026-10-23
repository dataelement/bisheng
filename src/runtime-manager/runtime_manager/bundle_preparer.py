"""Build versioned bundles and dependency materials without building OCI images."""

from __future__ import annotations

import json
import shutil
from uuid import uuid4

from runtime_manager.bundle_inputs import (
    archive_directory,
    dependency_input_key,
    environment_key,
    extract_archive,
    startup_command,
)
from runtime_manager.container_runner import ContainerRunner, ExecutionError


class BundlePreparer:
    def __init__(self, config, platform, docker=None, *, runner=None):
        self.config = config
        self.platform = platform
        self.runner = runner or ContainerRunner(config, docker)

    def _source(self, operation, root):
        source = root / "input"
        marker = root / "source.ready"
        if marker.exists() and marker.read_text() == operation["payload"]["source_artifact_id"]:
            if (source / "bisheng-app.yaml").is_file():
                return source
            children = list(source.iterdir())
            if len(children) == 1 and children[0].is_dir():
                return children[0]
        if source.exists():
            shutil.rmtree(source)
        source.mkdir(parents=True, exist_ok=True)
        archive = root / "source.tar.gz"
        self.platform.download(
            operation["operation_id"],
            operation["payload"]["source_artifact_id"],
            archive,
            max_bytes=operation["payload"].get("source_limits", {}).get("compressed", 50 * 1024 * 1024),
        )
        limits = operation["payload"].get("source_limits", {})
        extract_archive(
            archive,
            source,
            max_bytes=limits.get("unpacked", 200 * 1024 * 1024),
            max_entries=limits.get("entries", 20000),
        )
        marker.write_text(operation["payload"]["source_artifact_id"])
        if not (source / "bisheng-app.yaml").is_file():
            children = list(source.iterdir())
            if len(children) == 1 and children[0].is_dir() and (children[0] / "bisheng-app.yaml").is_file():
                return children[0]
        return source

    def prepare(self, operation):
        body = operation["payload"]
        profile = body["profile"]
        language = profile["language"]
        opid = operation["operation_id"]
        root = self.config.data_root / "tasks" / opid
        root.mkdir(parents=True, exist_ok=True)
        self.runner.cleanup(opid)
        original = self._source(operation, root)
        source = root / "source"
        if source.exists():
            shutil.rmtree(source)
        shutil.copytree(original, source)
        declaration = body.get("delivery", {})
        dependencies = declaration.get("dependencies", {})
        offline_ids = dependencies.get("offline_artifacts", [])
        key = dependency_input_key(
            original,
            tenant_id=body["tenant_id"],
            app_id=operation["app_id"],
            profile=profile,
            language=language,
            offline_artifacts=offline_ids,
            install_inputs=[
                *dependencies.get("install_inputs", []),
                *([dependencies["lock"]] if dependencies.get("lock") else []),
            ],
        )
        plan = self.platform.dependencies(opid, key)
        materials = root / "materials"
        materials.mkdir(exist_ok=True)
        image = self.runner.ensure_image(
            profile["preparer_image"], platform=profile["platform"], expected_id=profile["preparer_image_id"]
        )
        common_env = {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "BISHENG_DEPENDENCY_LOCK": dependencies.get("lock") or "",
        }
        if plan.get("artifact_id"):
            package = root / "dependencies.tar.gz"
            self.platform.download(opid, plan["artifact_id"], package)
            extract_archive(
                package, materials, internal_links=True, max_bytes=8 * 1024 * 1024 * 1024, max_entries=200000
            )
            dependency_id = plan["artifact_id"]
        else:
            for ident in offline_ids:
                archive = root / f"offline-{ident}.tar.gz"
                self.platform.download(opid, ident, archive)
                extract_archive(
                    archive,
                    materials / ident,
                    internal_links=True,
                    max_bytes=8 * 1024 * 1024 * 1024,
                    max_entries=200000,
                )
            output = root / "resolved"
            output.mkdir(exist_ok=True)
            mounts = [
                (source, "/workspace/app", False),
                (original, "/original", True),
                (materials, "/materials", True),
                (output, "/output", False),
            ]
            needs_packages = any(
                (source / name).exists() and (source / name).stat().st_size
                for name in ["requirements.txt", "pyproject.toml", "uv.lock"]
            ) or any(
                (source / name).exists()
                and any(
                    json.loads((source / name).read_text()).get(key)
                    for key in ["dependencies", "devDependencies", "optionalDependencies"]
                )
                for name in ["package.json", "frontend/package.json"]
            )
            if not body.get("offline") and needs_packages:
                network = self.config.build_network
                if not network:
                    raise ExecutionError("preparation_network_not_configured")
                online = {**common_env}
                if self.config.build_index_url:
                    online["PIP_INDEX_URL"] = self.config.build_index_url
                if self.config.build_extra_index_url:
                    online["PIP_EXTRA_INDEX_URL"] = self.config.build_extra_index_url
                if self.config.build_npm_registry:
                    online["npm_config_registry"] = self.config.build_npm_registry
                if self.config.egress_enabled:
                    from runtime_manager.egress import egress_env

                    credentials = self.platform.egress(
                        opid,
                        "build",
                        package_sources=[
                            self.config.build_index_url,
                            self.config.build_extra_index_url,
                            self.config.build_npm_registry,
                        ],
                    )
                    online.update(egress_env(self.config, **credentials))
                self.runner.run(
                    operation,
                    "download",
                    image=image,
                    command=["python", "/opt/bisheng/prepare.py", "download", language],
                    mounts=mounts,
                    env=online,
                    network=network,
                    uid=profile["uid"],
                    gid=profile["gid"],
                )
            self.runner.run(
                operation,
                "resolve",
                image=image,
                command=["python", "/opt/bisheng/prepare.py", "lock", language],
                mounts=mounts,
                env=common_env,
                network="none",
                uid=profile["uid"],
                gid=profile["gid"],
            )
            archive = archive_directory(output, root / "dependencies.tar.gz")
            artifact = self.platform.upload(
                opid,
                archive,
                kind="dependencies",
                platform=profile["platform"],
                metadata={"input_key": key, "profile_id": profile["profile_id"]},
            )
            dependency_id = artifact["artifact_id"]
            self.platform.dependencies(opid, key, artifact_id=dependency_id)
            shutil.copytree(output, materials, dirs_exist_ok=True, symlinks=True)
        overlay = materials / "install-overlay"
        if overlay.exists():
            shutil.copytree(overlay, source, dirs_exist_ok=True, symlinks=True)
        deleted = materials / "install-deleted.json"
        if deleted.exists():
            from runtime_manager.bundle_inputs import safe_relative

            for name in json.loads(deleted.read_text()):
                safe_relative(source, name).unlink(missing_ok=True)
        lock = (materials / "runtime.lock").read_bytes()
        envkey = environment_key(profile, lock, tenant_id=body["tenant_id"], app_id=operation["app_id"])
        if language == "python3.11":
            self.materialize_python(operation, materials, profile, envkey)
        output = root / "build-output"
        output.mkdir(exist_ok=True)
        self.runner.run(
            operation,
            "compile",
            image=image,
            command=["python", "/opt/bisheng/prepare.py", "build", language],
            mounts=[
                (source, "/workspace/app", False),
                (original, "/original", True),
                (materials, "/materials", True),
                (output, "/output", False),
            ],
            env=common_env,
            network="none",
            uid=profile["uid"],
            gid=profile["gid"],
        )
        self.platform.dependencies(opid, key, artifact_id=dependency_id, verified=True)
        code = source / "dist" if language == "static" and (source / "dist" / "index.html").is_file() else source
        archive = archive_directory(
            code,
            root / "compiled.tar.gz",
            exclude={".git", ".venv", "__pycache__"} | ({"node_modules"} if language != "node20" else set()),
        )
        artifact = self.platform.upload(
            opid,
            archive,
            kind="compiled",
            platform=profile["platform"],
            metadata={"source_artifact_id": body["source_artifact_id"], "dependency_artifact_id": dependency_id},
        )
        result = {
            "mode": "bundle",
            "profile": profile,
            "platform": profile["platform"],
            "source_artifact_id": body["source_artifact_id"],
            "dependency_artifact_id": dependency_id,
            "compiled_artifact_id": artifact["artifact_id"],
            "startup": {"command": startup_command(source, language, declaration.get("startup", {}).get("command"))},
            "environment_key": envkey,
        }
        self.cache_compiled(operation, artifact["artifact_id"])
        return result

    def materialize_python(self, operation, materials, profile, key):
        parent = self.config.data_root / "envs" / str(operation["payload"]["tenant_id"]) / operation["app_id"]
        parent.mkdir(parents=True, exist_ok=True)
        environment = parent / key
        if (environment / ".complete").is_file():
            return environment
        self.runner.reset_phase(operation["operation_id"], "materialize")
        temporary = parent / (".prepare-" + operation["operation_id"] + "-" + key[:12])
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir()
        image = self.runner.ensure_image(
            profile["runtime_image"], platform=profile["platform"], expected_id=profile["runtime_image_id"]
        )
        script = 'python -m venv --system-site-packages /opt/venv && /opt/venv/bin/python -m pip install --no-index --find-links=/materials/wheels --require-hashes -r /materials/runtime.lock && /opt/venv/bin/python -m pip check && /opt/venv/bin/python -c "import bisheng_sdk"'
        self.runner.run(
            operation,
            "materialize",
            image=image,
            command=["sh", "-ec", script],
            mounts=[(temporary, "/opt/venv", False), (materials, "/materials", True)],
            env={"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
            network="none",
            uid=profile["uid"],
            gid=profile["gid"],
        )
        (temporary / ".complete").write_text(json.dumps({"key": key, "runtime_image_id": profile["runtime_image_id"]}))
        if environment.exists():
            if not (environment / ".complete").is_file():
                shutil.rmtree(environment)
            else:
                shutil.rmtree(temporary)
                return environment
        temporary.rename(environment)
        return environment

    def cache_compiled(self, operation, artifact_id):
        root = (
            self.config.data_root
            / "artifacts"
            / str(operation["payload"]["tenant_id"])
            / operation["app_id"]
            / artifact_id
        )
        if (root / ".complete").is_file():
            return root / "app"
        temporary = root.parent / (".extract-" + uuid4().hex)
        temporary.mkdir(parents=True)
        archive = temporary / "compiled.tar.gz"
        self.platform.download(operation["operation_id"], artifact_id, archive)
        extract_archive(
            archive, temporary / "app", internal_links=True, max_bytes=8 * 1024 * 1024 * 1024, max_entries=200000
        )
        archive.unlink()
        (temporary / ".complete").write_text(artifact_id)
        if root.exists():
            shutil.rmtree(root)
        temporary.rename(root)
        return root / "app"

    def restore(self, operation, delivery):
        code = self.cache_compiled(operation, delivery["compiled_artifact_id"])
        profile = delivery["profile"]
        environment = None
        if profile["language"] == "python3.11":
            key = delivery["environment_key"]
            environment = (
                self.config.data_root / "envs" / str(operation["payload"]["tenant_id"]) / operation["app_id"] / key
            )
            if not (environment / ".complete").is_file():
                temporary = self.config.data_root / "tasks" / operation["operation_id"] / "restore"
                temporary.mkdir(parents=True, exist_ok=True)
                archive = temporary / "dependencies.tar.gz"
                self.platform.download(operation["operation_id"], delivery["dependency_artifact_id"], archive)
                materials = temporary / "materials"
                extract_archive(
                    archive, materials, internal_links=True, max_bytes=8 * 1024 * 1024 * 1024, max_entries=200000
                )
                environment = self.materialize_python(operation, materials, profile, key)
        elif profile["language"] == "node20":
            environment = code / "node_modules" if (code / "node_modules").exists() else None
        return {"code_dir": code, "environment_dir": environment}
