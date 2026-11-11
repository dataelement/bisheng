"""Trusted release-bundled official catalog seed. Not an API management identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeProfile, RuntimeProfileDefault
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest


def load_official_catalog(root):
    try:
        root = Path(root)
        raw = (root / "catalog.json").read_bytes()
        lock = json.loads((root / "catalog.lock.json").read_text())
        if (
            len(raw) > 4 * 1024 * 1024
            or lock.get("schema_version") != 1
            or not isinstance(lock.get("release"), str)
            or not lock["release"]
            or hashlib.sha256(raw).hexdigest() != lock.get("catalog_sha256")
        ):
            raise ValueError()
        document = json.loads(raw)
        profiles = [RuntimeProfileDefinition.model_validate(value) for value in document["profiles"]]
        if not profiles or any(not value.official for value in profiles):
            raise ValueError()
        identities = [f"{value.code}@{value.revision}" for value in profiles]
        if len(identities) != len(set(identities)) or not isinstance(document.get("defaults"), dict):
            raise ValueError()
        for language, reference in document["defaults"].items():
            if reference not in identities or profiles[identities.index(reference)].language != language:
                raise ValueError()
        return lock, profiles, document["defaults"]
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise RuntimeConflict("official_catalog_invalid") from None


async def seed_official_catalog(root, *, repository=None):
    lock, definitions, defaults = load_official_catalog(root)
    repo = repository or RuntimeDeliveryRepository()
    selected = {}
    async with repo.transaction():
        for definition in definitions:
            body = definition.model_dump(mode="json")
            digest = content_digest(body)
            existing = await repo.find(RuntimeProfile, code=definition.code, revision=definition.revision, lock=True)
            if existing:
                row = existing[0]
                if row.content_digest != digest:
                    raise RuntimeConflict("immutable_profile_conflict")
            else:
                row = await repo.save(
                    RuntimeProfile(
                        id=digest[:32],
                        code=definition.code,
                        revision=definition.revision,
                        language=definition.language,
                        contract_version=definition.contract_version,
                        created_by=None,
                        origin="system",
                        release_version=lock["release"],
                        catalog_digest=lock["catalog_sha256"],
                        content_digest=digest,
                        definition=body,
                    )
                )
            selected[f"{definition.code}@{definition.revision}"] = row
        for language, reference in defaults.items():
            if not await repo.find(RuntimeProfileDefault, language=language, lock=True):
                await repo.save(RuntimeProfileDefault(language=language, profile_id=selected[reference].id))
    return len(definitions)


async def official_catalog_ready(root, *, repository=None):
    _, definitions, _ = load_official_catalog(root)
    repo = repository or RuntimeDeliveryRepository()
    for definition in definitions:
        existing = await repo.find(RuntimeProfile, code=definition.code, revision=definition.revision)
        if not existing or existing[0].content_digest != content_digest(definition.model_dump(mode="json")):
            return False
    return True
