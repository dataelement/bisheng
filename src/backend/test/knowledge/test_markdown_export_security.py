"""Markdown resources never gain local-file or private-network authority."""

from io import BytesIO
from zipfile import ZipFile

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from bisheng.common.utils.markdown_cmpnt.md_to_docx.markdocx import MarkDocx
from bisheng.common.utils.markdown_cmpnt.md_to_docx.provider.docx_processor import DocxProcessor


def _png():
    stream = BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    return stream.getvalue()


def _pictures(data):
    with ZipFile(BytesIO(bytes(data))) as document:
        return [name for name in document.namelist() if name.startswith("word/media/")]


def test_title_fallback_never_reads_local_png_canary(tmp_path):
    canary = tmp_path / "generated-canary.png"
    canary.write_bytes(_png())
    data, _ = MarkDocx()(f'<img src="missing-local" title="{canary.as_uri()}" alt="canary">')
    assert _pictures(data) == []


def test_direct_docx_processor_never_reads_local_png_canary(tmp_path):
    canary = tmp_path / "generated-canary.png"
    canary.write_bytes(_png())
    processor = DocxProcessor(style_conf=None, show_image_desc=False)
    processor.add_picture(BeautifulSoup(f'<img src="{canary}">', "html.parser").img)
    stream = BytesIO()
    processor.document.save(stream)
    assert _pictures(stream.getvalue()) == []


def test_authorized_preinlined_workspace_png_is_preserved():
    import base64

    source = "data:image/png;base64," + base64.b64encode(_png()).decode()
    data, _ = MarkDocx()(f"# Report\n\n![chart]({source})")
    assert len(_pictures(data)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "http://127.0.0.1/image.png",
        "http://169.254.169.254/image.png",
        "file:///generated-canary.png",
        "/generated-canary.png",
        "https://user:password@example.com/image.png",
    ],
)
def test_resource_policy_denies_local_private_and_credentialed_sources(source):
    from bisheng.common.utils.markdown_cmpnt.image_resources import image_bytes

    with pytest.raises(ValueError):
        image_bytes(source)


def test_public_png_fetch_uses_validated_pinned_transport_and_embeds(monkeypatch):
    from contextlib import contextmanager

    import httpx

    from bisheng.core.external import safe_download
    from bisheng_langchain.utils.egress_policy import ResolvedDestination

    seen = []

    class Peer:
        def get_extra_info(self, name):
            return ("93.184.216.34", 443)

    class Client:
        cookies = type("Cookies", (), {"clear": lambda self: None})()

        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @contextmanager
        def stream(self, method, url, **kwargs):
            seen.append((url, kwargs))
            yield httpx.Response(
                200, content=_png(), request=httpx.Request("GET", url), extensions={"network_stream": Peer()}
            )

    monkeypatch.setattr(safe_download.httpx, "Client", Client)
    monkeypatch.setattr(
        safe_download,
        "resolve_destination",
        lambda url: ResolvedDestination(
            url, "https", "images.example.com", 443, "https://images.example.com:443", ("93.184.216.34",)
        ),
    )
    data, _ = MarkDocx()("![chart](https://images.example.com/image.png)")
    assert len(_pictures(data)) == 1
    assert seen[0][0] == "https://93.184.216.34:443/image.png"
    assert seen[0][1]["headers"]["Host"] == "images.example.com"
    assert seen[0][1]["extensions"]["sni_hostname"] == "images.example.com"


def test_pdf_route_never_continues_browser_egress(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from bisheng.common.utils.markdown_cmpnt import image_resources

    route = SimpleNamespace(
        request=SimpleNamespace(resource_type="image", url="http://127.0.0.1/image.png"), abort=Mock(), fulfill=Mock()
    )
    image_resources.route_export_resource(route)
    route.abort.assert_called_once()
    route.fulfill.assert_not_called()
    route = SimpleNamespace(
        request=SimpleNamespace(resource_type="image", url="https://example.com/image.png"),
        abort=Mock(),
        fulfill=Mock(),
    )
    monkeypatch.setattr(image_resources, "image_bytes", lambda source: _png())
    image_resources.route_export_resource(route)
    assert route.fulfill.call_args.kwargs["body"] == _png()
    route.abort.assert_not_called()


def test_inline_data_uri_size_bound_and_strict_base64(monkeypatch):
    from bisheng.common.utils.markdown_cmpnt import image_resources

    monkeypatch.setattr(image_resources, "MAX_IMAGE_BYTES", 4)
    for value in ["data:image/png;base64,invalid!", "data:text/html;base64,AA==", "data:image/png;base64,AAAAAAAAAAAA"]:
        with pytest.raises(ValueError):
            image_resources.image_bytes(value)
