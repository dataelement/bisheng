"""Image build — Dockerfile template matrix (D3).

The developer ships source; the platform owns the recipe. ``runtime`` selects a
directory under ``templates/`` and every ``*.j2`` in it is rendered into the
build context, so adding ``node20`` / ``static`` (T092) is adding a directory —
no constant anywhere else has to learn about it. That is why
:func:`discover_runtimes` reads the filesystem instead of returning a literal:
an air-gapped install that only carries the python base image advertises exactly
what it can actually build (AC-15).

Pipeline stages, and why the stage matters as much as the message (AC-15): a
capacity refusal, a dead pre-signed URL and an unresolvable dependency need
three different fixes, and the person reading F055's pre-flight output is not
the person who wrote this code.

``build_admission`` → ``fetch_source`` → ``render_dockerfile`` → ``docker_build``

``STAGE_PROBE`` completes that vocabulary but is *not* executed here: probing
needs a started instance, which is ``POST /v1/intents/probe`` (T027). F055's
pre-flight composes build-then-probe on the backend side; keeping the two
intents orthogonal is what lets the preview instance reuse the probe without
dragging a build along.
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from runtime_manager.admission import PURPOSE_BUILD, AdmissionService
from runtime_manager.api.schemas import BuildRequest
from runtime_manager.config import Config
from runtime_manager.docker_backend import DockerBackend, get_docker_backend
from runtime_manager.errors import NotFoundError, UnsupportedRuntimeError

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

STAGE_BUILD_ADMISSION = "build_admission"
STAGE_FETCH_SOURCE = "fetch_source"
STAGE_RENDER_DOCKERFILE = "render_dockerfile"
STAGE_DOCKER_BUILD = "docker_build"
STAGE_PROBE = "probe"

STATUS_BUILDING = "building"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

#: Base image per runtime. Pinned by digest-less tag on purpose: private
#: registries mirror by tag, and an air-gapped install pre-pulls exactly these.
BASE_IMAGES = {"python3.11": "python:3.11-slim"}

DEFAULT_APP_USER = "bisheng"
DEFAULT_APP_UID = 10001
DEFAULT_APP_GID = 10001

#: Log lines kept for a failed build. Enough to see the real error, small enough
#: to travel in an HTTP response and land in a UI panel.
TAIL_LINES = 80

MIB = 1024 * 1024


def discover_runtimes(templates_dir: Path | None = None) -> list[str]:
    """Runtimes this deployment can actually build, from the shipped templates."""
    root = templates_dir or TEMPLATES_DIR
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "Dockerfile.j2").is_file())


def require_runtime(runtime: str, templates_dir: Path | None = None) -> None:
    supported = discover_runtimes(templates_dir)
    if runtime not in supported:
        raise UnsupportedRuntimeError(
            f"runtime {runtime!r} is not supported by this deployment",
            supported_runtimes=supported,
        )


def render_build_context(
    runtime: str, context: dict[str, Any], templates_dir: Path | None = None
) -> dict[str, str]:
    """Render every ``*.j2`` of a runtime template into ``{filename: content}``.

    ``StrictUndefined`` on purpose: a typo in a context key must fail loudly at
    render time rather than silently produce a Dockerfile with an empty ``USER``
    line — a security-baseline hole that no test would notice.
    """
    root = (templates_dir or TEMPLATES_DIR) / runtime
    require_runtime(runtime, templates_dir)
    env = Environment(
        loader=FileSystemLoader(str(root)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    merged = {
        "base_image": BASE_IMAGES.get(runtime, "python:3.11-slim"),
        "app_user": DEFAULT_APP_USER,
        "app_uid": DEFAULT_APP_UID,
        "app_gid": DEFAULT_APP_GID,
        "health_path": "/",
        **context,
    }
    rendered: dict[str, str] = {}
    for template_path in sorted(root.glob("*.j2")):
        name = template_path.name[: -len(".j2")]
        rendered[name] = env.get_template(template_path.name).render(**merged)
    return rendered


def image_tag(config: Config, slug: str, version_no: int, version_id: str) -> str:
    """``{prefix}/{slug}:{version_no}-{version_id[:8]}`` — never ``latest``.

    A tag names one immutable code snapshot because ``app_version`` is
    append-only (AC-02), and because AC-21 retires the previous container only
    after the new one is healthy — which requires the previous *image* to still
    be there and still be distinguishable.
    """
    return f"{config.image_prefix}/{slug}:{version_no}-{version_id[:8]}"


def _parse_version_no(tag: str) -> int:
    try:
        return int(tag.rsplit(":", 1)[1].split("-", 1)[0])
    except (IndexError, ValueError):
        return -1


def fetch_source(url: str, dest: Path) -> None:
    """Download the pre-signed code snapshot and unpack it into ``dest``.

    The manager holds no platform credentials (D3): the backend mints a
    short-lived pre-signed URL and the manager is a dumb HTTP client. Extraction
    is path-checked — a snapshot is developer-controlled input, and a ``../``
    entry in a tar would otherwise write outside the build context.
    """
    import httpx

    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".archive") as handle:
        archive = Path(handle.name)
        with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                handle.write(chunk)
    try:
        _extract_archive(archive, dest)
    finally:
        archive.unlink(missing_ok=True)


def _extract_archive(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                _guard_member(dest, member)
            zf.extractall(dest)
        return
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            _guard_member(dest, member.name)
            if member.issym() or member.islnk():
                _guard_member(dest, member.linkname)
        tf.extractall(dest)


def _guard_member(dest: Path, name: str) -> None:
    target = (dest / name).resolve()
    if not str(target).startswith(str(dest)):
        raise ValueError(f"refusing to extract outside the build context: {name}")


@dataclass
class BuildRecord:
    build_id: str
    app_id: str
    version_id: str
    status: str = STATUS_BUILDING
    stage: str = STAGE_BUILD_ADMISSION
    message: str = ""
    tail: list[str] = field(default_factory=list)
    image_ref: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "tail": list(self.tail),
            "image_ref": self.image_ref,
        }


class BuildRegistry:
    """In-process build index.

    Deliberately not persisted: a build that was in flight when the manager
    restarted did not survive either (its ``docker build`` child died with the
    process), so resurrecting the *record* would only produce a build that stays
    "building" forever. The backend re-submits instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, BuildRecord] = {}

    def put(self, record: BuildRecord) -> BuildRecord:
        with self._lock:
            self._records[record.build_id] = record
            return record

    def get(self, build_id: str) -> BuildRecord | None:
        with self._lock:
            return self._records.get(build_id)


