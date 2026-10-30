"""Versioned, opt-in public catalogs. These entries express no account entitlement."""

PRESETS = {
    "zhipu": {
        "hosts": {"open.bigmodel.cn"},
        "docs": "https://docs.bigmodel.cn/cn/guide/start/model-overview",
        "models": {
            "llm": ["glm-5.3", "glm-5.2", "glm-5.3-flash", "glm-5.3-flashx"],
            "embedding": ["embedding-3"],
            "asr": ["glm-asr-2512"],
            "tts": ["glm-tts"],
        },
    },
    "spark": {
        "hosts": {"spark-api-open.xf-yun.com"},
        "docs": "https://www.xfyun.cn/doc/spark/HTTP调用文档.html",
        "models": {"llm": ["4.0Ultra", "generalv3.5", "max-32k", "generalv3", "pro-128k", "lite"]},
    },
    "minimax": {
        "hosts": {"api.minimax.cn", "api.minimax.io", "api.minimax.chat"},
        "docs": "https://platform.minimax.io/docs/api-reference/text-openai-api",
        "models": {"llm": ["MiniMax-M3.1-Flash", "MiniMax-M3"]},
    },
    "tencent": {
        "hosts": {"api.hunyuan.cloud.tencent.com"},
        "docs": "https://cloud.tencent.com/document/product/1729/111007",
        "models": {"llm": ["hunyuan-turbos-latest", "hunyuan-vision"], "embedding": ["hunyuan-embedding"]},
    },
}


def preset_catalog(provider: str) -> tuple[dict, str]:
    from bisheng.common.errcode.llm import ModelDiscoveryError

    preset = PRESETS.get(provider)
    if preset is None:
        raise ModelDiscoveryError(reason="unsupported")
    return {
        "data": [{"id": name, "model_type": kind} for kind, names in preset["models"].items() for name in names]
    }, preset["docs"]
