"""vector_runtime 读 ES 认证: JSON list 要转成 tuple, 否则 401."""

import sys

from test.upgrade_ab_fusion._packutil import PACK, ensure_pack_path

ensure_pack_path()
sys.path.insert(0, str(PACK / "p5"))
from vector_runtime import es_kwargs_from_env


def test_es_kwargs_json_basic_auth_list_becomes_tuple():
    kw = es_kwargs_from_env('{"basic_auth": ["elastic", "secret"]}')
    assert kw["basic_auth"] == ("elastic", "secret")


def test_es_kwargs_empty_is_dict():
    assert es_kwargs_from_env(None) == {}
    assert es_kwargs_from_env("") == {}
    assert es_kwargs_from_env("{}") == {}


def test_sanitize_es_mapping_drops_custom_bm25():
    from vector_runtime import sanitize_es_mapping

    src = {
        "mappings": {
            "properties": {
                "text": {"type": "text", "similarity": "custom_bm25"},
                "file_id": {"type": "keyword"},
            }
        }
    }
    out = sanitize_es_mapping(src)
    assert "similarity" not in out["mappings"]["properties"]["text"]
    assert out["mappings"]["properties"]["text"]["type"] == "text"
    assert out["mappings"]["properties"]["file_id"]["type"] == "keyword"
