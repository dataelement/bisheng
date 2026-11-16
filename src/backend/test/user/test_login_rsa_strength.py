"""Public login keys must use modern modulus size and atomic cache publication."""

from unittest.mock import Mock

import rsa


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
