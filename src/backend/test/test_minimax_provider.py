"""Tests for MiniMax provider upgrade to OpenAI-compatible API (M2.7 support).

These tests verify the MiniMax provider changes without requiring the full
bisheng backend to be installed, by testing the specific files that were changed.
"""
import json
import os
import ast
import unittest


class TestMiniMaxLLMModuleChanges(unittest.TestCase):
    """Unit tests verifying the LLM module changes via AST inspection."""

    @classmethod
    def setUpClass(cls):
        cls.llm_py_path = os.path.join(
            os.path.dirname(__file__), '..', 'bisheng', 'llm', 'domain', 'llm', 'llm.py'
        )
        cls.llm_py_path = os.path.normpath(cls.llm_py_path)
        with open(cls.llm_py_path) as f:
            cls.llm_source = f.read()
        cls.llm_tree = ast.parse(cls.llm_source)

    def test_minimax_chat_not_imported(self):
        """MiniMaxChat should NOT be imported in llm.py."""
        self.assertNotIn('MiniMaxChat', self.llm_source)

    def test_chat_openai_compatible_imported(self):
        """ChatOpenAICompatible should be imported in llm.py."""
        self.assertIn('ChatOpenAICompatible', self.llm_source)

    def test_get_minimax_params_removed(self):
        """The legacy _get_minimax_params function should be removed."""
        for node in ast.walk(self.llm_tree):
            if isinstance(node, ast.FunctionDef) and node.name == '_get_minimax_params':
                self.fail('_get_minimax_params function still exists in llm.py')

    def test_minimax_entry_uses_openai_compatible(self):
        """_llm_node_type['minimax'] should reference ChatOpenAICompatible."""
        found = False
        for line in self.llm_source.splitlines():
            if 'MINIMAX' in line and 'client' in line:
                self.assertIn('ChatOpenAICompatible', line,
                              f'MINIMAX client should be ChatOpenAICompatible, got: {line.strip()}')
                found = True
                break
        self.assertTrue(found, 'Could not find MINIMAX entry in _llm_node_type')

    def test_minimax_entry_uses_openai_params(self):
        """_llm_node_type['minimax'] should use _get_openai_params handler."""
        for line in self.llm_source.splitlines():
            if 'MINIMAX' in line and 'params_handler' in line:
                self.assertIn('_get_openai_params', line,
                              f'MINIMAX params handler should be _get_openai_params, got: {line.strip()}')
                return
        self.fail('Could not find MINIMAX params_handler entry')

    def test_web_search_support_preserved(self):
        """Web search tool support for MiniMax should still be present."""
        self.assertIn('web_search', self.llm_source)
        in_parse_kwargs = False
        found_minimax_web_search = False
        for line in self.llm_source.splitlines():
            if 'def parse_kwargs' in line:
                in_parse_kwargs = True
            if in_parse_kwargs and 'MINIMAX' in line:
                found_minimax_web_search = True
                break
        self.assertTrue(found_minimax_web_search,
                        'MiniMax web_search support not found in parse_kwargs')

    def test_no_legacy_minimax_api_key_param(self):
        """No function should set minimax_api_key (legacy param)."""
        self.assertNotIn("minimax_api_key", self.llm_source)

    def test_no_chat_completions_appended_for_minimax(self):
        """No code should append /chat/completions to base_url for MiniMax."""
        lines_with_chat_completions = [
            line.strip() for line in self.llm_source.splitlines()
            if 'chat/completions' in line and 'minimax' in line.lower()
        ]
        self.assertEqual(len(lines_with_chat_completions), 0,
                         f'Found legacy chat/completions URL appending: {lines_with_chat_completions}')


