"""Text-level updates to the stored configuration.

The settings form patches the stored YAML by hand so operator comments survive;
a bug here silently rewrites unrelated sections, hence the byte-level assertions.
"""

import yaml

from bisheng.common.services.config_service import ConfigService

BASE = """\
knowledges: # 知识库相关配置
  loader_provider: "etl4lm" # 文档解析模型提供商
  paddle_ocr:
    # 文档地址
    url: "https://example.test/layout-parsing" # sync service
    auth_token: ''
    timeout: 60
  version_management:
    enabled: false

llm_request:
  timeout: 30
"""

def _load(text: str) -> dict:
    return yaml.safe_load(text)

def test_sets_existing_scalar_and_keeps_trailing_comment():
    out = ConfigService.update_section_scalars(BASE, ["knowledges"], {"loader_provider": "paddle_ocr"})
    assert _load(out)["knowledges"]["loader_provider"] == "paddle_ocr"
    line = next(line for line in out.splitlines() if "loader_provider:" in line)
    assert "# 文档解析模型提供商" in line, "an operator's trailing comment must survive"

def test_updates_nested_scalars_only():
    out = ConfigService.update_section_scalars(
        BASE, ["knowledges", "paddle_ocr"], {"url": "https://new.test/jobs", "timeout": 99}
    )
    paddle = _load(out)["knowledges"]["paddle_ocr"]
    assert paddle["url"] == "https://new.test/jobs"
    assert paddle["timeout"] == 99
    assert "# sync service" in next(line for line in out.splitlines() if line.strip().startswith("url:"))

def test_leaves_other_sections_and_keys_untouched():
    before = _load(BASE)
    out = ConfigService.update_section_scalars(BASE, ["knowledges", "paddle_ocr"], {"timeout": 5})
    after = _load(out)
    assert after["llm_request"] == before["llm_request"]
    assert after["knowledges"]["version_management"] == before["knowledges"]["version_management"]
    assert after["knowledges"]["paddle_ocr"]["auth_token"] == before["knowledges"]["paddle_ocr"]["auth_token"]
    assert out.count("#") == BASE.count("#"), "no comment may be dropped or added"

def test_appends_keys_missing_from_the_section():
    out = ConfigService.update_section_scalars(BASE, ["knowledges", "paddle_ocr"], {"model": "PaddleOCR-VL-1.6"})
    paddle = _load(out)["knowledges"]["paddle_ocr"]
    assert paddle["model"] == "PaddleOCR-VL-1.6"
    assert paddle["timeout"] == 60, "existing siblings keep their values"
    # The blank line separating the next top-level key stays where it was.
    assert "\n\nllm_request:" in out

def test_values_are_yaml_quoted_so_special_characters_round_trip():
    url = "https://example.test/path?q=a#b&x=1"  # a bare '#' would start a comment
    out = ConfigService.update_section_scalars(BASE, ["knowledges", "paddle_ocr"], {"url": url})
    assert _load(out)["knowledges"]["paddle_ocr"]["url"] == url

def test_unknown_section_is_rejected_loudly():
    try:
        ConfigService.update_section_scalars(BASE, ["does_not_exist"], {"a": 1})
    except ValueError as exc:
        assert "does_not_exist" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a missing section must not be silently created")

def test_multi_section_update_keeps_unrelated_comments():
    """Saving the form rewrites four sections; nothing else may move."""
    sections = {
        ("knowledges", "etl4lm"): {"url": "https://etl.test/x", "timeout": 601},
        ("knowledges", "mineru"): {"url": "https://mineru.test/x"},
        ("knowledges", "mineru_v4"): {"api_url": "https://mv4.test/api", "ocr_mode": "ocr"},
    }
    text = """\
knowledges: # 知识库相关配置
  loader_provider: "mine" # provider
  etl4lm:
    url: "" # 文档解析服务
    timeout: 600
  mineru:
    url: ""
  mineru_v4:
    api_url: ""
    ocr_mode: "auto"

llm_request:
  timeout: 30
"""
    out = text
    for path, values in sections.items():
        out = ConfigService.update_section_scalars(out, list(path), values)

    parsed = _load(out)
    assert parsed["knowledges"]["etl4lm"]["timeout"] == 601
    assert parsed["knowledges"]["mineru_v4"]["ocr_mode"] == "ocr"
    assert out.count("#") == text.count("#")
    assert parsed["llm_request"]["timeout"] == 30

def test_request_kwargs_dict_round_trips_through_the_text_updater():
    """request_kwargs is a mapping; writing it must stay valid YAML."""
    text = """\
knowledges:
  mineru:
    url: "http://mineru.test" # 服务地址
    request_kwargs:
      backend: "pipeline"

llm_request:
  timeout: 30
"""
    out = ConfigService.update_section_scalars(
        text, ["knowledges", "mineru"], {"request_kwargs": {"backend": "vlm", "extra": 1}}
    )
    parsed = _load(out)["knowledges"]["mineru"]
    assert parsed["request_kwargs"] == {"backend": "vlm", "extra": 1}
    assert out.count("#") == text.count("#")
    assert _load(out)["llm_request"]["timeout"] == 30

def test_trailing_comment_survives_an_escaped_quote():
    """`url: "a\\"#b"  # note` used to swallow the comment: the escape was not skipped."""
    value, comment = ConfigService._split_trailing_comment('    url: "a\\"#b"  # note')
    assert comment == "# note"
    assert value.endswith('"a\\"#b"')

def test_dotted_key_updates_one_child_and_keeps_the_rest():
    """`request_kwargs.backend` must not replace the whole mapping."""
    text = """\
knowledges:
  mineru:
    request_kwargs:
      backend: "pipeline"  # 解析后端
      timeout: 30

llm_request:
  timeout: 30
"""
    out = ConfigService.update_section_scalars(text, ["knowledges", "mineru"], {"request_kwargs.backend": "vlm"})
    kwargs = _load(out)["knowledges"]["mineru"]["request_kwargs"]
    assert kwargs == {"backend": "vlm", "timeout": 30}, "sibling keys must survive"
    assert "解析后端" in out, "the child's comment must survive"
    assert out.count("#") == text.count("#")
