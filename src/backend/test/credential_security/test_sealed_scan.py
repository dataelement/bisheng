"""Acceptance evidence detects cleartext and cannot silently omit scan gaps."""

import base64
import io
import json

import pytest

from test.credential_security.probes.sealed_scan import scan_paths, scan_stream, variants


def test_encoded_and_cross_chunk_passwords_are_detected():
    value = 'Test-only@:$#%\'"\\secret'
    patterns = variants([value])
    for pattern in patterns:
        assert scan_stream(io.BytesIO(b"prefix" + pattern + b"suffix"), patterns, chunk_size=3)
    assert base64.b64encode(value.encode()) in patterns
    assert not scan_stream(io.BytesIO(b"ciphertext fixture without candidate"), patterns, chunk_size=2)


def test_report_redacts_password_in_filename_and_never_contains_contents(tmp_path):
    value = "test-only-secret-123456"
    p = tmp_path / value
    p.write_text("prefix:" + value)
    report = scan_paths([tmp_path], [value])
    assert report["status"] == "failed"
    assert report["files_scanned"] >= 1  # Repository fixture also writes an ownership marker.
    assert "<redacted>" in report["matches"][0]
    assert value not in json.dumps(report)


def test_missing_scope_and_symlink_are_not_counted_as_a_pass(tmp_path):
    missing = scan_paths([tmp_path / "missing"], ["test-secret-value"])
    assert missing["status"] == "failed" and missing["unreadable"]
    target = tmp_path / "file"
    target.write_text("ciphertext")
    (tmp_path / "link").symlink_to(target)
    report = scan_paths([tmp_path], ["test-secret-value"])
    assert report["status"] == "failed" and report["symlinks"]


def test_empty_candidates_cannot_produce_a_misleading_success(tmp_path):
    with pytest.raises(ValueError):
        scan_paths([tmp_path], [""])


def test_milvus_exception_does_not_exclude_other_passwords_or_config_files(tmp_path):
    value, other = "milvus-test-secret-long", "other-component-secret-long"
    root = tmp_path / "native"
    (root / "rdb_data").mkdir(parents=True)
    record = root / "rdb_data/00001.sst"
    record.write_bytes(base64.b64encode(value.encode()))
    kwargs = {"milvus_base64_values": [value], "milvus_data_root": root}
    result = scan_paths([root], [value, other], **kwargs)
    assert result["status"] == "passed_with_accepted_exceptions"
    assert len(result["accepted_exceptions"]) == 1
    record.write_bytes(record.read_bytes() + other.encode())
    assert scan_paths([root], [value, other], **kwargs)["status"] == "failed"
    record.write_bytes(base64.b64encode(value.encode()))
    config = root / "user.yaml"
    config.write_bytes(record.read_bytes())
    assert scan_paths([root], [value, other], **kwargs)["matches"] == [str(config)]


def test_only_exact_native_mysql_socket_link_can_be_accepted(tmp_path):
    link = tmp_path / "mysql.sock"
    link.symlink_to("/var/run/mysqld/mysqld.sock")
    result = scan_paths([tmp_path], ["test-password-value"], mysql_socket_link=link)
    assert result["status"] == "passed_with_accepted_exceptions"
    link.unlink()
    link.symlink_to(tmp_path / "customer-file")
    assert scan_paths([tmp_path], ["test-password-value"], mysql_socket_link=link)["status"] == "failed"
