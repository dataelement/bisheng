"""Cooperative checkpoints plus transaction-bound external writes."""

from contextlib import contextmanager
from functools import wraps

from bisheng.knowledge.domain.repositories.processing_fence_repository import (
    ProcessingCancelled,
    ProcessingFenceRepository,
)


class ProcessingWriteGuard:
    def __init__(self, space_id, file_id=0, *, repository=None):
        self.space_id, self.file_id = space_id, file_id
        self.repository = repository or ProcessingFenceRepository()

    def checkpoint(self):
        self.repository.checkpoint(self.space_id, self.file_id)

    @contextmanager
    def write(self):
        with self.repository.writer(self.space_id, self.file_id) as session:
            yield session

    def upload(self, storage, **kwargs):
        with self.write():
            self.repository.record_artifact(self.space_id, self.file_id, kwargs["object_name"])
            return storage.put_object_sync(**kwargs)


def guarded_processing(*, space_arg="space_id", file_arg=None, cancel_result=None):
    """Protect a legacy atomic index operation, retaining its public signature."""
    import inspect

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def guarded(*args, **kwargs):
            values = signature.bind(*args, **kwargs).arguments

            def resolve(path):
                name, *attributes = path.split(".")
                value = values[name]
                for attribute in attributes:
                    value = getattr(value, attribute)
                return value

            space_id = resolve(space_arg)
            file_id = resolve(file_arg) if file_arg else 0
            try:
                with ProcessingWriteGuard(space_id, file_id).write():
                    return function(*args, **kwargs)
            except ProcessingCancelled:
                if cancel_result is None:
                    raise
                from loguru import logger

                logger.info("Knowledge processing cancelled by deletion space={} file={}", space_id, file_id)
                return cancel_result

        return guarded

    return decorate
