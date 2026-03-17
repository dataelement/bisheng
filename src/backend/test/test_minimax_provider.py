"""Tests for MiniMax provider upgrade to OpenAI-compatible API (M2.5 support).

These tests verify the MiniMax provider changes:
1. Backend: MiniMax uses ChatOpenAICompatible (OpenAI-compatible) instead of legacy MiniMaxChat
2. Frontend: Model data includes M2.5 models, default API URL updated
"""
import ast
import json
import os
import unittest

# Paths relative to this test file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_PY = os.path.join(BASE_DIR, '..', 'bisheng', 'llm', 'domain', 'llm', 'llm.py')
AI_INIT = os.path.join(BASE_DIR, '..', 'bisheng', 'core', 'ai', '__init__.py')
DATA_JSON = os.path.join(BASE_DIR, '..', '..', 'frontend', 'platform', 'public', 'models', 'data.json')
CUSTOM_FORM_TSX = os.path.join(BASE_DIR, '..', '..', 'frontend', 'platform', 'src', 'pages',
                                'ModelPage', 'manage', 'CustomForm.tsx')
EMBEDDING_PY = os.path.join(BASE_DIR, '..', 'bisheng', 'llm', 'domain', 'llm', 'embedding.py')
CONST_PY = os.path.join(BASE_DIR, '..', 'bisheng', 'llm', 'domain', 'const.py')
ADVANCED_PARAMS_TS = os.path.join(BASE_DIR, '..', '..', 'frontend', 'platform', 'src', 'util',
                                   'advancedParamsTemplates.ts')


class TestMiniMaxBackendConfig(unittest.TestCase):
    """Unit tests for MiniMax backend provider configuration via source analysis."""

    def setUp(self):
        with open(os.path.normpath(LLM_PY)) as f:
            self.llm_source = f.read()

    def test_minimax_uses_chat_openai_compatible(self):
        """MiniMax factory entry should use ChatOpenAICompatible client."""
        self.assertIn(
            "LLMServerType.MINIMAX.value: {'client': ChatOpenAICompatible",
            self.llm_source
        )

    def test_minimax_uses_openai_params_handler(self):
        """MiniMax factory entry should use _get_openai_params handler."""
        self.assertIn(
            "'params_handler': _get_openai_params}",
            self.llm_source.split('MINIMAX')[1].split('\n')[0]
        )

    def test_no_legacy_minimax_params_handler(self):
        """Legacy _get_minimax_params function should be removed."""
        self.assertNotIn('def _get_minimax_params', self.llm_source)

    def test_no_minimax_chat_import(self):
        """MiniMaxChat should not be imported in llm.py."""
        self.assertNotIn('MiniMaxChat', self.llm_source)

    def test_chat_openai_compatible_imported(self):
        """ChatOpenAICompatible should be imported in llm.py."""
        self.assertIn('ChatOpenAICompatible', self.llm_source)

    def test_minimax_server_type_defined(self):
        """MiniMax should be defined as a valid server type in const.py."""
        with open(os.path.normpath(CONST_PY)) as f:
            const_source = f.read()
        self.assertIn("MINIMAX = 'minimax'", const_source)

    def test_web_search_support_preserved(self):
        """parse_kwargs should still handle web_search for MINIMAX."""
        self.assertIn('LLMServerType.MINIMAX.value', self.llm_source)
        self.assertIn("'type': 'web_search'", self.llm_source)

    def test_minimax_chat_removed_from_core_ai(self):
        """Legacy MiniMaxChat should be removed from core.ai (no longer needed)."""
        with open(os.path.normpath(AI_INIT)) as f:
            ai_init_source = f.read()
        self.assertNotIn('MiniMaxChat', ai_init_source)

    def test_minimax_embedding_uses_openai(self):
        """MiniMax embedding should use OpenAIEmbeddings with _get_openai_params."""
        with open(os.path.normpath(EMBEDDING_PY)) as f:
            embedding_source = f.read()
        self.assertIn('LLMServerType.MINIMAX.value', embedding_source)
        self.assertIn('OpenAIEmbeddings', embedding_source)


