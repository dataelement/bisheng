"""Disposable private pages for the full read-only migration preflight.

Use the normal canonical codecs and graph verification without publishing
objects or holding the entire inventory in memory. These local scratch pages
are deleted on exit and can never resume a migration. Existing operational
backup/schema objects remain read through the original artifact adapter.
"""

import hashlib
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore


class _PreviewStorage:
    def __init__(self, original, directory):
        self.original = original
        self.bucket = original.bucket
        self.tmp_bucket = None
        self.directory = Path(directory)

    def _path(self, object_name):
        # Object keys remain validated by UnificationArtifactStore; hashing
        # also keeps temporary filenames independent of caller-provided paths.
        return self.directory / hashlib.sha256(object_name.encode()).hexdigest()

    async def object_exists(self, *, bucket_name, object_name):
        return self._path(object_name).exists()

    async def put_object(self, *, bucket_name, object_name, file, content_type):
        path = self._path(object_name)
        with path.open("xb") as output:
            path.chmod(0o600)
            output.write(file)

    async def get_object(self, *, bucket_name, object_name):
        path = self._path(object_name)
        if path.exists():
            return path.read_bytes()
        return await self.original.storage.get_object(bucket_name=bucket_name, object_name=object_name)


@contextmanager
def preview_artifact_store(original):
    with TemporaryDirectory(prefix="f118-preflight-") as directory:
        yield UnificationArtifactStore(_PreviewStorage(original, directory))
