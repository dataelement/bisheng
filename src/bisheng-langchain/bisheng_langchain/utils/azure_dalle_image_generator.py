import os
from typing import Callable, Dict, Optional, Union

import openai
from langchain_community.utilities.dalle_image_generator import DallEAPIWrapper
from pydantic import Field, SecretStr, model_validator
from langchain_core.utils import convert_to_secret_str, get_from_dict_or_env


class AzureDallEWrapper(DallEAPIWrapper):
    """`Azure OpenAI` Embeddings API.

    To use, you should have the
    environment variable ``AZURE_OPENAI_API_KEY`` set with your API key or pass it
    as a named parameter to the constructor.

    Example:
        .. code-block:: python

            from langchain_openai import AzureOpenAIEmbeddings

            openai = AzureOpenAIEmbeddings(model="text-embedding-3-large")
    """

    azure_endpoint: Union[str, None] = None
    """Your Azure endpoint, including the resource.

        Automatically inferred from env var `AZURE_OPENAI_ENDPOINT` if not provided.

        Example: `https://example-resource.azure.openai.com/`
    """
    deployment: Optional[str] = Field(default=None, alias='azure_deployment')
    """A model deployment.

        If given sets the base client URL to include `/deployments/{azure_deployment}`.
        Note: this means you won't be able to use non-deployment endpoints.
    """
    openai_api_key: Optional[SecretStr] = Field(default=None, alias='api_key')
    """Automatically inferred from env var `AZURE_OPENAI_API_KEY` if not provided."""
    azure_ad_token: Optional[SecretStr] = None
    """Your Azure Active Directory token.

        Automatically inferred from env var `AZURE_OPENAI_AD_TOKEN` if not provided.

        For more:
        https://www.microsoft.com/en-us/security/business/identity-access/microsoft-entra-id.
    """
    azure_ad_token_provider: Union[Callable[[], str], None] = None
    """A function that returns an Azure Active Directory token.

        Will be invoked on every request.
    """
    openai_api_version: Optional[str] = Field(default=None, alias='api_version')
    """Automatically inferred from env var `OPENAI_API_VERSION` if not provided."""
    validate_base_url: bool = True
    chunk_size: int = 2048
    """Maximum number of texts to embed in each batch"""

    @model_validator(mode='before')
    @classmethod
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        # Check OPENAI_KEY for backwards compatibility.
        # TODO: Remove OPENAI_API_KEY support to avoid possible conflict when using
        # other forms of azure credentials.
        openai_api_key = (values['openai_api_key'] or os.getenv('AZURE_OPENAI_API_KEY')
                          or os.getenv('OPENAI_API_KEY'))
        values['openai_api_key'] = (convert_to_secret_str(openai_api_key)
                                    if openai_api_key else None)
        values['openai_api_base'] = (values['openai_api_base'] if 'openai_api_base' in values else
                                     os.getenv('OPENAI_API_BASE'))
        values['openai_api_version'] = values['openai_api_version'] or os.getenv(
            'OPENAI_API_VERSION', default='2023-05-15')
        values['openai_api_type'] = get_from_dict_or_env(values,
                                                         'openai_api_type',
                                                         'OPENAI_API_TYPE',
                                                         default='azure')
        values['openai_organization'] = (values['openai_organization']
                                         or os.getenv('OPENAI_ORG_ID')
                                         or os.getenv('OPENAI_ORGANIZATION'))
        values['openai_proxy'] = get_from_dict_or_env(values,
                                                      'openai_proxy',
                                                      'OPENAI_PROXY',
                                                      default='')
        values['azure_endpoint'] = values['azure_endpoint'] or os.getenv('AZURE_OPENAI_ENDPOINT')
        azure_ad_token = values['azure_ad_token'] or os.getenv('AZURE_OPENAI_AD_TOKEN')
        values['azure_ad_token'] = (convert_to_secret_str(azure_ad_token)
                                    if azure_ad_token else None)
        # For backwards compatibility. Before openai v1, no distinction was made
        # between azure_endpoint and base_url (openai_api_base).
        openai_api_base = values['openai_api_base']
        if openai_api_base and values['validate_base_url']:
            if '/openai' not in openai_api_base:
                values['openai_api_base'] += '/openai'
                raise ValueError('As of openai>=1.0.0, Azure endpoints should be specified via '
                                 'the `azure_endpoint` param not `openai_api_base` '
                                 '(or alias `base_url`). ')
            if values['deployment']:
                raise ValueError('As of openai>=1.0.0, if `deployment` (or alias '
                                 '`azure_deployment`) is specified then '
                                 '`openai_api_base` (or alias `base_url`) should not be. '
                                 'Instead use `deployment` (or alias `azure_deployment`) '
                                 'and `azure_endpoint`.')
        client_params = {
            'api_version':
            values['openai_api_version'],
            'azure_endpoint':
            values['azure_endpoint'],
            'azure_deployment':
            values['deployment'],
            'api_key':
            (values['openai_api_key'].get_secret_value() if values['openai_api_key'] else None),
            'azure_ad_token':
            (values['azure_ad_token'].get_secret_value() if values['azure_ad_token'] else None),
            'azure_ad_token_provider':
            values['azure_ad_token_provider'],
            'organization':
            values['openai_organization'],
            'base_url':
            values['openai_api_base'],
            'timeout':
            values['request_timeout'],
            'max_retries':
            values['max_retries'],
            'default_headers':
            values['default_headers'],
            'default_query':
            values['default_query'],
        }
        if not values.get('client'):
            values['client'] = openai.AzureOpenAI(**client_params).images
        if not values.get('async_client'):
            values['async_client'] = openai.AsyncAzureOpenAI(**client_params).images
        return values

    @property
    def _llm_type(self) -> str:
        return 'azure-openai-chat'
