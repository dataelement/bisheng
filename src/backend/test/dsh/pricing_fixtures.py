"""F016 test prices. Every LLM model has a price after the upgrade, so fakes need one too."""

# 0.01 per million tokens on every token class with the default 0.01 credit value bills
# exactly one microcredit per token, i.e. the same as the removed 1x multiplier.
LEGACY_EQUIVALENT_PRICING = {
    "currency": "CNY",
    "input": "0.01",
    "cache_read": "0.01",
    "cache_write": "0.01",
    "output": "0.01",
    "source": "MANUAL",
}
PRICED_CONFIG = {"pricing": LEGACY_EQUIVALENT_PRICING}
