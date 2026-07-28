"""F043: prefix deletion used to drop a conversation's attachments.

See features/v2.6.0/043-chat-file-permanent-storage/design.md §3 decision 1.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from bisheng.core.storage.minio.minio_storage import MinioStorage


def _storage(objects, remove_side_effect=None):
    """A MinioStorage with just enough wired up to exercise the sweep."""
    storage = MinioStorage.__new__(MinioStorage)
    storage.bucket = "bisheng"
    client = MagicMock()
    client.list_objects.return_value = [SimpleNamespace(object_name=name) for name in objects]
    if remove_side_effect:
        client.remove_object.side_effect = remove_side_effect
    storage.minio_client_sync = client
    return storage, client


class TestRemoveObjectsByPrefix:
    def test_removes_every_object_under_the_prefix(self):
        storage, client = _storage(["chat/c1/a.png", "chat/c1/b.pdf"])

        deleted, failed = storage.remove_objects_by_prefix_sync("chat/c1/")

        assert (deleted, failed) == (2, 0)
        assert client.list_objects.call_args.kwargs["recursive"] is True
        assert [c.args[1] for c in client.remove_object.call_args_list] == ["chat/c1/a.png", "chat/c1/b.pdf"]

    def test_one_failure_does_not_abort_the_sweep(self):
        # A single unreachable object must not strand the rest of the files.
        def boom(bucket, name):
            if name.endswith("b.pdf"):
                raise S3Error("err", "msg", "res", "req", "host", "resp")

        storage, client = _storage(["chat/c1/a.png", "chat/c1/b.pdf", "chat/c1/c.png"], remove_side_effect=boom)

        deleted, failed = storage.remove_objects_by_prefix_sync("chat/c1/")

        assert (deleted, failed) == (2, 1)
        assert client.remove_object.call_count == 3

    @pytest.mark.parametrize("prefix", ["", "/", "//", "   "])
    def test_refuses_a_prefix_that_would_match_the_whole_bucket(self, prefix):
        # There is no legitimate caller for this and the blast radius is the
        # entire object store.
        storage, client = _storage(["chat/c1/a.png"])

        with pytest.raises(ValueError):
            storage.remove_objects_by_prefix_sync(prefix)

        client.remove_object.assert_not_called()