class TestCoreAIModuleChanges(unittest.TestCase):
    """Unit tests verifying core.ai __init__.py changes."""

    @classmethod
    def setUpClass(cls):
        cls.init_py_path = os.path.join(
            os.path.dirname(__file__), '..', 'bisheng', 'core', 'ai', '__init__.py'
        )
        cls.init_py_path = os.path.normpath(cls.init_py_path)
        with open(cls.init_py_path) as f:
            cls.init_source = f.read()

    def test_minimax_chat_not_imported(self):
        """MiniMaxChat should NOT be imported from langchain_community."""
        self.assertNotIn('MiniMaxChat', self.init_source)

    def test_minimax_chat_not_in_all(self):
        """MiniMaxChat should NOT be in __all__ list."""
        tree = ast.parse(self.init_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == '__all__':
                        if isinstance(node.value, ast.List):
                            items = [
                                elt.value for elt in node.value.elts
                                if isinstance(elt, ast.Constant)
                            ]
                            self.assertNotIn('MiniMaxChat', items)
                            return
        self.fail('Could not find __all__ in __init__.py')

    def test_chat_openai_compatible_in_all(self):
        """ChatOpenAICompatible should be in __all__ list."""
        tree = ast.parse(self.init_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == '__all__':
                        if isinstance(node.value, ast.List):
                            items = [
                                elt.value for elt in node.value.elts
                                if isinstance(elt, ast.Constant)
                            ]
                            self.assertIn('ChatOpenAICompatible', items)
                            return
        self.fail('Could not find __all__ in __init__.py')


class TestEmbeddingModuleConsistency(unittest.TestCase):
    """Unit tests verifying MiniMax embedding uses OpenAI-compatible pattern."""

    @classmethod
    def setUpClass(cls):
        cls.emb_py_path = os.path.join(
            os.path.dirname(__file__), '..', 'bisheng', 'llm', 'domain', 'llm', 'embedding.py'
        )
        cls.emb_py_path = os.path.normpath(cls.emb_py_path)
        with open(cls.emb_py_path) as f:
            cls.emb_source = f.read()

    def test_minimax_embedding_uses_openai_embeddings(self):
        """MiniMax embedding should map to OpenAIEmbeddings."""
        for line in self.emb_source.splitlines():
            if 'MINIMAX' in line and 'client' in line:
                self.assertIn('OpenAIEmbeddings', line)
                return
        self.fail('Could not find MINIMAX entry in embedding _node_type')

    def test_minimax_embedding_uses_openai_params(self):
        """MiniMax embedding should use _get_openai_params."""
        for line in self.emb_source.splitlines():
            if 'MINIMAX' in line and 'params_handler' in line:
                self.assertIn('_get_openai_params', line)
                return
        self.fail('Could not find MINIMAX params_handler in embedding')


class TestFrontendModelData(unittest.TestCase):
    """Unit tests for frontend model configuration data."""

    @classmethod
    def setUpClass(cls):
        cls.data_path = os.path.join(
            os.path.dirname(__file__),
            '../../frontend/platform/public/models/data.json'
        )
        cls.data_path = os.path.normpath(cls.data_path)
        if not os.path.exists(cls.data_path):
            raise unittest.SkipTest('Frontend data.json not available in checkout')
        with open(cls.data_path) as f:
            cls.model_data = json.load(f)

    def test_minimax_models_exist(self):
        """MiniMax models should be present in data.json."""
        self.assertIn('minimax', self.model_data)

    def test_minimax_has_m27_model(self):
        """MiniMax-M2.7 should be listed as an LLM model."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-M2.7', model_names)

    def test_minimax_has_m27_highspeed_model(self):
        """MiniMax-M2.7-highspeed should be listed as an LLM model."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-M2.7-highspeed', model_names)

    def test_minimax_has_m25_model(self):
        """MiniMax-M2.5 should still be listed for backward compatibility."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-M2.5', model_names)

    def test_minimax_has_m25_highspeed_model(self):
        """MiniMax-M2.5-highspeed should still be listed."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-M2.5-highspeed', model_names)

    def test_minimax_has_text01_model(self):
        """MiniMax-Text-01 should still be listed for backward compatibility."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-Text-01', model_names)

    def test_minimax_m27_is_first(self):
        """MiniMax-M2.7 should be the first (default) model."""
        self.assertEqual(self.model_data['minimax'][0]['model_name'], 'MiniMax-M2.7')

    def test_minimax_models_are_llm_type(self):
        """All MiniMax models should be of type 'llm'."""
        for model in self.model_data['minimax']:
            self.assertEqual(model['model_type'], 'llm')

    def test_minimax_model_count(self):
        """MiniMax should have 5 models listed."""
        self.assertEqual(len(self.model_data['minimax']), 5)


class TestFrontendCustomForm(unittest.TestCase):
    """Unit tests for frontend MiniMax provider form configuration."""

    @classmethod
    def setUpClass(cls):
        cls.form_path = os.path.join(
            os.path.dirname(__file__),
            '../../frontend/platform/src/pages/ModelPage/manage/CustomForm.tsx'
        )
        cls.form_path = os.path.normpath(cls.form_path)
        if not os.path.exists(cls.form_path):
            raise unittest.SkipTest('Frontend CustomForm.tsx not available in checkout')
        with open(cls.form_path) as f:
            cls.form_source = f.read()

    def test_minimax_api_base_url(self):
        """Default MiniMax API base should be api.minimax.io/v1."""
        self.assertIn('https://api.minimax.io/v1', self.form_source)

    def test_minimax_not_using_old_api_url(self):
        """Should NOT use old api.minimax.chat/v1 URL."""
        self.assertNotIn('api.minimax.chat/v1', self.form_source)


class TestMiniMaxLLMServerTypeEnum(unittest.TestCase):
    """Unit tests for MiniMax in the LLMServerType enum."""

    @classmethod
    def setUpClass(cls):
        cls.const_path = os.path.join(
            os.path.dirname(__file__), '..', 'bisheng', 'llm', 'domain', 'const.py'
        )
        cls.const_path = os.path.normpath(cls.const_path)
        with open(cls.const_path) as f:
            cls.const_source = f.read()

    def test_minimax_server_type_exists(self):
        """MINIMAX should be defined in LLMServerType enum."""
        self.assertIn("MINIMAX = 'minimax'", self.const_source)


class TestOpenAIParamsFunction(unittest.TestCase):
    """Unit tests for _get_openai_params function behavior."""

    @classmethod
    def setUpClass(cls):
        llm_py_path = os.path.join(
            os.path.dirname(__file__), '..', 'bisheng', 'llm', 'domain', 'llm', 'llm.py'
        )
        llm_py_path = os.path.normpath(llm_py_path)
        with open(llm_py_path) as f:
            source = f.read()

        tree = ast.parse(source)
        funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ('_get_user_kwargs', '_get_openai_params'):
                func_source = ast.get_source_segment(source, node)
                funcs[node.name] = func_source

        combined = funcs['_get_user_kwargs'] + '\n\n' + funcs['_get_openai_params']
        exec_globals = {'json': json}
        exec(compile(combined, '<test>', 'exec'), exec_globals)
        cls._openai_params_fn = staticmethod(exec_globals['_get_openai_params'])

    def test_extracts_api_key(self):
        """Should use openai_api_key from server config."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'test-minimax-key', 'openai_api_base': 'https://api.minimax.io/v1'},
            {}
        )
        self.assertEqual(result['api_key'], 'test-minimax-key')

    def test_extracts_base_url(self):
        """Should use openai_api_base as base_url."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1'},
            {}
        )
        self.assertEqual(result['base_url'], 'https://api.minimax.io/v1')

    def test_strips_trailing_slash(self):
        """Should strip trailing slash from base_url."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1/'},
            {}
        )
        self.assertEqual(result['base_url'], 'https://api.minimax.io/v1')

    def test_stream_usage_true(self):
        """Should set stream_usage=True."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1'},
            {}
        )
        self.assertTrue(result['stream_usage'])

    def test_no_legacy_params(self):
        """Should not produce minimax_api_key or group_id."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1'},
            {}
        )
        self.assertNotIn('minimax_api_key', result)
        self.assertNotIn('minimax_group_id', result)

    def test_preserves_model_name(self):
        """Model name should be preserved."""
        for name in ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M2.5', 'MiniMax-M2.5-highspeed', 'MiniMax-Text-01']:
            result = self._openai_params_fn(
                {'model': name},
                {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1'},
                {}
            )
            self.assertEqual(result['model'], name)

    def test_user_kwargs_applied(self):
        """User advanced kwargs should be merged."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5', 'temperature': 0.7},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1'},
            {'user_kwargs': json.dumps({'max_tokens': 4096})}
        )
        self.assertEqual(result['temperature'], 0.7)
        self.assertEqual(result['model'], 'MiniMax-M2.5')

    def test_empty_key_fallback(self):
        """Should fall back to 'empty' when API key is empty."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': '', 'openai_api_base': 'https://api.minimax.io/v1'},
            {}
        )
        self.assertEqual(result['api_key'], 'empty')

    def test_proxy_passthrough(self):
        """Should pass through openai_proxy if configured."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1',
             'openai_proxy': 'http://proxy:8080'},
            {}
        )
        self.assertEqual(result['openai_proxy'], 'http://proxy:8080')

    def test_no_url_appending(self):
        """Should NOT append /chat/completions to the URL."""
        result = self._openai_params_fn(
            {'model': 'MiniMax-M2.5'},
            {'openai_api_key': 'key', 'openai_api_base': 'https://api.minimax.io/v1'},
            {}
        )
        self.assertNotIn('/chat/completions', result['base_url'])


class TestMiniMaxIntegration(unittest.TestCase):
    """Integration tests for MiniMax provider (require MINIMAX_API_KEY)."""

    @unittest.skipUnless(
        os.environ.get('MINIMAX_API_KEY'),
        'MINIMAX_API_KEY not set'
    )
    def test_minimax_m27_chat_completion(self):
        """Test actual chat completion with MiniMax-M2.7 via OpenAI-compatible API."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model='MiniMax-M2.7',
            api_key=os.environ['MINIMAX_API_KEY'],
            base_url='https://api.minimax.io/v1',
            temperature=0.1,
            max_tokens=64,
        )
        response = llm.invoke('Say hello in one word.')
        self.assertIsNotNone(response.content)
        self.assertTrue(len(response.content) > 0)

    @unittest.skipUnless(
        os.environ.get('MINIMAX_API_KEY'),
        'MINIMAX_API_KEY not set'
    )
    def test_minimax_m27_highspeed_chat_completion(self):
        """Test actual chat completion with MiniMax-M2.7-highspeed."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model='MiniMax-M2.7-highspeed',
            api_key=os.environ['MINIMAX_API_KEY'],
            base_url='https://api.minimax.io/v1',
            temperature=0.1,
            max_tokens=64,
        )
        response = llm.invoke('Say hello in one word.')
        self.assertIsNotNone(response.content)
        self.assertTrue(len(response.content) > 0)

    @unittest.skipUnless(
        os.environ.get('MINIMAX_API_KEY'),
        'MINIMAX_API_KEY not set'
    )
    def test_minimax_m27_streaming(self):
        """Test streaming chat completion with MiniMax-M2.7."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model='MiniMax-M2.7',
            api_key=os.environ['MINIMAX_API_KEY'],
            base_url='https://api.minimax.io/v1',
            temperature=0.1,
            max_tokens=64,
            streaming=True,
        )
        chunks = list(llm.stream('Say hello in one word.'))
        self.assertTrue(len(chunks) > 0)
        full_content = ''.join(c.content for c in chunks)
        self.assertTrue(len(full_content) > 0)

    @unittest.skipUnless(
        os.environ.get('MINIMAX_API_KEY'),
        'MINIMAX_API_KEY not set'
    )
    def test_minimax_m25_chat_completion(self):
        """Test actual chat completion with MiniMax-M2.5 via OpenAI-compatible API."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model='MiniMax-M2.5',
            api_key=os.environ['MINIMAX_API_KEY'],
            base_url='https://api.minimax.io/v1',
            temperature=0.1,
            max_tokens=64,
        )
        response = llm.invoke('Say hello in one word.')
        self.assertIsNotNone(response.content)
        self.assertTrue(len(response.content) > 0)


if __name__ == '__main__':
    unittest.main()
