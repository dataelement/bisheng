#!/usr/bin/env python3
"""Bind a clinic knowledge space to a portal business domain (bidirectional).

Creates/updates both sides required by filelib dynamic business-domain checks:

1. Portal config ``domain.space_ids`` (+ optional ``domain.department_ids``)
2. Knowledge space ``business_domain_codes``

Default is dry-run. Pass ``--apply`` to persist changes.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/bind_clinic_space_business_domain.py \\
      --space-id 3689 --domain-code HR --department-id 2359

    PYTHONPATH=./ .venv/bin/python scripts/bind_clinic_space_business_domain.py \\
      --file scripts/examples/clinic_business_domain_bindings.example.json --apply

    bash scripts/bind_clinic_space_business_domain.sh \\
      --space-id 3689 --domain-code HR --department-id 2359 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.knowledge.domain.constants import normalize_business_domain_code  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_space_scope import (  # noqa: E402
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.models.department_knowledge_space import (  # noqa: E402
    DepartmentKnowledgeSpaceDao,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (  # noqa: E402
    ShougangPortalSpaceBusinessDomainCodesSyncReq,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService  # noqa: E402
from bisheng.open_endpoints.domain.services.filelib_sync_service import (  # noqa: E402
    FilelibSyncService,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (  # noqa: E402
    PortalDomainConfig,
    ShougangPortalAdminConfig,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (  # noqa: E402
    ShougangPortalConfigService,
)


@dataclass(frozen=True)
class BindingSpec:
    space_id: int
    domain_code: str
    department_ids: tuple[int, ...] = ()


@dataclass
class BindingPlan:
    spec: BindingSpec
    space_name: str = ""
    domain_name: str = ""
    is_clinic_like: bool = False
    bound_department_ids: tuple[int, ...] = ()
    current_space_domain_codes: list[str] = field(default_factory=list)
    new_space_domain_codes: list[str] = field(default_factory=list)
    current_domain_space_ids: list[int] = field(default_factory=list)
    new_domain_space_ids: list[int] = field(default_factory=list)
    current_domain_department_ids: list[int] = field(default_factory=list)
    new_domain_department_ids: list[int] = field(default_factory=list)
    portal_domain_changed: bool = False
    space_codes_changed: bool = False


def _normalize_department_ids(values: list[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw in values:
        department_id = int(raw)
        if department_id <= 0:
            raise ValueError(f"department_id must be positive, got {department_id}")
        if department_id not in normalized:
            normalized.append(department_id)
    return tuple(normalized)


def _merge_positive_ids(existing: list[int], additions: tuple[int, ...]) -> list[int]:
    merged = list(existing or [])
    for value in additions:
        department_id = int(value)
        if department_id > 0 and department_id not in merged:
            merged.append(department_id)
    return merged


def _load_specs_from_file(path: Path) -> list[BindingSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("binding file must be a JSON array")

    specs: list[BindingSpec] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"binding[{index}] must be an object")
        space_id = int(item.get("space_id") or 0)
        domain_code = normalize_business_domain_code(item.get("domain_code"))
        if space_id <= 0:
            raise ValueError(f"binding[{index}].space_id must be positive")
        if domain_code is None:
            raise ValueError(f"binding[{index}].domain_code is invalid")
        department_ids = _normalize_department_ids(
            [int(value) for value in (item.get("department_ids") or [])]
        )
        if "department_id" in item and item["department_id"] is not None:
            department_ids = _normalize_department_ids(
                list(department_ids) + [int(item["department_id"])]
            )
        specs.append(
            BindingSpec(
                space_id=space_id,
                domain_code=domain_code,
                department_ids=department_ids,
            )
        )
    return specs


def _find_domain(config: ShougangPortalAdminConfig, domain_code: str) -> PortalDomainConfig:
    matches = [
        domain
        for domain in config.portal.domains
        if normalize_business_domain_code(domain.code) == domain_code
    ]
    if not matches:
        known = ", ".join(sorted({domain.code for domain in config.portal.domains if domain.code}))
        raise ValueError(f"portal domain code {domain_code} not found; known codes: {known or '(none)'}")
    if len(matches) > 1:
        raise ValueError(f"portal domain code {domain_code} is ambiguous")
    return matches[0]


async def _is_clinic_like_space(space_id: int) -> tuple[bool, tuple[int, ...]]:
    bindings = await DepartmentKnowledgeSpaceDao.aget_by_space_ids([space_id])
    if not bindings:
        return False, ()
    bound_department_ids = tuple(sorted({int(binding.department_id) for binding in bindings}))
    scopes = await KnowledgeSpaceScopeDao.aget_by_space_ids([space_id])
    for scope in scopes:
        if (
            KnowledgeSpaceLevelEnum.is_team_level(scope.level)
            and scope.owner_type == KnowledgeSpaceOwnerTypeEnum.USER
        ):
            return True, bound_department_ids
    return False, bound_department_ids


async def _build_plan(
    config: ShougangPortalAdminConfig,
    spec: BindingSpec,
) -> BindingPlan:
    spaces = await KnowledgeDao.async_get_spaces_by_ids([spec.space_id])
    if len(spaces) != 1:
        raise ValueError(f"knowledge space {spec.space_id} does not exist")

    space = spaces[0]
    if int(space.type) != KnowledgeTypeEnum.SPACE.value:
        raise ValueError(f"knowledge id {spec.space_id} is not a knowledge space")

    domain = _find_domain(config, spec.domain_code)
    is_clinic_like, bound_department_ids = await _is_clinic_like_space(spec.space_id)

    current_space_codes = [
        code
        for code in (
            normalize_business_domain_code(raw)
            for raw in (getattr(space, "business_domain_codes", None) or [])
        )
        if code
    ]
    new_space_codes = list(current_space_codes)
    if spec.domain_code not in new_space_codes:
        new_space_codes.append(spec.domain_code)

    current_domain_space_ids = [int(space_id) for space_id in (domain.space_ids or []) if int(space_id) > 0]
    new_domain_space_ids = _merge_positive_ids(current_domain_space_ids, (spec.space_id,))

    current_domain_department_ids = [
        int(department_id)
        for department_id in (domain.department_ids or [])
        if int(department_id) > 0
    ]
    additions = spec.department_ids or bound_department_ids
    new_domain_department_ids = _merge_positive_ids(current_domain_department_ids, additions)

    return BindingPlan(
        spec=spec,
        space_name=str(space.name or ""),
        domain_name=str(domain.name or ""),
        is_clinic_like=is_clinic_like,
        bound_department_ids=bound_department_ids,
        current_space_domain_codes=current_space_codes,
        new_space_domain_codes=new_space_codes,
        current_domain_space_ids=current_domain_space_ids,
        new_domain_space_ids=new_domain_space_ids,
        current_domain_department_ids=current_domain_department_ids,
        new_domain_department_ids=new_domain_department_ids,
        portal_domain_changed=(
            new_domain_space_ids != current_domain_space_ids
            or new_domain_department_ids != current_domain_department_ids
        ),
        space_codes_changed=new_space_codes != current_space_codes,
    )


def _apply_plans_to_config(config: ShougangPortalAdminConfig, plans: list[BindingPlan]) -> None:
    grouped: dict[str, list[BindingPlan]] = {}
    for plan in plans:
        grouped.setdefault(plan.spec.domain_code, []).append(plan)

    for domain_code, domain_plans in grouped.items():
        domain = _find_domain(config, domain_code)
        merged_space_ids = list(domain.space_ids or [])
        merged_department_ids = list(domain.department_ids or [])
        for plan in domain_plans:
            merged_space_ids = _merge_positive_ids(merged_space_ids, (plan.spec.space_id,))
            merged_department_ids = _merge_positive_ids(
                merged_department_ids,
                plan.spec.department_ids or plan.bound_department_ids,
            )
        domain.space_ids = merged_space_ids
        domain.department_ids = merged_department_ids


def _print_plan(plan: BindingPlan) -> None:
    print(f"[bind_clinic_space_business_domain] space_id={plan.spec.space_id} name={plan.space_name!r}")
    print(f"  domain_code={plan.spec.domain_code} domain_name={plan.domain_name!r}")
    print(f"  clinic_like={plan.is_clinic_like} bound_department_ids={list(plan.bound_department_ids)}")
    print(
        "  space.business_domain_codes:"
        f" {plan.current_space_domain_codes} -> {plan.new_space_domain_codes}"
        f" ({'change' if plan.space_codes_changed else 'unchanged'})"
    )
    print(
        "  domain.space_ids:"
        f" {plan.current_domain_space_ids} -> {plan.new_domain_space_ids}"
    )
    print(
        "  domain.department_ids:"
        f" {plan.current_domain_department_ids} -> {plan.new_domain_department_ids}"
    )
    if not plan.spec.department_ids and not plan.bound_department_ids:
        print("  warning: no department_ids provided or inferred; dynamic filelib domain resolution may fail")


async def _verify_bidirectional_binding(
    *,
    space_id: int,
    space_name: str,
    space_codes: list[str],
    domain: PortalDomainConfig,
) -> None:
    from types import SimpleNamespace

    space = SimpleNamespace(
        id=space_id,
        name=space_name,
        business_domain_codes=space_codes,
    )
    FilelibSyncService._ensure_domain_bound(space, domain)


async def _run(
    specs: list[BindingSpec],
    *,
    tenant_id: int,
    apply: bool,
) -> int:
    if not specs:
        print("[bind_clinic_space_business_domain] no bindings requested", file=sys.stderr)
        return 1

    config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
    if config is None:
        print("[bind_clinic_space_business_domain] portal config not found", file=sys.stderr)
        return 1

    plans: list[BindingPlan] = []
    for spec in specs:
        plans.append(await _build_plan(config, spec))

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[bind_clinic_space_business_domain] mode={mode} tenant_id={tenant_id} bindings={len(plans)}")
    for plan in plans:
        _print_plan(plan)

    if not apply:
        print("[bind_clinic_space_business_domain] dry-run complete; re-run with --apply to persist")
        return 0

    working_config = config.model_copy(deep=True)
    portal_changed = any(plan.portal_domain_changed for plan in plans)
    if portal_changed:
        _apply_plans_to_config(working_config, plans)
    if portal_changed:
        saved = await ShougangPortalConfigService.save_config(
            working_config,
            tenant_id=tenant_id,
        )
        working_config = saved

    space_bindings = {
        plan.spec.space_id: plan.new_space_domain_codes
        for plan in plans
        if plan.space_codes_changed
    }
    if space_bindings:
        service = object.__new__(KnowledgeSpaceService)
        result = await service.sync_shougang_portal_space_business_domain_codes(
            ShougangPortalSpaceBusinessDomainCodesSyncReq(
                bindings=[
                    {"space_id": space_id, "business_domain_codes": codes}
                    for space_id, codes in space_bindings.items()
                ]
            )
        )
        print(f"[bind_clinic_space_business_domain] updated_space_codes={result['updated']}")

    if portal_changed:
        print(f"[bind_clinic_space_business_domain] saved_portal_config_version={working_config.version}")

    print("[bind_clinic_space_business_domain] verification:")
    for plan in plans:
        domain = _find_domain(working_config, plan.spec.domain_code)
        await _verify_bidirectional_binding(
            space_id=plan.spec.space_id,
            space_name=plan.space_name,
            space_codes=plan.new_space_domain_codes,
            domain=domain,
        )
        print(f"  ok space_id={plan.spec.space_id} domain_code={plan.spec.domain_code}")

    return 0


def _build_specs(args: argparse.Namespace) -> list[BindingSpec]:
    if args.file is not None:
        return _load_specs_from_file(args.file.expanduser().resolve())

    domain_code = normalize_business_domain_code(args.domain_code)
    if domain_code is None:
        raise ValueError("--domain-code is invalid")
    if args.space_id <= 0:
        raise ValueError("--space-id must be positive")

    return [
        BindingSpec(
            space_id=int(args.space_id),
            domain_code=domain_code,
            department_ids=_normalize_department_ids(list(args.department_id or [])),
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space-id", type=int, help="Clinic knowledge space id")
    parser.add_argument(
        "--domain-code",
        help="Portal business domain code, e.g. HR for 人力",
    )
    parser.add_argument(
        "--department-id",
        action="append",
        type=int,
        default=[],
        help="Department id for domain.department_ids (repeatable). "
        "If omitted, uses department_knowledge_space bindings on the space.",
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=1,
        help="Tenant id for portal config lookup/save (default: 1)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="JSON array of bindings: "
        '[{"space_id":3689,"domain_code":"HR","department_ids":[2359]}]',
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist portal config and knowledge.business_domain_codes",
    )
    args = parser.parse_args()

    if args.file is None and (args.space_id is None or not args.domain_code):
        parser.error("either --file or both --space-id and --domain-code are required")

    try:
        specs = _build_specs(args)
        return asyncio.run(_run(specs, tenant_id=int(args.tenant_id), apply=args.apply))
    except ValueError as exc:
        print(f"[bind_clinic_space_business_domain] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