_registries: dict[str, BuildRegistry] = {}
_registries_lock = threading.Lock()


def get_registry(config: Config) -> BuildRegistry:
    key = str(config.build_root)
    with _registries_lock:
        registry = _registries.get(key)
        if registry is None:
            registry = BuildRegistry()
            _registries[key] = registry
        return registry


class BuildService:
    def __init__(
        self,
        config: Config,
        docker: DockerBackend | None = None,
        admission: AdmissionService | None = None,
        fetcher: Callable[[str, Path], None] | None = None,
        registry: BuildRegistry | None = None,
    ) -> None:
        self._config = config
        self._docker = docker or get_docker_backend()
        self._admission = admission or AdmissionService(config)
        self._fetcher = fetcher
        self._registry = registry or get_registry(config)

    # -- public ------------------------------------------------------------
    def submit(self, request: BuildRequest) -> BuildRecord:
        """Validate, register, and build in the background.

        Validation of ``runtime`` happens *here*, synchronously, so AC-15's
        "reject and list the supported values" is an immediate 400 rather than a
        build that has to be polled before revealing it was never going to work.
        """
        require_runtime(request.runtime)
        record = self._registry.put(
            BuildRecord(
                build_id=uuid.uuid4().hex,
                app_id=request.app_id,
                version_id=request.version_id,
            )
        )
        thread = threading.Thread(
            target=self._execute, args=(request, record), name=f"build-{record.build_id[:8]}", daemon=True
        )
        thread.start()
        return record

    def run(self, request: BuildRequest) -> BuildRecord:
        """Synchronous build — used by tests and by the background thread."""
        require_runtime(request.runtime)
        record = self._registry.put(
            BuildRecord(
                build_id=uuid.uuid4().hex,
                app_id=request.app_id,
                version_id=request.version_id,
            )
        )
        self._execute(request, record)
        return record

    def get(self, build_id: str) -> BuildRecord:
        record = self._registry.get(build_id)
        if record is None:
            raise NotFoundError(f"unknown build {build_id}")
        return record

    # -- pipeline ----------------------------------------------------------
    def _execute(self, request: BuildRequest, record: BuildRecord) -> None:
        context_dir = self._config.build_root / record.build_id
        try:
            self._stage_admission(record)
            if record.status == STATUS_FAILED:
                return
            self._stage_fetch(request, record, context_dir)
            if record.status == STATUS_FAILED:
                return
            self._stage_render(request, record, context_dir)
            if record.status == STATUS_FAILED:
                return
            self._stage_build(request, record, context_dir)
        except Exception as exc:
            logger.exception("build %s crashed", record.build_id)
            self._fail(record, record.stage, str(exc))
        finally:
            record.finished_at = time.time()
            shutil.rmtree(context_dir, ignore_errors=True)

    def _fail(self, record: BuildRecord, stage: str, message: str) -> BuildRecord:
        record.status = STATUS_FAILED
        record.stage = stage
        record.message = message
        logger.warning("build %s failed at %s: %s", record.build_id, stage, message)
        return record

    def _stage_admission(self, record: BuildRecord) -> None:
        record.stage = STAGE_BUILD_ADMISSION
        verdict = self._admission.evaluate(None, purpose=PURPOSE_BUILD)
        if not verdict.admitted:
            self._fail(record, STAGE_BUILD_ADMISSION, verdict.message or verdict.reason)

    def _stage_fetch(self, request: BuildRequest, record: BuildRecord, context_dir: Path) -> None:
        record.stage = STAGE_FETCH_SOURCE
        fetcher = self._fetcher or fetch_source
        try:
            fetcher(request.code_url, context_dir)
        except Exception as exc:
            self._fail(record, STAGE_FETCH_SOURCE, f"cannot fetch {request.code_object_key}: {exc}")

    def _stage_render(self, request: BuildRequest, record: BuildRecord, context_dir: Path) -> None:
        record.stage = STAGE_RENDER_DOCKERFILE
        try:
            files = render_build_context(request.runtime, {"port": request.port})
            for name, content in files.items():
                (context_dir / name).write_text(content, encoding="utf-8")
            requirements = context_dir / "requirements.txt"
            if not requirements.exists():
                # Materialise it so the Dockerfile needs no optional-COPY trick,
                # which BuildKit and the classic builder disagree about.
                requirements.write_text("", encoding="utf-8")
        except Exception as exc:
            self._fail(record, STAGE_RENDER_DOCKERFILE, str(exc))

    def _stage_build(self, request: BuildRequest, record: BuildRecord, context_dir: Path) -> None:
        record.stage = STAGE_DOCKER_BUILD
        tag = image_tag(self._config, request.slug or request.app_id, request.version_no, request.version_id)
        buildargs = {
            "PIP_INDEX_URL": self._config.build_index_url,
            "PIP_TRUSTED_HOST": self._config.build_trusted_host,
            **request.build_args,
        }
        lines: list[str] = []
        error: str | None = None
        try:
            stream = self._docker.build_image(
                context_dir=str(context_dir),
                dockerfile="Dockerfile",
                tag=tag,
                buildargs=buildargs,
                memory_bytes=self._config.build_reserve_mb * MIB,
            )
            for chunk in stream:
                error, text = _chunk_to_text(chunk)
                if text:
                    lines.extend(text.splitlines())
                if error:
                    break
        except Exception as exc:
            error = str(exc)
        record.tail = lines[-TAIL_LINES:]
        if error:
            self._fail(record, STAGE_DOCKER_BUILD, error)
            return
        record.status = STATUS_SUCCEEDED
        record.image_ref = tag
        record.message = ""
        self._prune_images(request.slug or request.app_id)

    def _prune_images(self, slug: str) -> None:
        """Keep the current image and the previous one; drop the rest.

        The previous image is not sentimentality: AC-21 keeps the old container
        serving for the grace window after the new one is healthy, and a
        reconcile in that window would have to recreate it from that image.
        """
        prefix = f"{self._config.image_prefix}/{slug}"
        try:
            tags = [
                tag
                for image in self._docker.list_images(name=prefix)
                for tag in (image.get("RepoTags") or [])
                if tag.startswith(f"{prefix}:")
            ]
        except Exception as exc:
            logger.warning("image pruning skipped for %s: %s", slug, exc)
            return
        for tag in sorted(tags, key=_parse_version_no, reverse=True)[self._config.image_retention :]:
            try:
                self._docker.remove_image(tag, force=False)
            except Exception as exc:
                logger.warning("cannot remove stale image %s: %s", tag, exc)


def _chunk_to_text(chunk: Any) -> tuple[str | None, str]:
    """Normalise one ``docker build`` stream chunk to ``(error, text)``."""
    if isinstance(chunk, bytes):
        try:
            chunk = json.loads(chunk.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None, chunk.decode("utf-8", errors="replace")
    if isinstance(chunk, dict):
        if "error" in chunk:
            return str(chunk.get("error") or "build failed"), str(chunk.get("error") or "")
        for key in ("stream", "status"):
            if chunk.get(key):
                return None, str(chunk[key])
        return None, ""
    return None, str(chunk)
