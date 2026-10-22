"""Exact model capabilities, independent of provider display names."""

ALI_MODELS = {
    "paraformer-realtime-v2": "paraformer",
    "paraformer-realtime-v1": "paraformer",
    "qwen3-asr-flash-realtime": "qwen",
}
BAIDU_MODELS = {"1537", "15372", "15376", "1737", "17372"}
TENCENT_MODELS = {
    "16k_zh_en",
    "16k_multi_lang",
    "16k_en_large",
    "16k_zh",
    "16k_zh-TW",
    "16k_zh_edu",
    "16k_zh_medical",
    "16k_zh_court",
    "16k_yue",
    "16k_en",
    "16k_en_game",
    "16k_en_edu",
    "16k_ko",
    "16k_ja",
    "16k_th",
    "16k_id",
    "16k_vi",
    "16k_ms",
    "16k_fil",
    "16k_pt",
    "16k_tr",
    "16k_ar",
    "16k_es",
    "16k_hi",
    "16k_fr",
    "16k_de",
}
VOLC_RESOURCES = {
    "volc.bigasr.sauc.duration",
    "volc.bigasr.sauc.concurrent",
    "volc.seedasr.sauc.duration",
    "volc.seedasr.sauc.concurrent",
}


def should_promote_legacy_asr(server_type: str, model_name: str | None, model_type: str) -> bool:
    """File-typed rows whose engine already has a realtime client.

    The provider lives on ``llm_server.type``. Callers must not add a tenant
    filter: every tenant's matching row moves together.
    """
    return model_type == "asr" and realtime_protocol(server_type, model_name) is not None


def realtime_protocol(provider: str, model: str | None) -> str | None:
    if provider == "qwen":
        return ALI_MODELS.get(model or "")
    if provider == "volcengine" and model == "bigmodel":
        return "volcengine"
    if provider == "qianfan" and model in BAIDU_MODELS:
        return "baidu"
    if provider == "tencent" and model in TENCENT_MODELS:
        return "tencent"
    return None
