"""MinerU (self-hosted) API key handling.

The key is stored encrypted in the config and injected as a request header at
load time, so an operator can set it from the admin form instead of hand-editing
the ``headers`` map.
"""

from bisheng.core.config.settings import MineruConf, encrypt_token
from bisheng.knowledge.rag.pipeline.loader.mineru import MineruLoader


def _loader(**kwargs) -> MineruLoader:
    return MineruLoader(
        url="http://mineru.test/file_parse",
        file_path="/tmp/unused.pdf",
        file_metadata={},
        file_extension="pdf",
        tmp_dir="/tmp",
        **kwargs,
    )


def test_stored_key_is_injected_as_the_default_header():
    enc = encrypt_token("secret-key").decode()
    loader = _loader(api_key_enc=enc)
    assert loader.headers["x-api-key"] == "secret-key"


def test_key_header_name_is_configurable():
    enc = encrypt_token("secret-key").decode()
    loader = _loader(api_key_enc=enc, api_key_header="X-Custom-Key")
    assert loader.headers == {"X-Custom-Key": "secret-key"}


def test_stored_key_overrides_a_stale_header_in_the_file():
    enc = encrypt_token("new-key").decode()
    loader = _loader(api_key_enc=enc, headers={"x-api-key": "old"})
    assert loader.headers["x-api-key"] == "new-key"


def test_no_key_leaves_headers_untouched():
    loader = _loader(headers={"x-api-key": "from-file"})
    assert loader.headers == {"x-api-key": "from-file"}


def test_loader_does_not_mutate_the_callers_headers_dict():
    headers = {"x-api-key": "from-file"}
    _loader(api_key_enc=encrypt_token("k").decode(), headers=headers)
    assert headers == {"x-api-key": "from-file"}, "settings must not be mutated in place"


def test_mineru_conf_defaults():
    conf = MineruConf()
    assert conf.api_key_header == "x-api-key" and conf.api_key_enc == ""
