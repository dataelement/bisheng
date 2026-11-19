"""Provider probes used by the settings form's connection test.

A probe must separate "wrong credential" from "service down" without doing real
work; the classifications below mirror what the live services actually answer.
"""



JOBS = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"

_UNSET = object()

def _probe(handler, token=_UNSET, **conf_kwargs):
    import httpx as _httpx

    from bisheng.core.config.settings import PaddleOcrConf
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import probe_connection

    defaults = {"url": JOBS, "model": "PaddleOCR-VL-1.6", "api_key_env": ""}
    conf = PaddleOcrConf(**{**defaults, **conf_kwargs})
    # `_UNSET` = let the probe resolve the token itself (stored ciphertext / env).
    explicit = None if token is _UNSET else token
    return probe_connection(conf, transport=_httpx.MockTransport(handler), token=explicit)

def test_probe_reports_ok_when_the_service_accepts_token_and_model(monkeypatch):
    import httpx as _httpx

    def handler(request):
        assert request.headers["Authorization"] == "token typed-in-form"
        assert b'name="model"' in request.content, "the probe must send the model as a form field"
        return _httpx.Response(400, json={"code": 10001, "msg": "空文件"})

    result = _probe(handler, token="typed-in-form")
    assert result["status"] == "ok"

def test_probe_reports_invalid_token():
    import httpx as _httpx

    result = _probe(lambda r: _httpx.Response(401, json={"code": 401, "msg": "Unauthorized"}), token="bad")
    assert result["status"] == "token_invalid"

def test_probe_reports_invalid_model():
    import httpx as _httpx

    result = _probe(lambda r: _httpx.Response(400, json={"code": 10007, "msg": "模型传参错误"}), token="t")
    assert result["status"] == "model_invalid"

def test_probe_reports_unreachable_service():
    import httpx as _httpx

    def handler(request):
        raise _httpx.ConnectError("boom")

    result = _probe(handler, token="t")
    assert result["status"] == "unreachable"

def test_probe_reports_missing_token_and_model():
    assert _probe(lambda r: None, token="")["status"] == "token_missing"
    assert _probe(lambda r: None, token="t", model="")["status"] == "misconfigured"

def test_probe_rejects_an_unusable_url():
    assert _probe(lambda r: None, url="not-a-url", token="t")["status"] == "misconfigured"

def test_probe_uses_the_stored_token_when_none_is_typed(monkeypatch):
    """Testing right after load must work without re-typing the token."""
    import httpx as _httpx

    from bisheng.core.config.settings import encrypt_token

    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        return _httpx.Response(400, json={"code": 10001})

    result = _probe(handler, auth_token_enc=encrypt_token("stored").decode())
    assert result["status"] == "ok"
    assert seen["auth"] == "token stored"

def test_reachability_probe_classifies_answers():
    import httpx as _httpx

    from bisheng.knowledge.rag.pipeline.loader.provider_probe import probe_endpoint

    def probe(status):
        return probe_endpoint("https://svc.test/parse", "k", transport=_httpx.MockTransport(
            lambda r: _httpx.Response(status, json={})))

    assert probe(200)["status"] == "ok"
    assert probe(405)["status"] == "ok", "method-not-allowed still proves it is reachable"
    assert probe(401)["status"] == "token_invalid"
    assert probe(403)["status"] == "token_invalid"
    assert probe_endpoint("", "k")["status"] == "misconfigured"

def test_reachability_probe_reports_transport_failure():
    import httpx as _httpx

    from bisheng.knowledge.rag.pipeline.loader.provider_probe import probe_endpoint

    def handler(request):
        raise _httpx.ConnectError("boom")

    assert probe_endpoint("https://svc.test", transport=_httpx.MockTransport(handler))["status"] == "unreachable"

def _probe_mv4(handler, url="https://mineru.test/api/v4/extract/task", key="k"):
    import httpx as _httpx

    from bisheng.knowledge.rag.pipeline.loader.provider_probe import probe_mineru_v4

    return probe_mineru_v4(url, key, transport=_httpx.MockTransport(handler))

def test_mv4_cloud_url_is_accepted_now_that_the_hosted_api_is_supported():
    import httpx as _httpx

    result = _probe_mv4(lambda r: _httpx.Response(200, json={"code": -10002, "msg": 'field "url" is not set'}))
    assert result["status"] == "ok"
    assert "accepted" in result["message"], "the operator should learn the key is fine"
    assert "sharepoint" in result["message"], "and that documents must be publicly reachable"

def test_mv4_cloud_url_with_a_rejected_key_is_token_invalid():
    import httpx as _httpx

    assert _probe_mv4(lambda r: _httpx.Response(401, json={"code": 401}))["status"] == "token_invalid"

def test_mv4_self_hosted_root_probes_the_job_api():
    import httpx as _httpx

    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return _httpx.Response(200, json={})

    result = _probe_mv4(handler, url="https://mineru.test")
    assert seen["path"] == "/v1/uploads", "a bare root must be probed on the job API, not the root itself"
    assert result["status"] == "ok"

def test_mv4_self_hosted_root_404_is_reported_as_wrong_shape():
    import httpx as _httpx

    result = _probe_mv4(lambda r: _httpx.Response(404), url="https://mineru.test")
    assert result["status"] == "misconfigured"
    assert "/v1" in result["message"]

def test_mv4_probe_reports_transport_failure():
    import httpx as _httpx

    def handler(request):
        raise _httpx.ConnectError("boom")

    assert _probe_mv4(handler)["status"] == "unreachable"

def test_probe_endpoint_uses_a_custom_header_and_no_prefix():
    """A self-hosted MinerU authenticates with x-api-key, not a Bearer token."""
    import httpx as _httpx

    from bisheng.knowledge.rag.pipeline.loader.provider_probe import probe_endpoint

    seen = {}

    def handler(request):
        seen.update(dict(request.headers))
        return _httpx.Response(200)

    probe_endpoint(
        "https://mineru.test/file_parse",
        "k",
        transport=_httpx.MockTransport(handler),
        token_header="x-api-key",
        token_prefix="",
    )
    assert seen["x-api-key"] == "k"
    assert "authorization" not in seen

def test_probe_reports_a_broken_service_as_error():
    import httpx as _httpx

    from bisheng.knowledge.rag.pipeline.loader.provider_probe import probe_endpoint

    result = probe_endpoint("https://svc.test", transport=_httpx.MockTransport(lambda r: _httpx.Response(500)))
    assert result["status"] == "error", "a 5xx must not read as a healthy connection"
