import unittest

from bisheng.llm.domain.schemas import AssistantLLMConfig, AssistantLLMItem


class TestAssistantExecutorTypeFallback(unittest.TestCase):
    def test_default_is_function_call(self):
        self.assertEqual(AssistantLLMItem().agent_executor_type, "function call")

    def test_blank_or_unknown_values_fall_back_to_function_call(self):
        for value in ("", None, "React", "unknown"):
            with self.subTest(value=value):
                item = AssistantLLMItem(agent_executor_type=value)
                self.assertEqual(item.agent_executor_type, "function call")

    def test_explicit_choices_are_kept(self):
        for value in ("ReAct", "function call"):
            with self.subTest(value=value):
                self.assertEqual(AssistantLLMItem(agent_executor_type=value).agent_executor_type, value)

    def test_stored_blank_config_is_normalized_on_read(self):
        # Rows saved by the old UI carry an explicit "" that bypassed the schema default.
        stored = {
            "llm_list": [{"model_id": 1, "agent_executor_type": ""}],
            "auto_llm": {"model_id": 2, "agent_executor_type": ""},
        }
        cfg = AssistantLLMConfig(**stored)
        self.assertEqual(cfg.llm_list[0].agent_executor_type, "function call")
        self.assertEqual(cfg.auto_llm.agent_executor_type, "function call")
