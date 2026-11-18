"""Preview/reconcile existing Root provider sharing through its business Owner.

Run from src/backend with the live service config. Preview is the default:
  python scripts/repair_model_sharing.py --operator-id 191 --manifest /tmp/sharing.json
  python scripts/repair_model_sharing.py --operator-id 191 --manifest /tmp/sharing.json --apply --provider-ids 337,358

Apply consumes the preview's exact intent/version under the provider lock. It
never enables a previously disabled/unshared provider or bypasses a pending
operation. Missing receiving policies are initialized; restrictions are kept.
The short-lived operator credential stays in memory and is never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from starlette.requests import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings
from bisheng.core.context import close_app_context, initialize_app_context
from bisheng.core.context.manager import app_context
from bisheng.core.context.tenant import management_tenant_scope, set_current_tenant_id
from bisheng.llm.application.model_sharing import ModelSharingApplication
from bisheng.llm.application.model_sharing_status import ModelSharingStatusService
from bisheng.llm.domain.models.llm_server import LLMDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.services.auth import AuthJwt


async def prepare_runtime():
    """Use public process compositions without importing/starting the HTTP app."""
    from bisheng.api.services.f048_permission_runtime import initialize_f048_worker_runtime
    from bisheng.department.domain.services.department_projection_scope import (
        get_department_projection_scope,
        register_department_projection_runtime_context,
    )
    from bisheng.llm.application.model_provider_projection import get_model_provider_projection_scope
    from bisheng.permission.application.process_runtime import (
        get_f048_process_runtime,
        register_f048_permission_runtime_context,
    )
    from bisheng.resource_reference.composition import register

    async def initialize(client):
        return await initialize_f048_worker_runtime(
            client,
            external_scopes={
                "department": get_department_projection_scope(),
                "llm_model_deletion": get_model_provider_projection_scope(),
            },
        )

    register_f048_permission_runtime_context(initialize)
    register_department_projection_runtime_context()
    await get_f048_process_runtime()
    register()


async def operator_identity(operator_id):
    row = await UserDao.aget_user(operator_id)
    if row is None or row.delete != 0:
        raise ValueError("An active Root global-super operator is required")
    token = AuthJwt().create_access_token(
        {"user_id": row.user_id, "user_name": row.user_name, "tenant_id": 1, "token_version": row.token_version},
        expires_in=900,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/maintenance/model-sharing",
            "query_string": b"",
            "headers": [(b"cookie", ("access_token_cookie=" + token).encode())],
            "server": ("localhost", 0),
            "client": ("localhost", 0),
            "scheme": "http",
        }
    )
    request.state.require_current_super = True
    user = await UserPayload.get_login_user(AuthJwt(request))
    if not user.is_global_super or user.tenant_id != 1:
        raise ValueError("An active Root global-super operator is required")
    return user


async def run(args):
    set_current_tenant_id(1)
    await initialize_app_context(config=settings, instance_role="script")
    try:
        await prepare_runtime()
        with management_tenant_scope(1):
            user = await operator_identity(args.operator_id)
            readiness = app_context.get_context("openfga").readiness()
            pin = {key: readiness[key] for key in ("store_id", "model_id", "catalog_release_id")}
            sharing = ModelSharingApplication()
            status = ModelSharingStatusService(sharing)
            providers = await LLMDao.aget_all_server()
            own = {p.id: p for p in providers if p.tenant_id == 1}
            if not args.apply:
                rows = []
                for sid, provider in sorted(own.items()):
                    try:
                        state = await status.aget(identity=user, server_id=sid)
                        rows.append({"server_id": sid, "name": provider.name, **state})
                    except Exception as error:
                        row = {"server_id": sid, "name": provider.name, "error": type(error).__name__}
                        try:
                            row["unstarted_preparation"] = await sharing.aprepare_cancellation(
                                identity=user, server_id=sid
                            )
                        except Exception:
                            pass
                        rows.append(row)
                manifest = {"operator_id": user.user_id, "runtime": pin, "providers": rows}
                args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                return manifest, 0
            saved = json.loads(args.manifest.read_text())
            if saved["operator_id"] != user.user_id or saved["runtime"] != pin:
                raise ValueError("Operator or permission runtime changed since preview")
            selected = {int(value) for value in args.provider_ids.split(",") if value}
            if not selected or not selected <= set(own):
                raise ValueError("Apply requires existing Root provider IDs")
            before = {row["server_id"]: row for row in saved["providers"]}
            if any(sid not in before for sid in selected):
                raise ValueError("Every selected provider must exist in the preview")
            if args.abandon_preparing:
                if any("unstarted_preparation" not in before[sid] for sid in selected):
                    raise ValueError("Every selected preparation must be previewed as safely cancellable")
                results = []
                for sid in sorted(selected):
                    record = before[sid]["unstarted_preparation"]
                    result = await sharing.aprepare_cancellation(
                        identity=user,
                        server_id=sid,
                        expected_fingerprint=record["fingerprint"],
                    )
                    results.append({"server_id": sid, **result})
                return {"runtime": pin, "cancelled_preparations": results}, 0
            if any(before[sid].get("enabled") is not True for sid in selected):
                raise ValueError("Only providers previewed as enabled may be repaired")
            results = []
            for sid in sorted(selected):
                row = before[sid]
                try:
                    await sharing.arepair_enabled_sharing(
                        identity=user,
                        server_id=sid,
                        expected_enabled=row["stored_enabled"],
                        expected_version=row["version"],
                        expected_plan_id=row["plan_id"],
                    )
                    state = await status.aget(identity=user, server_id=sid)
                    results.append({"server_id": sid, "result": "repaired", **state})
                except Exception as error:
                    results.append({"server_id": sid, "result": "blocked", "error": type(error).__name__})
            return {"runtime": pin, "results": results}, int(any(r["result"] != "repaired" for r in results))
    finally:
        await close_app_context()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-id", type=int, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--provider-ids", default="")
    parser.add_argument(
        "--abandon-preparing",
        action="store_true",
        help="Explicitly retire only a previewed unstarted preparation; never repairs grants in the same invocation",
    )
    args = parser.parse_args()
    if args.operator_id <= 0:
        parser.error("operator ID must be positive")
    if args.abandon_preparing and not args.apply:
        parser.error("--abandon-preparing requires --apply and a preview manifest")
    logger.remove()
    result, code = asyncio.run(run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
