"""Prepare a new installation before `alembic upgrade head`, never an existing DB.

Run from src/backend with the API's config: python scripts/initialize_installation.py
(read-only preview), or add --apply before Alembic. A durable empty-schema claim
allows retry after interrupted DDL. Root, Coverage and completion commit together.
This is DB-only: it never initializes external storage or invokes API seeds.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


async def main():
    from sqlmodel import SQLModel

    from bisheng.core.database import get_async_db_session, sync_get_database_connection
    from bisheng.core.database.model_discovery import import_all_sqlmodel_models
    from bisheng.tenant.application.installation import initialize_installation

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    import_all_sqlmodel_models()
    database = sync_get_database_connection()
    try:
        result = await initialize_installation(
            engine=database.engine, metadata=SQLModel.metadata, sessions=get_async_db_session, apply=args.apply
        )
        print(json.dumps(result))
    finally:
        await database.close()
        database.close_sync()


if __name__ == "__main__":
    asyncio.run(main())
