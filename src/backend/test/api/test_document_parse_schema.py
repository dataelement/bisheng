"""Document-parse settings payloads and credential resolution."""

from pydantic import ValidationError

from bisheng.knowledge.domain.schemas.document_parse_schema import DocumentParseConfig

JOBS = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"

def _payload(**overrides) -> DocumentParseConfig:
    base = {
        "loader_provider": "paddle_ocr",
        "paddle_ocr_url": JOBS,
        "paddle_ocr_model": "PaddleOCR-VL-1.6",
        "paddle_ocr_api_key_env": "PADDLE_OCR_TOKEN",
    }
    return DocumentParseConfig(**{**base, **overrides})

def test_jobs_config_requires_model():
    _payload()  # valid
    try:
        _payload(paddle_ocr_model="")
    except ValidationError:
        return
    raise AssertionError("the model must be required for the jobs API")

def test_jobs_config_does_not_require_a_token_variable():
    """A token may already be stored, or arrive through the environment later."""
    conf = _payload(paddle_ocr_api_key_env="")
    assert conf.paddle_ocr_api_key_env == ""

def test_sync_mode_needs_neither_model_nor_token_variable():
    conf = _payload(paddle_ocr_service_mode="sync", paddle_ocr_model="", paddle_ocr_api_key_env="")
    assert conf.paddle_ocr_service_mode == "sync"

def test_other_providers_are_not_forced_into_jobs_rules():
    conf = DocumentParseConfig(loader_provider="etl4lm", paddle_ocr_model="", paddle_ocr_api_key_env="")
    assert conf.loader_provider == "etl4lm"

def test_unknown_provider_is_rejected():
    try:
        DocumentParseConfig(loader_provider="not_a_provider")
    except ValidationError:
        return
    raise AssertionError("the provider must be one the pipeline supports")

def test_stored_token_wins_over_the_environment(monkeypatch):
    """A token typed in the form must not be silently overridden by a leftover variable."""
    from bisheng.core.config.settings import PaddleOcrConf, encrypt_token
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import resolve_token

    monkeypatch.setenv("TEST_OCR_TOKEN", "from-env")
    conf = PaddleOcrConf(
        url=JOBS,
        model="m",
        api_key_env="TEST_OCR_TOKEN",
        auth_token_enc=encrypt_token("from-db").decode(),
    )

    assert resolve_token(conf) == "from-db"

def test_environment_token_is_the_fallback_when_nothing_is_stored(monkeypatch):
    from bisheng.core.config.settings import PaddleOcrConf
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import resolve_token

    monkeypatch.setenv("TEST_OCR_TOKEN", "from-env")
    conf = PaddleOcrConf(url=JOBS, model="m", api_key_env="TEST_OCR_TOKEN")

    assert resolve_token(conf) == "from-env"

def test_undecryptable_stored_token_fails_loudly():
    from bisheng.core.config.settings import PaddleOcrConf
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import PaddleOcrJobsError, resolve_token

    conf = PaddleOcrConf(url=JOBS, model="m", api_key_env="", auth_token_enc="not-a-fernet-token")
    try:
        resolve_token(conf)
    except PaddleOcrJobsError as exc:
        assert "cannot be decrypted" in str(exc)
        return
    raise AssertionError("a corrupt ciphertext must not degrade to an empty token")

def test_no_token_anywhere_yields_empty_string():
    from bisheng.core.config.settings import PaddleOcrConf
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr_client import resolve_token

    assert resolve_token(PaddleOcrConf(url=JOBS, model="m", api_key_env="")) == ""
