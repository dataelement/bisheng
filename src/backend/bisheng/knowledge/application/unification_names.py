"""Compile original APP names once; resolving names grants no target authority.

The real migration must supply its original, eligible NameCatalog. This pure
index never discovers sharing, queries SQL, certifies absence or writes ready.
"""

from bisheng.app_publish.domain.services.reference_extractor import AppReferenceRequest
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.model_face import (
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.knowledge.domain.repositories.unification_inventory_repository import KnowledgeRow
from bisheng.llm.domain.repositories.model_name_resolution_repository import CatalogModel, CatalogServer, NameCatalog
from bisheng.resource_reference.application.contracts import TargetKey, TargetType, canonical_target_id


def _invalid(reason="app_reference_resolution"):
    raise ResourceReferenceInvalidError(reason=reason)


def _positive(value):
    return type(value) is int and value > 0


def _text(value, *, empty=False):
    return isinstance(value, str) and (bool(value) or empty) and "\x00" not in value


class UnificationNameIndex:
    def __init__(self, model_catalog: NameCatalog, knowledge_rows: tuple[KnowledgeRow, ...]):
        if (
            not isinstance(model_catalog, NameCatalog)
            or not _positive(model_catalog.tenant_id)
            or type(model_catalog.servers) is not tuple
            or type(model_catalog.models) is not tuple
            or type(model_catalog.visible_server_ids) is not frozenset
            or type(knowledge_rows) is not tuple
        ):
            _invalid("migration_name_catalog_invalid")
        tenant = model_catalog.tenant_id
        servers = {}
        for server in model_catalog.servers:
            if not isinstance(server, CatalogServer):
                _invalid("migration_name_catalog_invalid")
            ident, owner, name = server.id, server.tenant_id, server.name
            if (
                not _positive(ident)
                or not _positive(owner)
                or owner not in {tenant, ROOT_TENANT_ID}
                or ident in servers
                or not _text(name, empty=True)
            ):
                _invalid("migration_name_catalog_invalid")
            servers[ident] = (owner, name)
        visible = model_catalog.visible_server_ids
        if any(not _positive(ident) or ident not in servers for ident in visible):
            _invalid("migration_name_catalog_invalid")
        bare, qualified, offline, model_ids = {}, {}, set(), set()
        for model in model_catalog.models:
            if not isinstance(model, CatalogModel):
                _invalid("migration_name_catalog_invalid")
            ident, owner, parent, name, kind, online = (
                model.id,
                model.tenant_id,
                model.server_id,
                model.model_name,
                model.model_type,
                model.online,
            )
            server = servers.get(parent) if _positive(parent) else None
            if (
                not _positive(ident)
                or ident in model_ids
                or server is None
                or not _positive(owner)
                or owner != server[0]
                or not _text(name, empty=True)
                or not isinstance(kind, str)
                or type(online) is not bool
            ):
                _invalid("migration_name_catalog_invalid")
            model_ids.add(ident)
            if parent not in visible or kind != "llm":
                continue
            full_name = f"{server[1]}/{name}"
            if online:
                candidate = (str(ident), full_name)
                bare.setdefault(name, []).append(candidate)
                qualified.setdefault(full_name, []).append(candidate)
            else:
                offline.update((name, full_name))
        self._bare = {name: tuple(matches) for name, matches in bare.items()}
        self._qualified = {name: tuple(matches) for name, matches in qualified.items()}
        self._offline = frozenset(offline)
        knowledge, knowledge_ids = {}, set()
        for row in knowledge_rows:
            if not isinstance(row, KnowledgeRow):
                _invalid("migration_name_catalog_invalid")
            ident, owner, kind, name = row.id, row.tenant_id, row.type, row.name
            if (
                not _positive(ident)
                or ident in knowledge_ids
                or type(owner) is not int
                or owner != tenant
                or type(kind) is not int
                or not _text(name, empty=True)
            ):
                _invalid("migration_name_catalog_invalid")
            knowledge_ids.add(ident)
            if kind in {0, 3}:
                knowledge.setdefault(name, []).append(str(ident))
        self._knowledge = {name: tuple(matches) for name, matches in knowledge.items()}

    @staticmethod
    def _requests(requests):
        if type(requests) is not tuple:
            _invalid()
        slots = {}
        for request in requests:
            if (
                not isinstance(request, AppReferenceRequest)
                or not _text(request.slot_key)
                or len(request.slot_key) > 192
                or not isinstance(request.target_type, TargetType)
                or request.target_type not in {TargetType.MODEL, TargetType.KNOWLEDGE_SPACE}
                or (request.requested_name is not None and not _text(request.requested_name))
            ):
                _invalid()
            if request.target_type == TargetType.MODEL:
                if request.target_id is not None or request.requested_name is None:
                    _invalid()
                meaning = (TargetType.MODEL, request.requested_name, None)
            elif request.target_id is not None:
                if not isinstance(request.target_id, str):
                    _invalid()
                try:
                    target_id = canonical_target_id(request.target_id)
                except ValueError as error:
                    raise ResourceReferenceInvalidError(reason="app_reference_resolution") from error
                # Explicit ID remains the identity even if a legacy request
                # also carries its old display name. No fallback is possible.
                meaning = (TargetType.KNOWLEDGE_SPACE, None, target_id)
            else:
                if request.requested_name is None:
                    _invalid()
                meaning = (TargetType.KNOWLEDGE_SPACE, request.requested_name, None)
            if request.slot_key in slots and slots[request.slot_key] != meaning:
                _invalid()
            slots[request.slot_key] = meaning
        return slots

    def resolve(self, requests: tuple[AppReferenceRequest, ...]) -> dict[str, TargetKey]:
        result = {}
        for slot, (kind, name, explicit_id) in self._requests(requests).items():
            if explicit_id is not None:
                result[slot] = TargetKey(kind, explicit_id)
            elif kind == TargetType.MODEL:
                # Match the original Port: only online bare matches outrank
                # qualified matches; offline candidates are considered last.
                matches = self._bare.get(name) or self._qualified.get(name) or ()
                if len(matches) > 1:
                    raise ModelFaceModelAmbiguousError(model=name, candidates=sorted(full for _, full in matches))
                if not matches:
                    if name in self._offline:
                        raise ModelFaceModelOfflineError(model=name)
                    raise ModelFaceModelNotFoundError(model=name)
                result[slot] = TargetKey(kind, matches[0][0])
            else:
                matches = self._knowledge.get(name, ())
                if len(matches) != 1:
                    _invalid("app_knowledge_name_ambiguous" if len(matches) > 1 else "app_knowledge_unavailable")
                result[slot] = TargetKey(kind, matches[0])
        return result
