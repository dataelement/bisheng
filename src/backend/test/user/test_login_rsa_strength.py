"""Public login keys must use modern modulus size and atomic cache publication."""

from unittest.mock import Mock

import pytest
import rsa

pytestmark = pytest.mark.mock


def test_login_key_strength_and_cache_publication(monkeypatch):
    from bisheng.user.api import user as endpoints

    public, private = rsa.newkeys(2048)
    cache = Mock()
    cache.get.return_value = None
    cache.setNx.return_value = True
    generate = Mock(return_value=(public, private))
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    monkeypatch.setattr(endpoints.rsa, "newkeys", generate)
    result = endpoints.get_rsa_publish_key()
    generate.assert_called_once_with(2048)
    # The winning keypair itself is published atomically, never a scalar sentinel.
    assert cache.setNx.call_args.args[1] == (public, private)
    assert result.data["public_key"] == public.save_pkcs1().decode()
    cache.set.assert_not_called()


def test_racing_request_reads_the_winning_keypair(monkeypatch):
    from bisheng.user.api import user as endpoints

    public, private = rsa.newkeys(2048)
    losing_public, losing_private = rsa.newkeys(2048)
    cache = Mock()
    cache.get.side_effect = [None, (public, private)]
    cache.setNx.return_value = False
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    monkeypatch.setattr(endpoints.rsa, "newkeys", Mock(return_value=(losing_public, losing_private)))
    result = endpoints.get_rsa_publish_key()
    assert result.data["public_key"] == public.save_pkcs1().decode()
    cache.set.assert_not_called()


def test_login_reuses_only_current_versioned_key(monkeypatch):
    from bisheng.user.api import user as endpoints

    public, private = rsa.newkeys(2048)
    cache = Mock()
    cache.get.return_value = (public, private)
    generate = Mock(side_effect=AssertionError("existing strong key must be reused"))
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    monkeypatch.setattr(endpoints.rsa, "newkeys", generate)
    assert endpoints.RSA_KEY != "rsa_"
    result = endpoints.get_rsa_publish_key()
    assert result.data["public_key"] == public.save_pkcs1().decode()
    generate.assert_not_called()
    cache.setNx.assert_not_called()


@pytest.mark.parametrize("pair", [1, (), ("public", "private")])
def test_invalid_cached_pair_fails_closed(monkeypatch, pair):
    from fastapi import HTTPException

    from bisheng.user.api import user as endpoints

    cache = Mock()
    cache.get.return_value = pair
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    with pytest.raises(HTTPException) as error:
        endpoints.get_rsa_publish_key()
    assert error.value.status_code == 503
    cache.setNx.assert_not_called()
    cache.set.assert_not_called()


def test_publication_uses_versioned_key_and_expiration(monkeypatch):
    from bisheng.user.api import user as endpoints
    from bisheng.user.domain.services import user as service
    from bisheng.utils.constants import RSA_KEY

    public, private = rsa.newkeys(2048)
    cache = Mock()
    cache.get.return_value = None
    cache.setNx.return_value = True
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    monkeypatch.setattr(endpoints.rsa, "newkeys", Mock(return_value=(public, private)))
    endpoints.get_rsa_publish_key()
    assert endpoints.RSA_KEY == service.RSA_KEY == RSA_KEY == "rsa_login_2048_v2"
    cache.get.assert_called_once_with(RSA_KEY)
    cache.setNx.assert_called_once_with(RSA_KEY, (public, private), expiration=3600)
