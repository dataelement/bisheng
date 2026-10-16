from bisheng.llm.domain.llm.llm import _get_tencent_params

SERVER = {"openai_api_key": "key", "openai_api_base": "https://api.hunyuan.cloud.tencent.com/v1/"}


def test_web_search_toggle_drives_enable_enhancement():
    on = _get_tencent_params({"model": "hunyuan-turbos-latest"}, SERVER, {"enable_web_search": True})
    off = _get_tencent_params({"model": "hunyuan-turbos-latest"}, SERVER, {})
    assert on["extra_body"]["enable_enhancement"] is True
    assert off["extra_body"]["enable_enhancement"] is False


def test_keeps_user_extra_body_and_toggle_wins():
    user_kwargs = '{"extra_body": {"citation": true, "enable_enhancement": true}}'
    result = _get_tencent_params(
        {"model": "hunyuan-turbos-latest"}, SERVER, {"user_kwargs": user_kwargs, "enable_web_search": False}
    )
    assert result["extra_body"] == {"citation": True, "enable_enhancement": False}
    assert result["base_url"] == "https://api.hunyuan.cloud.tencent.com/v1"
