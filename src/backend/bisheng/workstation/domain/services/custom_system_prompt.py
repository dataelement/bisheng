"""The administrator's custom system prompt of the workbench (F004 design 决策 15).

Daily chat and deep research both put this text first in the main graph's system
prompt. It holds only the persona and business requirements; platform abilities
(language, citations, current time, charts, grounding) live in code.

The platform admin page fills an empty field with the same default in the admin's
UI language (``chatConfig.customSystemPromptDefault`` in the platform locales);
``test_custom_system_prompt.py`` keeps the zh-Hans text equal to
:data:`DEFAULT_CUSTOM_SYSTEM_PROMPT_ZH`.
"""

from loguru import logger

DEFAULT_BRAND_NAME = "BISHENG"
# ``{brand}`` is the brand name of the deployment (``BrandService.get_brand_name``).
DEFAULT_CUSTOM_SYSTEM_PROMPT_ZH = "你是 {brand} 智能助手，帮助用户解答问题、完成工作任务。"


def default_custom_system_prompt(brand: str | None = None) -> str:
    return DEFAULT_CUSTOM_SYSTEM_PROMPT_ZH.replace("{brand}", (brand or "").strip() or DEFAULT_BRAND_NAME)


async def _brand_name() -> str:
    from bisheng.brand.domain.services.brand_service import BrandService

    try:
        return (await BrandService().get_brand_name()).zh
    except Exception:
        # The persona still has a name when the brand row cannot be read.
        logger.opt(exception=True).warning("custom system prompt: brand name unavailable, using the default")
        return DEFAULT_BRAND_NAME


async def custom_system_prompt() -> str:
    """The saved ``customSystemPrompt`` of the current tenant, or the built-in default when empty.

    The text is used as saved: no ``{cur_date}`` substitution (the current time is in
    every turn's user message), so the prompt prefix stays the same across turns.
    The legacy ``systemPrompt`` key is not read: existing deployments move to the new
    default on upgrade (design 决策 15, upgrade.md 第八节).
    """
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    try:
        config = await WorkStationService.aget_config()
    except Exception:
        # A run is not failed over its persona; it answers with the default one.
        logger.opt(exception=True).warning("custom system prompt: workbench config unavailable, using the default")
        config = None
    text = (getattr(config, "customSystemPrompt", None) or "").strip() if config is not None else ""
    if text:
        return text
    return default_custom_system_prompt(await _brand_name())
