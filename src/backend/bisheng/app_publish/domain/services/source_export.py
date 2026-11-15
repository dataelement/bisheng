"""Editable source exports: original safe source, never masked review text."""

import asyncio
import hashlib
import io
import re
import tarfile
import tempfile
from pathlib import Path

from bisheng.app_publish.domain.services import package_service
from bisheng.app_publish.domain.services.secret_scanner import scan_package
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.common.errcode.app_publish import AppSecretScanBlockedError, AppVersionSnapshotUnavailableError

_BLOCKED = re.compile(
    r"^(?:\.git|node_modules|\.venv|venv|\.npmrc|\.pypirc|\.netrc|\.DS_Store|\.ssh|\.aws|\.azure|\.cache|\.env(?:\..*)?|\.bisheng|\.dsh|__pycache__|data|logs?|sessions?)$|\.(?:pem|key|p12|pfx|(?:db|sqlite3?)(?:-(?:wal|shm|journal))?)$",
    re.I,
)


def export_archive(data):
    package_service.check_upload_size(len(data))
    with tempfile.TemporaryDirectory(prefix="bisheng-source-") as temporary:
        source = Path(temporary) / "package.tgz"
        source.write_bytes(data)
        root = package_service.safe_extract(source, Path(temporary) / "source").root
        files = [
            p
            for p in sorted(root.rglob("*"))
            if p.is_file() and not any(_BLOCKED.search(part) for part in p.relative_to(root).parts)
        ]
        # Scan the export selection, not a redacted copy that cannot be built.
        clean = Path(temporary) / "clean"
        clean.mkdir()
        for path in files:
            target = clean / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        if scan_package(clean).blocked:
            raise AppSecretScanBlockedError()
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for path in sorted(clean.rglob("*")):
                if path.is_file():
                    name = path.relative_to(clean).as_posix()
                    info = tarfile.TarInfo(name)
                    content = path.read_bytes()
                    info.size, info.mode, info.mtime = len(content), 0o644, 0
                    archive.addfile(info, io.BytesIO(content))
        return output.getvalue()


async def source_export(app_id, version_id):
    data = await VersionService.get_snapshot(app_id, version_id)
    if not data:
        raise AppVersionSnapshotUnavailableError()
    archive = await asyncio.to_thread(export_archive, data)
    return archive, hashlib.sha256(archive).hexdigest()
