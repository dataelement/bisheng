"""Backend integration points for OFD support (T007).

Covers the routing / advertised-format wiring that makes an uploaded .ofd a
first-class document.

- AC-01: OFD routes through the parse pipeline like other documents.
- AC-06: OFD is advertised as uploadable with no config gate.

Note: the preview-object-path mapping (`get_*_preview_file_object_name`) lives in
``knowledge_utils``, which the test harness stubs in sys.modules
(`test/fixtures/mock_services.py`); it cannot be exercised here and is verified
by the manual end-to-end pass (T014, AC-03/AC-05).
"""

from bisheng.api.v1.endpoints import UNS_SUPPORT_FORMATS
from bisheng.knowledge.rag.base_file_pipeline import FileExtensionMap


def test_ofd_routed_to_ofd_loader():
    assert "ofd" in FileExtensionMap
    assert FileExtensionMap["ofd"]["loader"] == "_init_ofd_loader"


def test_ofd_advertised_without_gate():
    # AC-06: OFD listed alongside pdf/docx, unconditionally (no config switch).
    assert "ofd" in UNS_SUPPORT_FORMATS
