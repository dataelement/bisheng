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
        client_params = values.copy()
        if not values.get('client'):
            values['client'] = openai.AzureOpenAI(**client_params).images
        if not values.get('async_client'):
            values['async_client'] = openai.AsyncAzureOpenAI(**client_params).images
        return values

    @property
    def _llm_type(self) -> str:
        return 'azure-openai-chat'
