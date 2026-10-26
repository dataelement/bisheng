"""Seal resumable execution secrets with a deployment-owned key."""

import json

from cryptography.fernet import Fernet, InvalidToken

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json
from bisheng.common.services.config_service import settings


def cipher():
    try:
        return Fernet(settings.app_runtime.runtime_payload_key.encode())
    except (ValueError, TypeError):
        raise RuntimeConflict("runtime_payload_key_required") from None


def seal(environment):
    return cipher().encrypt(canonical_json(environment)).decode()


def unseal(value):
    try:
        return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError):
        raise RuntimeConflict("runtime_payload_unreadable") from None
