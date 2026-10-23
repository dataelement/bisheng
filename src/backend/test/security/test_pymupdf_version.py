import pymupdf
from packaging.version import Version


def test_embedded_mupdf_contains_cve_2026_3308_fix():
    assert Version(pymupdf.VersionFitz) >= Version("1.27.1"), (
        f"MuPDF versions before 1.27.1 are vulnerable to CVE-2026-3308; found {pymupdf.VersionFitz}"
    )
