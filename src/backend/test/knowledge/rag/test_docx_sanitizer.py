import zipfile

from bisheng.knowledge.rag.pipeline.loader.utils.docx_sanitizer import sanitize_docx_textbox_noise

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


def _write_docx(path, document_xml: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("[Content_Types].xml", "<Types />")


def test_sanitize_docx_textbox_noise_removes_encoded_fallback_text(tmp_path):
    noise = "AbCdEf0123456789" * 40
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:wps="{WPS_NS}">
  <w:body>
    <w:p><w:r><w:t>可见正文</w:t></w:r></w:p>
    <w:p>
      <w:r>
        <wps:txbx>
          <w:txbxContent>
            <w:p><w:r><w:t>{noise}</w:t></w:r></w:p>
            <w:p><w:r><w:t>正常文本框内容 with spaces</w:t></w:r></w:p>
          </w:txbxContent>
        </wps:txbx>
      </w:r>
    </w:p>
  </w:body>
</w:document>
"""
    source_path = tmp_path / "source.docx"
    _write_docx(source_path, document_xml)

    sanitized_path = sanitize_docx_textbox_noise(source_path, tmp_path)

    assert sanitized_path != source_path
    with zipfile.ZipFile(sanitized_path) as archive:
        cleaned_xml = archive.read("word/document.xml").decode("utf-8")
    assert noise not in cleaned_xml
    assert "可见正文" in cleaned_xml
    assert "正常文本框内容 with spaces" in cleaned_xml


def test_sanitize_docx_textbox_noise_keeps_normal_docx(tmp_path):
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:wps="{WPS_NS}">
  <w:body>
    <w:p><w:r><w:t>可见正文</w:t></w:r></w:p>
    <w:p>
      <w:r>
        <wps:txbx>
          <w:txbxContent>
            <w:p><w:r><w:t>正常文本框内容 with spaces</w:t></w:r></w:p>
          </w:txbxContent>
        </wps:txbx>
      </w:r>
    </w:p>
  </w:body>
</w:document>
"""
    source_path = tmp_path / "source.docx"
    _write_docx(source_path, document_xml)

    sanitized_path = sanitize_docx_textbox_noise(source_path, tmp_path)

    assert sanitized_path == source_path
