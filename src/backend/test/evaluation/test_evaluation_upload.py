from io import BytesIO

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from bisheng.evaluation.domain.services import evaluation_service


@pytest.mark.parametrize("content_type", ["text/html", "image/svg+xml", "text/csv", None])
def test_upload_stores_csv_type_without_changing_file(monkeypatch, content_type):
    """Client MIME metadata must not turn a valid evaluation CSV into active content."""
    csv_bytes = b"question,ground_truth\n<script>alert(1)</script>,answer\n"
    stored_objects = {}

    class MemoryStorage:
        bucket = "evaluation-test"

        def put_object_sync(self, *, bucket_name, object_name, file, content_type):
            stored_objects[(bucket_name, object_name)] = (file.read(), content_type)

        def get_object_sync(self, *, bucket_name, object_name):
            return stored_objects[(bucket_name, object_name)][0]

    monkeypatch.setattr(evaluation_service, "get_minio_storage_sync", MemoryStorage)
    monkeypatch.setattr(evaluation_service, "generate_uuid", lambda: "upload-test")
    headers = Headers({"content-type": content_type}) if content_type else Headers()
    upload = UploadFile(file=BytesIO(csv_bytes), filename="dataset.csv", headers=headers)

    try:
        original_rows = evaluation_service.EvaluationService.parse_csv(BytesIO(csv_bytes))
        filename, object_name = evaluation_service.EvaluationService.upload_file(upload)

        assert filename == "dataset.csv"
        assert object_name == "evaluation/dataset/upload-test.csv"
        assert stored_objects[(MemoryStorage.bucket, object_name)] == (csv_bytes, "text/csv")
        downloaded = evaluation_service.EvaluationService.read_csv_file(object_name)
        assert downloaded.getvalue() == csv_bytes
        assert evaluation_service.EvaluationService.parse_csv(downloaded) == original_rows
    finally:
        upload.file.close()
