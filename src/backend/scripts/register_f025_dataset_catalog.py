"""Register historical F025 training versions in the catalog without changing original files.

Run from src/backend: python scripts/register_f025_dataset_catalog.py --tenant-id N [--apply]
Dry-run is the default. Only the explicitly selected tenant is inspected.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.finetune.domain.models.dataset import FinetuneDataset
from bisheng.finetune.domain.models.preset_train import PresetTrain
from bisheng.finetune.domain.repositories.dataset_catalog import DatasetCatalogRepository
from bisheng.finetune.domain.services.dataset_validation import build_preview
from bisheng.finetune.domain.services.datasets import DatasetService
from bisheng.finetune.domain.services.finetune_file import FinetuneFileService
from bisheng.finetune.domain.services.legacy_dataset import classify_records
from bisheng.utils import generate_uuid


async def register(tenant_id, apply=False):
    result = {"tenant_id": tenant_id, "apply": apply, "registered": [], "skipped": [], "errors": []}
    with tenant_execution_scope(tenant_id):
        after = ""
        while catalogs := await DatasetCatalogRepository.historical_catalogs(after):
            for catalog in catalogs:
                after = catalog.id
                if catalog.is_deleted or catalog.version_id:
                    continue
                try:
                    rows, digest = await DatasetService.read_original(catalog.url)
                    kind = classify_records(rows)
                    if kind not in {"legacy", "text"}:
                        raise ValueError("Legacy catalog entry contains unsupported media")
                    source = "qa" if catalog.type == 1 and catalog.source_type == "local" else catalog.source_type
                    if apply:
                        catalog.source_type = source
                        version = None
                        if kind == "text":
                            report = FinetuneFileService.dataset_report("text", digest, len(rows), 0)
                            report = await FinetuneFileService.store_preview(
                                catalog.url, report, build_preview(rows, lambda _: b"")
                            )
                            version = FinetuneDataset(
                                name=catalog.name,
                                url=catalog.url,
                                report=report,
                                user_id=int(catalog.user_id),
                                create_time=catalog.create_time,
                            )
                            catalog.data_type = "text"
                            catalog.version_id = version.id
                        await DatasetCatalogRepository.save(catalog, version)
                    if kind == "text":
                        result["registered"].append({"catalog_id": catalog.id, "data_type": kind})
                except Exception as exc:
                    # Each record is independent; report failures and exit nonzero without deleting originals.
                    result["errors"].append({"catalog_id": catalog.id, "error_type": type(exc).__name__})
        after = ""
        while versions := await DatasetCatalogRepository.historical_versions(after):
            for version in versions:
                after = version.id
                if await DatasetCatalogRepository.find(version.id, version=True, include_deleted=True):
                    result["skipped"].append(version.id)
                    continue
                try:
                    report = version.report
                    if report.get("delivery") == "remote":
                        kind = report["data_type"]
                        if kind not in {"image_text", "video_text"}:
                            raise ValueError("Remote text plan needs manual format inspection")
                    else:
                        records, digest = await DatasetService.read_original(version.url)
                        if digest != report["sha256"]:
                            raise ValueError("Recorded hash differs from the original object")
                        kind = classify_records(records)
                    catalog = PresetTrain(
                        id=version.id,
                        name=version.name,
                        url=version.url,
                        user_id=str(version.user_id),
                        data_type=kind,
                        source_type=report.get("remote", {}).get("type", "local"),
                        version_id=version.id,
                        create_time=version.create_time,
                    )
                    if await DatasetCatalogRepository.find(catalog.id, include_deleted=True):
                        catalog.id = generate_uuid()
                    if apply:
                        await DatasetCatalogRepository.save(catalog)
                    result["registered"].append({"version_id": version.id, "catalog_id": catalog.id, "data_type": kind})
                except Exception as exc:
                    # Per-record upgrade work is independent; retain the original and surface the failure.
                    result["errors"].append({"version_id": version.id, "error_type": type(exc).__name__})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(register(args.tenant_id, args.apply))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(1 if result["errors"] else 0)
