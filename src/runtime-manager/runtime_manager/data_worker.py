"""One bounded SQLite action inside a networkless container mounting one app's data."""

import json
import sys
from pathlib import Path

from runtime_manager.appdb import AppDbService
from runtime_manager.config import Config
from runtime_manager.errors import RuntimeManagerError


def execute(document):
    service = AppDbService(Config(data_root=Path("/app-data")))
    action = document["action"]
    app = document["app_id"]
    params = document.get("parameters", {})
    if action == "tables":
        return {"tables": service.list_tables(app)}
    if action == "schema":
        return service.table_schema(app, params["table"])
    if action == "rows":
        return service.rows(
            app, params["table"], page=params.get("page", 1), size=params.get("size", 50), order=params.get("order")
        )
    if action == "update":
        return service.update_row(app, params["table"], params["key"], params["values"])
    if action == "export":
        path = service.export_csv(app, params["table"])
        return {"file": path.relative_to(Path("/app-data/exports")).as_posix()}
    raise ValueError("unsupported data action")


def main():
    try:
        answer = {"result": execute(json.loads(sys.argv[1]))}
    except RuntimeManagerError as exc:
        answer = {"error": exc.detail, "status_code": exc.status_code}
    print(json.dumps(answer, ensure_ascii=False))


if __name__ == "__main__":
    main()
