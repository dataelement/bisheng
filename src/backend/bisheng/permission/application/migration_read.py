"""Original-pin reads for explicit operational inventory, never online gates."""

import re
from contextlib import aclosing
from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.discovery import discover_openfga_runtime
from bisheng.permission.migration.f118_plan import PermissionCatalogBaseline


def _blocked(reason):
    return PermissionMigrationBlockedError(reason=f"f118_inventory_sharing_{reason}")


def target_authorization_model_checksum() -> str:
    return authorization_model_checksum(build_authorization_model_f048())


@dataclass(frozen=True, slots=True)
class OriginalTupleFact:
    user: str
    relation: str
    object: str


class PinnedMigrationPermissionReader:
    def __init__(self, config: OpenFGAConf, catalog: PermissionCatalogBaseline, *, discovery=None, client_factory=None):
        if not isinstance(config, OpenFGAConf) or not isinstance(catalog, PermissionCatalogBaseline):
            raise _blocked("original_pin_required")
        release, pin = catalog.release, catalog.authorization
        if (
            not config.enabled
            or config.force_write_model
            or config.dual_model_mode
            or config.legacy_model_id
            or release.status != "CURRENT"
            or release.write_fenced
            or pin.status != "ACTIVE"
            or type(pin.id) is not int
            or pin.id <= 0
            or release.required_authorization_model_release_id != pin.id
            or any(
                not isinstance(value, str) or not value.strip()
                for value in (pin.environment, pin.store_id, pin.model_id)
            )
            or any(
                not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (pin.model_checksum, pin.required_relations_checksum)
            )
        ):
            raise _blocked("original_pin_invalid")
        self._config, self._pin = config.model_copy(deep=True), deepcopy(pin)
        self._discovery = discovery if discovery is not None else discover_openfga_runtime
        self._factory = client_factory if client_factory is not None else FGAClient
        self._client = None
        self._entered = False
        self._tuple_inventory_started = False

    async def __aenter__(self):
        if self._entered:
            raise _blocked("reader_already_used")
        self._entered = True
        try:
            actual = await self._discovery(
                self._config,
                expected_model=None,
                allow_bootstrap=False,
                required_store_id=self._pin.store_id,
                required_model_id=self._pin.model_id,
            )
        except Exception as error:
            raise _blocked("original_pin_unavailable") from error
        if (actual.store_id, actual.model_id, actual.model_checksum) != (
            self._pin.store_id,
            self._pin.model_id,
            self._pin.model_checksum,
        ):
            raise _blocked("original_pin_changed")
        client = self._factory(
            api_url=self._config.api_url,
            store_id=self._pin.store_id,
            model_id=self._pin.model_id,
            timeout=self._config.timeout,
        )
        if (client.store_id, client.model_id) != (self._pin.store_id, self._pin.model_id):
            await client.close()
            raise _blocked("transport_repin_rejected")
        self._client = client
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        client, self._client = self._client, None
        if client is not None:
            await client.close()

    def _scope(self, session, tenant_id):
        actual_tenant = get_current_tenant_id()
        if (
            self._client is None
            or not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or type(tenant_id) is not int
            or tenant_id <= 0
            or type(actual_tenant) is not int
            or actual_tenant != tenant_id
            or is_tenant_filter_bypassed()
        ):
            raise _blocked("concrete_native_tenant_required")

    def _tuple_scope(self, client=None):
        actual = self._client
        if (
            actual is None
            or (client is not None and actual is not client)
            or (actual.store_id, actual.model_id) != (self._pin.store_id, self._pin.model_id)
        ):
            raise _blocked("original_tuple_reader_not_open_or_changed")

    async def aiter_original_tuples(self):
        self._tuple_scope()
        if self._tuple_inventory_started:
            raise _blocked("original_tuple_inventory_already_started")
        self._tuple_inventory_started = True
        client = self._client
        try:
            async with aclosing(client.iter_tuples(consistency="HIGHER_CONSISTENCY")) as stream:
                async for key in stream:
                    self._tuple_scope(client)
                    if (
                        type(key) is not dict
                        or set(key)
                        not in (
                            {"user", "relation", "object"},
                            {"user", "relation", "object", "condition"},
                        )
                        or key.get("condition") is not None
                        or any(
                            not isinstance(value, str) or not value.strip() or len(value) > 4096 or "\x00" in value
                            for value in (key["user"], key["relation"], key["object"])
                        )
                    ):
                        raise _blocked("original_tuple_key_invalid")
                    yield OriginalTupleFact(key["user"], key["relation"], key["object"])
            self._tuple_scope(client)
        except PermissionMigrationBlockedError:
            raise
        except Exception as error:
            raise _blocked("complete_original_tuple_stream_required") from error

    async def aassert_no_file_objects(self, tenant_id, *, file_ids):
        self._tuple_scope()
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or get_current_tenant_id() != tenant_id
            or is_tenant_filter_bypassed()
        ):
            raise _blocked("concrete_native_tenant_required")
        if (
            type(file_ids) is not tuple
            or len(file_ids) > 199
            or len(set(file_ids)) != len(file_ids)
            or any(type(v) is not int or v <= 0 for v in file_ids)
        ):
            raise _blocked("invalid_absent_file_ids")
        for ident in file_ids:
            rows = await self._client.read_tuples(object=f"knowledge_file:{ident}", consistency="HIGHER_CONSISTENCY")
            self._tuple_scope()
            if get_current_tenant_id() != tenant_id or is_tenant_filter_bypassed():
                raise _blocked("concrete_native_tenant_required")
            if rows:
                raise _blocked("stranded_file_authorization_present")

    async def aassert_no_file_tuples(self, session, tenant_id, *, file_ids):
        self._scope(session, tenant_id)
        await self.aassert_no_file_objects(tenant_id, file_ids=file_ids)
        self._scope(session, tenant_id)

    async def aget_shared_server_ids(self, session, tenant_id) -> frozenset[int]:
        self._scope(session, tenant_id)
        if tenant_id == 1:
            return frozenset()
        try:
            objects = await self._client.stream_list_objects(
                user=f"tenant:{tenant_id}",
                relation="shared_with",
                type="llm_server",
                consistency="HIGHER_CONSISTENCY",
            )
        except Exception as error:
            raise _blocked("complete_stream_required") from error
        self._scope(session, tenant_id)
        if not isinstance(objects, tuple):
            raise _blocked("shared_identity_invalid")
        ids = set()
        for key in objects:
            if not isinstance(key, str) or re.fullmatch(r"llm_server:[1-9][0-9]*", key) is None:
                raise _blocked("shared_identity_invalid")
            ids.add(int(key.removeprefix("llm_server:")))
        return frozenset(ids)
