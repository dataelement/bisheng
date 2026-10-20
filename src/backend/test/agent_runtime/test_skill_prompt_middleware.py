"""F078 T17: the skill rules appended to the system prompt."""

from langchain_core.messages import SystemMessage

from bisheng.agent_runtime.domain.services.skill_prompt_middleware import (
    SkillPromptMiddleware,
    SkillPromptVariant,
    skill_rules_text,
)


class _Request:
    def __init__(self, system_message):
        self.system_message = system_message

    def override(self, system_message):
        return _Request(system_message)


def _run(middleware, prompt):
    seen = {}

    def handler(request):
        seen["system"] = request.system_message
        return "ok"

    assert middleware.wrap_model_call(_Request(SystemMessage(content=prompt)), handler) == "ok"
    return seen["system"]


def _text(message):
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


class TestSkillRules:
    def test_every_variant_requires_reading_skill_md_first(self):
        for variant in SkillPromptVariant:
            text = skill_rules_text(variant)
            assert "SKILL.md" in text
            assert "limit=1000" in text

    def test_with_executor_points_files_at_output_and_the_interpreter(self):
        text = skill_rules_text(SkillPromptVariant.WITH_EXECUTOR)
        assert "/output/" in text
        assert "bisheng_code_interpreter" in text

    def test_without_executor_says_scripts_cannot_run(self):
        text = skill_rules_text(SkillPromptVariant.NO_EXECUTOR)
        assert "bisheng_code_interpreter" not in text
        assert "无法" in text


class TestMiddleware:
    def test_appends_after_the_author_prompt(self):
        author = "你是周报助手。"
        system = _text(_run(SkillPromptMiddleware(SkillPromptVariant.WITH_EXECUTOR), author))
        assert system.startswith(author)
        assert system.endswith(skill_rules_text(SkillPromptVariant.WITH_EXECUTOR))

    async def test_async_hook_appends_the_same_text(self):
        middleware = SkillPromptMiddleware(SkillPromptVariant.NO_EXECUTOR)
        seen = {}

        async def handler(request):
            seen["system"] = request.system_message
            return "ok"

        await middleware.awrap_model_call(_Request(SystemMessage(content="p")), handler)
        assert _text(seen["system"]).endswith(skill_rules_text(SkillPromptVariant.NO_EXECUTOR))

    def test_registers_no_tools(self):
        assert SkillPromptMiddleware(SkillPromptVariant.WITH_EXECUTOR).tools == []
