"""Offline URL, origin and complete DNS-answer policy contracts (AC-07/08/12)."""

import importlib
import socket

import pytest


def test_policy_module_is_available():
    assert importlib.util.find_spec("bisheng_langchain.utils.egress_policy") is not None


@pytest.fixture
def policy_module():
    return importlib.import_module("bisheng_langchain.utils.egress_policy")


def answers(*ips):
    return [
        (
            socket.AF_INET6 if ":" in ip else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (ip, 443, 0, 0) if ":" in ip else (ip, 443),
        )
        for ip in ips
    ]


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not access network DNS")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def test_private_origin_configuration_is_not_available(policy_module):
    assert not hasattr(policy_module, "EgressPolicy")
    assert not hasattr(policy_module, "normalize_origin")


def test_resolver_rejects_legacy_policy_argument(policy_module):
    with pytest.raises(TypeError, match="policy"):
        policy_module.resolve_destination("https://8.8.8.8", policy=object())


def test_parse_preserves_url_and_canonicalizes_identity(policy_module):
    url = "HTTPS://BÜCHER.example:8443/a?q=secret"
    target = policy_module.parse_destination(url)
    assert (target.url, target.scheme, target.hostname, target.port, target.origin) == (
        url,
        "https",
        "xn--bcher-kva.example",
        8443,
        "https://xn--bcher-kva.example:8443",
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "//example.com",
        "https://",
        "https://user:secret@example.com",
        "https://@example.com",
        "https://example.com#fragment",
        "https://example.com#",
        "https://example.com\\evil",
        "https://example.com/\nsecret",
        " https://example.com",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:",
        "https://example.com:+443",
        "https://%65xample.com",
        "http://[fe80::1%25eth0]",
        "http://127.1",
        "http://2130706433",
        "http://0177.0.0.1",
        "http://0x7f000001",
        "https://example.com.",
        "https://a..example",
        "https://*.example",
        "http://[::1]suffix",
        "https://foo_bar.example",
        "https://\uff45xample.com",  # fullwidth e: reject lossy IDNA mapping
    ],
)
def test_ambiguous_destinations_rejected(policy_module, url):
    with pytest.raises(policy_module.DestinationDenied) as exc:
        policy_module.parse_destination(url)
    assert url not in str(exc.value)


@pytest.mark.parametrize(
    "ip",
    [
        "8.8.8.8",
        "1.1.1.1",
        "2606:4700:4700::1111",
    ],
)
def test_public_literals_skip_dns(policy_module, ip):
    host = f"[{ip}]" if ":" in ip else ip
    target = policy_module.resolve_destination(f"https://{host}/secret?q=credential")
    assert target.ips == (ip,)
    assert target.hostname == ip
    assert target.port == 443


@pytest.mark.parametrize(
    "ip",
    [
        "0.0.0.0",
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "169.254.170.2",
        "100.100.100.200",
        "168.63.129.16",
        "100.64.0.1",
        "192.0.0.9",
        "192.0.2.1",
        "198.18.0.1",
        "198.51.100.1",
        "203.0.113.1",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "::",
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:8.8.8.8",
        "::ffff:127.0.0.1",
        "::8.8.8.8",
        "64:ff9b::808:808",
        "64:ff9b:1::808:808",
        "2002:808:808::1",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
        "2001:20::1",
        "2001:10::1",
        "2001:4860:1:2:0:5efe:808:808",
    ],
)
def test_forbidden_ip_literals_are_unconditionally_denied(policy_module, ip):
    host = f"[{ip}]" if ":" in ip else ip
    with pytest.raises(policy_module.DestinationDenied):
        policy_module.resolve_destination(f"https://{host}")


@pytest.mark.parametrize("ip", ["10.0.0.1", "172.31.255.254", "192.168.0.1", "fd12::1"])
def test_private_dns_answers_are_unconditionally_denied(policy_module, ip):
    def resolver(*args, **kwargs):
        return answers(ip)

    with pytest.raises(policy_module.DestinationDenied):
        policy_module.resolve_destination("https://INTERNAL.example:8443/path", resolver=resolver)


def test_resolver_freezes_all_addresses_and_deduplicates(policy_module, monkeypatch):
    calls = []

    def resolver(host, port, *, family, type):
        calls.append((host, port, family, type))
        return answers("8.8.8.8", "2606:4700:4700::1111", "8.8.8.8")

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    target = policy_module.resolve_destination("https://EXAMPLE.com/path")
    assert target.ips == ("8.8.8.8", "2606:4700:4700::1111")
    assert calls == [("example.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)]


@pytest.mark.parametrize("ips", [(), ("8.8.8.8", "127.0.0.1"), ("8.8.8.8", "10.0.0.1"), ("not-an-ip",)])
def test_entire_dns_answer_must_be_allowed(policy_module, ips):
    with pytest.raises(policy_module.DestinationDenied):
        policy_module.resolve_destination("https://example.com", resolver=lambda *a, **kw: answers(*ips))


def test_dns_errors_are_sanitized(policy_module):
    def resolver(*args, **kwargs):
        raise socket.gaierror("secret credential internal details")

    with pytest.raises(policy_module.DestinationDenied) as exc:
        policy_module.resolve_destination("https://example.com?q=secret", resolver=resolver)
    assert "secret" not in str(exc.value)
    assert exc.value.__suppress_context__