class TestMiniMaxModelData(unittest.TestCase):
    """Unit tests for MiniMax model template data."""

    def setUp(self):
        with open(os.path.normpath(DATA_JSON)) as f:
            self.model_data = json.load(f)

    def test_minimax_key_exists(self):
        """MiniMax provider should be present in data.json."""
        self.assertIn('minimax', self.model_data)

    def test_minimax_has_m25_model(self):
        """MiniMax-M2.5 should be listed as an LLM model."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-M2.5', model_names)

    def test_minimax_has_m25_highspeed_model(self):
        """MiniMax-M2.5-highspeed should be listed as an LLM model."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-M2.5-highspeed', model_names)

    def test_minimax_has_text01_model(self):
        """MiniMax-Text-01 should still be listed for backward compatibility."""
        model_names = [m['model_name'] for m in self.model_data['minimax']]
        self.assertIn('MiniMax-Text-01', model_names)

    def test_minimax_m25_is_first(self):
        """MiniMax-M2.5 should be the first (default) model."""
        self.assertEqual(self.model_data['minimax'][0]['model_name'], 'MiniMax-M2.5')

    def test_minimax_models_are_llm_type(self):
        """All MiniMax models should be of type 'llm'."""
        for model in self.model_data['minimax']:
            self.assertEqual(model['model_type'], 'llm')

    def test_minimax_model_count(self):
        """MiniMax should have 3 models listed."""
        self.assertEqual(len(self.model_data['minimax']), 3)

    def test_data_json_is_valid_json(self):
        """data.json should be valid JSON with all expected providers."""
        expected_providers = [
            'openai', 'azure_openai', 'qwen', 'deepseek', 'minimax',
            'volcengine', 'silicon',
        ]
        for provider in expected_providers:
            self.assertIn(provider, self.model_data)


class TestMiniMaxFrontendConfig(unittest.TestCase):
    """Unit tests for MiniMax frontend configuration."""

    def setUp(self):
        with open(os.path.normpath(CUSTOM_FORM_TSX)) as f:
            self.form_source = f.read()

    def test_minimax_default_api_base_url(self):
        """Default API base URL should be https://api.minimax.io/v1 (new OpenAI-compatible API)."""
        self.assertIn('https://api.minimax.io/v1', self.form_source)

    def test_no_legacy_api_url(self):
        """Legacy API URL api.minimax.chat should not be present."""
        self.assertNotIn('api.minimax.chat', self.form_source)

    def test_minimax_requires_api_key(self):
        """MiniMax provider form should require an API key."""
        # Find minimax section and check for API key field
        minimax_idx = self.form_source.index('minimax:')
        section_end = self.form_source.index('],', minimax_idx) + 2
        minimax_section = self.form_source[minimax_idx:section_end]
        self.assertIn('openai_api_key', minimax_section)

    def test_minimax_requires_api_base(self):
        """MiniMax provider form should require an API base URL."""
        minimax_idx = self.form_source.index('minimax:')
        section_end = self.form_source.index('],', minimax_idx) + 2
        minimax_section = self.form_source[minimax_idx:section_end]
        self.assertIn('openai_api_base', minimax_section)


class TestMiniMaxAdvancedParams(unittest.TestCase):
    """Unit tests for MiniMax advanced parameters template."""

    def setUp(self):
        with open(os.path.normpath(ADVANCED_PARAMS_TS)) as f:
            self.template_source = f.read()

    def test_minimax_llm_template_exists(self):
        """minimax-llm template should exist in advancedParamsTemplates."""
        self.assertIn("'minimax-llm'", self.template_source)

    def test_minimax_mapping_exists(self):
        """minimax should be mapped to minimax-llm template."""
        self.assertIn("'minimax': 'minimax-llm'", self.template_source)

    def test_minimax_embedding_template_exists(self):
        """minimax-embedding template should exist."""
        self.assertIn("'minimax-embedding'", self.template_source)


class TestMiniMaxProviderLinks(unittest.TestCase):
    """Unit tests for MiniMax provider documentation links."""

    def setUp(self):
        use_link_path = os.path.join(
            BASE_DIR, '..', '..', 'frontend', 'platform', 'src', 'pages',
            'ModelPage', 'manage', 'useLink.ts'
        )
        with open(os.path.normpath(use_link_path)) as f:
            self.links_source = f.read()

    def test_minimax_api_key_url(self):
        """MiniMax should have an API key URL."""
        minimax_idx = self.links_source.index('minimax:')
        section_end = self.links_source.index('},', minimax_idx) + 2
        minimax_section = self.links_source[minimax_idx:section_end]
        self.assertIn('apiKeyUrl', minimax_section)
        self.assertIn('platform.minimaxi.com', minimax_section)

    def test_minimax_model_url(self):
        """MiniMax should have a model documentation URL."""
        minimax_idx = self.links_source.index('minimax:')
        section_end = self.links_source.index('},', minimax_idx) + 2
        minimax_section = self.links_source[minimax_idx:section_end]
        self.assertIn('modelUrl', minimax_section)


class TestMiniMaxIntegration(unittest.TestCase):
    """Integration tests for MiniMax provider (require MINIMAX_API_KEY)."""

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

    @unittest.skipUnless(
        os.environ.get('MINIMAX_API_KEY'),
        'MINIMAX_API_KEY not set'
    )
    def test_minimax_m25_highspeed_chat_completion(self):
        """Test actual chat completion with MiniMax-M2.5-highspeed."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model='MiniMax-M2.5-highspeed',
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
    def test_minimax_m25_streaming(self):
        """Test streaming chat completion with MiniMax-M2.5."""
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model='MiniMax-M2.5',
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


if __name__ == '__main__':
    unittest.main()
