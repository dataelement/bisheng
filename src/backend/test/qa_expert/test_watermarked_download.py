from bisheng.qa_expert.domain.watermarked_download import parse_qa_asset_location


def test_parse_permanent_qa_object_and_tmp_uuid():
    assert parse_qa_asset_location(
        "https://minio:9000/bisheng/qa-expert/1/question/attachment/a/a.pdf?X-Amz-Signature=1",
        default_bucket="bisheng",
        tmp_bucket="tmp-dir",
    ) == ("bisheng", "qa-expert/1/question/attachment/a/a.pdf")
    assert parse_qa_asset_location(
        "/tmp-dir/abcd1234-ef.png?X-Amz-Expires=1",
        default_bucket="bisheng",
        tmp_bucket="tmp-dir",
    )[0] == "tmp-dir"


def test_parse_rejects_unrelated_paths():
    try:
        parse_qa_asset_location("https://evil.example/etc/passwd", default_bucket="bisheng", tmp_bucket="tmp-dir")
        raise AssertionError("expected error")
    except ValueError:
        pass
