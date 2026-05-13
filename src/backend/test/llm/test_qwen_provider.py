import ast
import json
import os
import unittest

from bisheng.core.ai import ChatOpenAICompatible


class TestQwenProvider(unittest.TestCase):
    def setUp(self):
        self.api_key = os.environ.get("QWEN_API_KEY")

    @unittest.skipUnless(os.environ.get("QWEN_API_KEY"), "QWEN_API_KEY not set")
    def test_qwen35(self):
        llm = ChatOpenAICompatible(api_key=self.api_key, model="qwen3.5-plus",
                                   base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        result = llm.invoke("hello")
        print(result)


class TestQwenParamsFunction(unittest.TestCase):
    """Unit tests for Qwen provider parameter assembly."""

    @classmethod
    def setUpClass(cls):
        llm_py_path = os.path.join(
            os.path.dirname(__file__), '..', '..', 'bisheng', 'llm', 'domain', 'llm', 'llm.py'
        )
        llm_py_path = os.path.normpath(llm_py_path)
        with open(llm_py_path) as f:
            source = f.read()

        tree = ast.parse(source)
        funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                    '_get_user_kwargs',
                    '_get_openai_params',
                    '_get_qwen_params',
            ):
                funcs[node.name] = ast.get_source_segment(source, node)

        combined = '\n\n'.join([
            funcs['_get_user_kwargs'],
            funcs['_get_openai_params'],
            funcs['_get_qwen_params'],
        ])
        exec_globals = {'json': json}
        exec(compile(combined, '<test>', 'exec'), exec_globals)
        cls._qwen_params_fn = staticmethod(exec_globals['_get_qwen_params'])

    def test_uses_frontend_configured_base_url(self):
        result = self._qwen_params_fn(
            {'model': 'qwen-plus'},
            {
                'openai_api_key': 'key',
                'openai_api_base': 'https://proxy.example.com/compatible-mode/v1/',
            },
            {}
        )
        self.assertEqual(result['base_url'], 'https://proxy.example.com/compatible-mode/v1')

    def test_falls_back_to_dashscope_default(self):
        result = self._qwen_params_fn(
            {'model': 'qwen-plus'},
            {'openai_api_key': 'key'},
            {}
        )
        self.assertEqual(result['base_url'], 'https://dashscope.aliyuncs.com/compatible-mode/v1')

    def test_preserves_qwen_extra_body_flags(self):
        result = self._qwen_params_fn(
            {'model': 'qwen-plus', 'streaming': True, 'model_kwargs': {'enable_thinking': True}},
            {'openai_api_key': 'key'},
            {'enable_web_search': True}
        )
        self.assertTrue(result['extra_body']['enable_search'])
        self.assertTrue(result['extra_body']['incremental_output'])
        self.assertTrue(result['extra_body']['enable_thinking'])
