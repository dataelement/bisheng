"""Cross-turn workspace continuity (跨轮工作区延续).

A follow-up turn runs under a fresh session_version_id with an empty workspace,
so it can't see the prior turn's deliverables. ``seed_workspace_from_previous``
server-side copies the previous version's ``output/`` + ``uploads/`` into the
new turn's prefix so read_file/ls transparently surface them.
"""

from unittest.mock import MagicMock

from minio.error import S3Error

from bisheng.linsight.domain.services.workspace_backend import seed_workspace_from_previous

SRC = "src-version-1"
DST = "dst-version-2"


class _Obj:
    def __init__(self, name: str):
        self.object_name = name


def _s3(code: str) -> S3Error:
    exc = S3Error.__new__(S3Error)
    object.__setattr__(exc, "code", code)
    return exc


def _minio(listing: dict[str, list[str]]) -> MagicMock:
    """listing: prefix -> list of object keys returned by list_objects."""
    minio = MagicMock()
    minio.bucket = "bisheng"

    def _list(bucket, prefix="", recursive=True):
        return iter([_Obj(k) for k in listing.get(prefix, [])])

    minio.minio_client_sync.list_objects.side_effect = _list
    return minio


async def test_seed_copies_output_and_uploads_skips_scratch():
    minio = _minio(
        {
            f"workspace/{SRC}/output/": [f"workspace/{SRC}/output/report.md"],
            f"workspace/{SRC}/uploads/": [f"workspace/{SRC}/uploads/doc/index.md"],
            # scratch present but must NOT be queried/copied
            f"workspace/{SRC}/scratch/": [f"workspace/{SRC}/scratch/notes.txt"],
        }
    )
    copied: list[tuple[str, str]] = []

    def _copy(source_bucket, source_object, dest_bucket, dest_object):
        if source_object.endswith("manifest.json"):
            raise _s3("NoSuchKey")  # no manifest in this workspace — expected, skipped
        copied.append((source_object, dest_object))

    minio.copy_object_sync.side_effect = _copy

    n = await seed_workspace_from_previous(minio, src_svid=SRC, dst_svid=DST)

    assert n == 2
    assert (f"workspace/{SRC}/output/report.md", f"workspace/{DST}/output/report.md") in copied
    assert (f"workspace/{SRC}/uploads/doc/index.md", f"workspace/{DST}/uploads/doc/index.md") in copied
    # scratch/ was never even listed (continuity carries deliverables + sources only)
    queried_prefixes = [c.kwargs.get("prefix") for c in minio.minio_client_sync.list_objects.call_args_list]
    assert all("scratch" not in (p or "") for p in queried_prefixes)


async def test_seed_noop_when_destination_not_empty():
    # idempotency: a re-run (or a turn that already started writing) must not re-copy
    minio = _minio(
        {
            f"workspace/{DST}/": [f"workspace/{DST}/output/already.md"],
            f"workspace/{SRC}/output/": [f"workspace/{SRC}/output/report.md"],
        }
    )
    n = await seed_workspace_from_previous(minio, src_svid=SRC, dst_svid=DST)
    assert n == 0
    minio.copy_object_sync.assert_not_called()


async def test_seed_noop_for_same_or_missing_svid():
    minio = _minio({})
    assert await seed_workspace_from_previous(minio, src_svid="x", dst_svid="x") == 0
    assert await seed_workspace_from_previous(minio, src_svid="", dst_svid=DST) == 0
    minio.copy_object_sync.assert_not_called()


async def test_seed_best_effort_on_copy_error():
    # a single object failing must not abort the rest of the seeding
    minio = _minio({f"workspace/{SRC}/output/": [f"workspace/{SRC}/output/a.md", f"workspace/{SRC}/output/b.md"]})

    def _copy(source_bucket, source_object, dest_bucket, dest_object):
        if source_object.endswith("manifest.json"):
            raise _s3("NoSuchKey")
        if source_object.endswith("a.md"):
            raise RuntimeError("transient copy failure")
        # b.md succeeds

    minio.copy_object_sync.side_effect = _copy
    n = await seed_workspace_from_previous(minio, src_svid=SRC, dst_svid=DST)
    assert n == 1  # only b.md copied; a.md failure swallowed, manifest absent
