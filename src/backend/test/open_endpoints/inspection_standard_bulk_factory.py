"""Factory helpers for large-scale inspection-standard sync tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from inspection_standard_bulk_factory import (  # noqa: E402,F401
    DEFAULT_DEPT_COUNT,
    DEFAULT_RECORDS_PER_DEPT,
    build_bulk_payload_dict,
    build_check_standard_id,
    build_create_dept_id,
    build_item_dict,
    build_standard_dict,
)

try:
    from bisheng.open_endpoints.domain.schemas.inspection_standard_sync import (
        InspectionStandardSyncRequest,
    )
except ImportError:
    InspectionStandardSyncRequest = None  # type: ignore[misc, assignment]


def build_bulk_request(
    *,
    dept_count: int = DEFAULT_DEPT_COUNT,
    records_per_dept: int = DEFAULT_RECORDS_PER_DEPT,
    dept_indices: list[int] | None = None,
):
    payload = build_bulk_payload_dict(
        dept_count=dept_count,
        records_per_dept=records_per_dept,
        dept_indices=dept_indices,
    )
    if InspectionStandardSyncRequest is None:
        return payload
    return InspectionStandardSyncRequest.model_validate(payload)
