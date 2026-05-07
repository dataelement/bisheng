#!/usr/bin/env python3
"""One-off migration: move legacy `workstation.models` to Root
`tenant_system_model_config(linsight_llm).models`.

Rules:
- Read old models from `config.key = "workstation"`.
- Write only to default tenant (`tenant_id = 1`).
- If Root already has `linsight_llm`, merge by updating only `models`.
- If Root has no `linsight_llm`, create it with `{"models": ...}`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfigDao


def _parse_json(value: str | None, *, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _extract_legacy_models(config_row: Config | None) -> list[dict[str, Any]]:
    if config_row is None:
        return []
    payload = _parse_json(config_row.value, default={})
    models = payload.get('models')
    if models is None:
        return []
    if not isinstance(models, list):
        raise ValueError('Legacy workstation.models is not a list')
    return models


async def _run(apply: bool) -> int:
    legacy_row = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION)
    legacy_models = _extract_legacy_models(legacy_row)
    if not legacy_models:
        print('No legacy workstation.models found; nothing to migrate.')
        return 0

    with bypass_tenant_filter():
        root_row = await TenantSystemModelConfigDao.aget(
            ROOT_TENANT_ID,
            ConfigKeyEnum.LINSIGHT_LLM.value,
        )
    root_payload = _parse_json(root_row.value if root_row else None, default={})
    root_existing_models = root_payload.get('models')
    root_existing_count = len(root_existing_models) if isinstance(root_existing_models, list) else 0
    root_payload['models'] = legacy_models

    if apply:
        with bypass_tenant_filter():
            await TenantSystemModelConfigDao.aupsert(
                tenant_id=ROOT_TENANT_ID,
                key=ConfigKeyEnum.LINSIGHT_LLM.value,
                value=json.dumps(root_payload, ensure_ascii=False),
            )

    print('Mode:', 'apply' if apply else 'dry-run')
    print('Legacy models count:', len(legacy_models))
    print('Target tenant:', ROOT_TENANT_ID)
    print('Action:', 'merge existing root linsight_llm' if root_row else 'create root linsight_llm')
    print('Root existing models count:', root_existing_count)
    print('Root resulting models count:', len(legacy_models))
    print('Root models will be overwritten:', 'yes' if root_existing_count > 0 else 'no')
    print('Legacy workstation.models preserved:', 'yes')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Migrate legacy workstation.models to Root linsight_llm.models',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply writes. Omit for dry-run preview.',
    )
    args = parser.parse_args()
    return asyncio.run(_run(apply=args.apply))


if __name__ == '__main__':
    raise SystemExit(main())
