"""Browser object paths stay independent of the configured bucket names.

The site entrance matches the fixed prefix ``/object/``. These helpers build
that prefix, rewrite stored text on the way out, and accept both the stored
form and the browser form. They do not read configuration or storage.
"""

from bisheng.core.storage.browser_object_path import (
    browser_object_path,
    parse_browser_object_reference,
    rewrite_browser_object_text,
)

PUBLIC = "bisheng"
TMP = "tmp-dir"


def test_browser_path_places_bucket_after_the_fixed_prefix():
    assert browser_object_path(PUBLIC, "original/4.pdf") == "/object/bisheng/original/4.pdf"


def test_browser_path_drops_a_leading_slash_on_the_key_and_keeps_the_query():
    assert (
        browser_object_path(TMP, "/download/pack.zip", "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc")
        == "/object/tmp-dir/download/pack.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
    )


def test_rewrite_prefixes_only_the_current_public_and_temp_buckets():
    text = "see /bisheng/knowledge/images/1/a.png and /tmp-dir/note.txt?X-Amz-Signature=abc"
    assert rewrite_browser_object_text(text, PUBLIC, TMP) == (
        "see /object/bisheng/knowledge/images/1/a.png and /object/tmp-dir/note.txt?X-Amz-Signature=abc"
    )


def test_rewrite_leaves_assets_absolute_urls_and_other_buckets():
    text = (
        "/assets/bisheng/logo.png "
        "http://minio:9000/bisheng/original/4.pdf "
        "https://share.example:9000/tmp-dir/a.bin "
        "/bisheng-apps/apps/1/attachments/a.pdf "
        "/object/bisheng/already.png"
    )
    assert rewrite_browser_object_text(text, PUBLIC, TMP) == text


def test_rewrite_leaves_a_path_whose_bucket_is_no_longer_current():
    assert rewrite_browser_object_text("/old-bucket/original/4.pdf", "corp-files", TMP) == (
        "/old-bucket/original/4.pdf"
    )


def test_rewrite_adds_a_slash_to_a_parenthesized_bucket_path():
    assert rewrite_browser_object_text("(bisheng/knowledge/images/1/a.png)", PUBLIC, TMP) == (
        "(/object/bisheng/knowledge/images/1/a.png)"
    )
    assert rewrite_browser_object_text("(/bisheng/knowledge/images/1/a.png)", PUBLIC, TMP) == (
        "(/object/bisheng/knowledge/images/1/a.png)"
    )


def test_parse_accepts_the_stored_form_and_the_browser_form():
    assert parse_browser_object_reference("/bisheng/original/4.pdf", PUBLIC, TMP) == (PUBLIC, "original/4.pdf")
    assert parse_browser_object_reference("/object/tmp-dir/download/pack.zip?X-Amz-Signature=abc", PUBLIC, TMP) == (
        TMP,
        "download/pack.zip",
    )


def test_parse_accepts_the_client_workspace_prefix():
    assert parse_browser_object_reference("/workspace/object/bisheng/chat/7/a.pdf", PUBLIC, TMP) == (
        PUBLIC,
        "chat/7/a.pdf",
    )
    assert parse_browser_object_reference("/workspace/bisheng/chat/7/a.pdf?sig=1", PUBLIC, TMP) == (
        PUBLIC,
        "chat/7/a.pdf",
    )


def test_parse_rejects_other_buckets_assets_and_empty_keys():
    assert parse_browser_object_reference("/bisheng-apps/apps/1/a.pdf", PUBLIC, TMP) is None
    assert parse_browser_object_reference("/assets/bisheng/logo.png", PUBLIC, TMP) is None
    assert parse_browser_object_reference("/object/bisheng", PUBLIC, TMP) is None
    assert parse_browser_object_reference("", PUBLIC, TMP) is None
