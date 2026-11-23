"""One-time data verification public key publication; named ConfigMaps only.

The material issuer seed is not published: existing HMAC-scoped material
delegations register their per-workload keys with Backend already.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime_manager.k8s_config import validate_namespace


def public_document(seed):
    if not isinstance(seed, bytes) or len(seed) != 32:
        raise ValueError("data_seed_invalid")
    key = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    return {"data_v1": key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()}


def publish(client, namespace, name, installation, document):
    validate_namespace(namespace)
    validate_namespace(name)
    path = f"/api/v1/namespaces/{namespace}/configmaps/{name}"
    response = client.get(path)
    response.raise_for_status()
    obj = response.json()
    if obj.get("metadata", {}).get("labels", {}).get("runtime.bisheng.io/installation") != installation:
        raise ValueError("public_key_configmap_ownership_mismatch")
    desired = {"public-keys.json": json.dumps(document, sort_keys=True, separators=(",", ":"))}
    current = obj.get("data") or {}
    if current == desired:
        return
    if current:
        raise ValueError("public_key_configmap_content_mismatch")
    response = client.patch(
        path,
        json={"metadata": {"resourceVersion": obj["metadata"]["resourceVersion"]}, "data": desired},
        headers={"Content-Type": "application/merge-patch+json"},
    )
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--configmap", required=True)
    parser.add_argument("--installation", required=True)
    args = parser.parse_args()
    account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    try:
        document = public_document(Path(args.seed).read_bytes())
        with httpx.Client(
            base_url="https://kubernetes.default.svc",
            verify=str(account / "ca.crt"),
            timeout=10,
            headers={"Authorization": "Bearer " + (account / "token").read_text().strip()},
            follow_redirects=False,
            trust_env=False,
        ) as client:
            publish(client, args.namespace, args.configmap, args.installation, document)
    except (OSError, ValueError, httpx.HTTPError):
        raise SystemExit(
            "Data public key initialization failed; check named ConfigMap ownership, key consistency and Job permissions"
        ) from None


if __name__ == "__main__":
    main()
