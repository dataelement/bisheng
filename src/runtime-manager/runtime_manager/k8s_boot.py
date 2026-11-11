"""Resolve the stable proxy Service in the control plane before Manager starts.

Application Pods keep their existing no-DNS policy. No address registry or new
per-operation state is introduced; Kubernetes Service fronts Egress replicas.
"""

import ipaddress
import os
import socket
import time


def resolve_proxy(value, *, timeout=120, resolver=socket.getaddrinfo, sleep=time.sleep):
    host, separator, port = value.rpartition(":")
    if not separator or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("egress_service_address_invalid")
    host = host.strip("[]")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        deadline = time.monotonic() + timeout
        while True:
            try:
                addresses = resolver(host, int(port), type=socket.SOCK_STREAM)
                address = ipaddress.ip_address(addresses[0][4][0])
                break
            except (socket.gaierror, IndexError):
                if time.monotonic() >= deadline:
                    raise ValueError("egress_service_resolution_timeout") from None
                sleep(1)
    if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_link_local:
        raise ValueError("egress_service_address_refused")
    return f"[{address}]:{port}" if address.version == 6 else f"{address}:{port}"


def main():
    os.environ["RTM_EGRESS_PROXY"] = resolve_proxy(
        os.environ["RTM_EGRESS_PROXY"], timeout=int(os.getenv("RTM_EGRESS_DNS_TIMEOUT", "120"))
    )
    import uvicorn

    uvicorn.run("runtime_manager.main:app", host="0.0.0.0", port=int(os.getenv("RTM_PORT", "8091")), access_log=False)


if __name__ == "__main__":
    main()
