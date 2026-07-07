import unittest

from bisheng.llm.domain.services.llm import LLMService


class TestStripConfigWhitespace(unittest.TestCase):
    def test_api_key_trailing_whitespace_stripped(self):
        config = {'openai_api_key': 'sk-xxx ', 'api_key': ' sk-yyy\n'}
        result = LLMService.strip_config_whitespace(config)
        self.assertEqual(result['openai_api_key'], 'sk-xxx')
        self.assertEqual(result['api_key'], 'sk-yyy')

    def test_url_and_endpoint_fields_stripped(self):
        config = {
            'openai_api_base': ' https://api.openai.com/v1 ',
            'base_url': 'https://example.com/v1\t',
            'azure_endpoint': ' https://xx.openai.azure.com',
            'openai_proxy': ' http://127.0.0.1:7890 ',
        }
        result = LLMService.strip_config_whitespace(config)
        self.assertEqual(result['openai_api_base'], 'https://api.openai.com/v1')
        self.assertEqual(result['base_url'], 'https://example.com/v1')
        self.assertEqual(result['azure_endpoint'], 'https://xx.openai.azure.com')
        self.assertEqual(result['openai_proxy'], 'http://127.0.0.1:7890')

    def test_nested_config_stripped(self):
        config = {'inner': {'api_key': 'sk-xxx '}}
        result = LLMService.strip_config_whitespace(config)
        self.assertEqual(result['inner']['api_key'], 'sk-xxx')

    def test_other_fields_untouched(self):
        config = {'description': ' keep me ', 'streaming': True, 'max_tokens': 4096, 'voice': None}
        result = LLMService.strip_config_whitespace(config)
        self.assertEqual(result['description'], ' keep me ')
        self.assertEqual(result['streaming'], True)
        self.assertEqual(result['max_tokens'], 4096)
        self.assertIsNone(result['voice'])

    def test_none_config(self):
        self.assertIsNone(LLMService.strip_config_whitespace(None))
