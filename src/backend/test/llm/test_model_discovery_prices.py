"""F016: vendor-listed models carry the catalog price that adding them would prefill."""

from bisheng.llm.domain.pricing.service import discovered_model_prices


def _rows(*names):
    return [
        {"model_name": name, "display_name": name, "model_type": "llm", "type_source": "registry"} for name in names
    ]


def test_listed_models_carry_their_catalog_price_and_unknown_ones_stay_unpriced():
    result = discovered_model_prices(
        "openai", {"models": _rows("gpt-4.1", "gpt-9-preview"), "source": "live", "scope": "catalog"}
    )
    priced, unknown = result["models"]
    assert priced["catalog"] == {"vendor": "OpenAI", "label": "GPT-4.1", "currency": "USD", "input": "2", "output": "8"}
    assert "catalog" not in unknown
    assert result["source"] == "live"


def test_gateway_rows_match_by_name_without_the_vendor_prefix():
    result = discovered_model_prices("openai_compatible", {"models": _rows("openai/gpt-4.1", "deepseek-v4-pro")})
    assert [row["catalog"]["label"] for row in result["models"]] == ["GPT-4.1", "DeepSeek V4 Pro"]
    assert result["models"][1]["catalog"]["currency"] == "CNY"


def test_azure_model_catalog_is_not_priced_by_model_name():
    # Adding an Azure row stores the deployment name the admin types, so the model name's price may not apply.
    result = discovered_model_prices("azure_openai", {"models": _rows("gpt-4.1"), "scope": "azure_models"})
    assert "catalog" not in result["models"][0]
