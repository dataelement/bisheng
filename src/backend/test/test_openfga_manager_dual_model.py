"""Unit tests for FGAManager dual-model bootstrap (F013 T04).

Verifies that legacy_model_id is forwarded to FGAClient only when
dual_model_mode is enabled in OpenFGAConf.
"""

from unittest.mock import patch, AsyncMock

import pytest

from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.openfga.client import FGAClient


def test_fga_client_legacy_model_id_default_none():
    """FGAClient construction without legacy_model_id leaves the property None."""
    client = FGAClient(
        api_url='http://localhost:8080',
        store_id='store-1',
        model_id='model-1',
    )
    assert client.legacy_model_id is None


def test_fga_client_legacy_model_id_set_when_provided():
    client = FGAClient(
        api_url='http://localhost:8080',
        store_id='store-1',
        model_id='model-1',
        legacy_model_id='legacy-xyz',
    )
    assert client.legacy_model_id == 'legacy-xyz'
    assert client.model_id == 'model-1'  # primary unchanged


@pytest.mark.asyncio
async def test_manager_passes_legacy_when_dual_mode_true():
    """When dual_model_mode=true, FGAManager must propagate legacy_model_id."""
    from bisheng.core.openfga.manager import FGAManager

    config = OpenFGAConf(
        store_id='store-1',
        model_id='model-1',
        dual_model_mode=True,
        legacy_model_id='legacy-xyz',
    )
    mgr = FGAManager(config)

    with patch('bisheng.core.openfga.manager.httpx.AsyncClient') as mock_http_cls, \
            patch('bisheng.core.openfga.manager.FGAClient') as mock_client_cls:
        mock_http = AsyncMock()
        mock_http_cls.return_value = mock_http
        mock_http.aclose = AsyncMock()

        await mgr._async_initialize()

        mock_client_cls.assert_called_once()
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs['legacy_model_id'] == 'legacy-xyz'
        assert kwargs['model_id'] == 'model-1'


@pytest.mark.asyncio
async def test_manager_ignores_legacy_when_dual_mode_false():
    """Even with legacy_model_id set, dual_model_mode=false makes manager forward None."""
    from bisheng.core.openfga.manager import FGAManager

    config = OpenFGAConf(
        store_id='store-1',
        model_id='model-1',
        dual_model_mode=False,
        legacy_model_id='legacy-xyz',  # set but should be ignored
    )
    mgr = FGAManager(config)

    with patch('bisheng.core.openfga.manager.httpx.AsyncClient') as mock_http_cls, \
            patch('bisheng.core.openfga.manager.FGAClient') as mock_client_cls:
        mock_http = AsyncMock()
        mock_http_cls.return_value = mock_http
        mock_http.aclose = AsyncMock()

        await mgr._async_initialize()

        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs['legacy_model_id'] is None
