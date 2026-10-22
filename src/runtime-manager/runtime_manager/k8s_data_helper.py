"""One-volume data endpoint with public keys and a durable ambiguity journal.

No manager/platform credential is present here. A fresh backend owner grant is
required for every accepted request, including reads of an earlier result.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Request

from runtime_manager.appdb import AppDbService
from runtime_manager.config import Config
from runtime_manager.data_grant import DataGrantError, canonical_json, verify_grant
from runtime_manager.errors import DataInvalidError, RuntimeManagerError


class VolumeDatabase(AppDbService):
    def __init__(self, volume, app_id):
        self.volume, self.app_id = Path(volume), app_id
        super().__init__(Config(data_root=self.volume / "platform"))

    def db_path(self, app_id):
        if app_id != self.app_id:
            raise DataInvalidError("Application scope mismatch")
        root = self.volume / "business"
        path = root / "app.db"
        if root.is_symlink() or any(
            (root / name).is_symlink() for name in ("app.db", "app.db-wal", "app.db-shm", "app.db-journal")
        ):
            raise DataInvalidError("Database links are refused")
        if path.exists() and not path.resolve().is_relative_to(root.resolve()):
            raise DataInvalidError("Database location is invalid")
        return path


class DataHelper:
    def __init__(self, volume, *, app_id, exec_ref, pod_uid, public_keys, clock=time.time, key_loader=None):
        self.volume = Path(volume).resolve()
        self.app_id, self.exec_ref, self.pod_uid = app_id, exec_ref, pod_uid
        self.public_keys, self.clock = dict(public_keys), clock
        self.key_loader = key_loader
        for path in (
            self.volume / "business",
            self.volume / "platform",
            self.volume / "platform/journal",
            self.volume / "platform/exports",
        ):
            if path.is_symlink():
                raise DataGrantError("data_layout_link_refused")
            path.mkdir(parents=True, exist_ok=True)
            if path.parent.name == "platform" or path.name == "platform":
                path.chmod(0o700)
        self.database = VolumeDatabase(self.volume, app_id)

    def _journal_path(self, request_id):
        try:
            if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            raise DataGrantError("data_request_id_invalid") from None
        return self.volume / "platform/journal" / (request_id + ".json")

    def _read(self, path):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError:
            raise DataGrantError("data_journal_unavailable") from None
        try:
            with os.fdopen(descriptor, "rb") as source:
                raw = source.read(16 * 1024**2 + 1)
            if len(raw) > 16 * 1024**2:
                raise ValueError()
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError()
            return document
        except (ValueError, OSError):
            raise DataGrantError("data_journal_invalid") from None

    @staticmethod
    def _sync_directory(directory):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write(self, path, document):
        raw = canonical_json(document)
        if len(raw) > 16 * 1024**2:
            raise DataGrantError("data_result_size_limit")
        temporary = path.with_name(".journal-" + uuid4().hex)
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
            self._sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _locked(self):
        path = self.volume / "platform/data.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DataGrantError("data_helper_busy") from None
            yield
        finally:
            os.close(descriptor)

    def current_keys(self):
        keys = self.key_loader() if self.key_loader else self.public_keys
        if (
            not isinstance(keys, dict)
            or not 1 <= len(keys) <= 8
            or any(not isinstance(key, str) or not 1 <= len(key) <= 64 for key in keys)
        ):
            raise DataGrantError("data_public_keys_invalid")
        return keys

    def execution_state(self):
        try:
            with self._locked():
                return {"idle": True}
        except DataGrantError as exc:
            if str(exc) != "data_helper_busy":
                raise
            return {"idle": False}

    def submit(self, ticket, parameters):
        claims = verify_grant(
            ticket,
            parameters,
            self.current_keys(),
            app_id=self.app_id,
            exec_ref=self.exec_ref,
            pod_uid=self.pod_uid,
            now=self.clock(),
        )
        with self._locked():
            if self.clock() >= claims["not_after"]:
                raise DataGrantError("data_grant_expired")
            path = self._journal_path(claims["request_id"])
            record = self._read(path)
            if record:
                if (record.get("action"), record.get("parameters_sha256")) != (
                    claims["action"],
                    claims["parameters_sha256"],
                ):
                    raise DataGrantError("data_request_content_changed")
                if claims["nonce"] in record.get("nonces", []):
                    raise DataGrantError("data_grant_replayed")
                if len(record.get("nonces", [])) >= 32:
                    raise DataGrantError("data_request_attempt_limit")
                record["nonces"] = [*record.get("nonces", []), claims["nonce"]]
                self._write(path, record)
                return (
                    record["result"]
                    if record.get("state") == "done"
                    else {"state": "unknown", "request_id": claims["request_id"]}
                )
            record = {
                "state": "started",
                "action": claims["action"],
                "parameters_sha256": claims["parameters_sha256"],
                "nonces": [claims["nonce"]],
                "operation_id": claims["operation_id"],
                "deadline": claims["deadline"],
            }
            # This fsync precedes the first possible SQLite write.
            self._write(path, record)
            if claims["action"] == "result":
                result = self._prior_result(parameters)
            else:
                result = self._bounded_action(claims, parameters)
            if result is None:
                return {"state": "unknown", "request_id": claims["request_id"]}
            record.update(state="done", result=result)
            self._write(path, record)
            return result

    def _prior_result(self, parameters):
        if set(parameters) != {"target_request_id", "parameters_sha256"}:
            raise DataGrantError("data_result_query_invalid")
        record = self._read(self._journal_path(parameters["target_request_id"]))
        if not record or record.get("parameters_sha256") != parameters["parameters_sha256"]:
            raise DataGrantError("data_result_scope_refused")
        if record.get("state") != "done":
            return {"state": "unknown", "request_id": parameters["target_request_id"]}
        return {"state": "done", "request_id": parameters["target_request_id"], "result": record["result"]}

    def _bounded_action(self, claims, parameters):
        remaining = claims["deadline"] - self.clock()
        if not 0 < remaining <= 60:
            return None
        context = multiprocessing.get_context("fork")
        reader, writer = context.Pipe(duplex=False)

        def child():
            reader.close()
            try:
                try:
                    result = self._dispatch(claims, parameters)
                except RuntimeManagerError as exc:
                    result = {
                        "error": {"code": exc.code, "message": "Application data operation failed"},
                        "status_code": exc.status_code,
                    }
                writer.send(result)
            except Exception:
                # A failed/ambiguous action deliberately leaves only started.
                pass
            finally:
                writer.close()

        process = context.Process(target=child, daemon=True)
        process.start()
        writer.close()
        try:
            if not reader.poll(remaining):
                return None
            try:
                return reader.recv()
            except (EOFError, OSError):
                return None
        finally:
            reader.close()
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)

    def _dispatch(self, claims, parameters):
        action, app = claims["action"], self.app_id
        if action == "tables":
            if parameters:
                raise DataInvalidError("Unexpected table parameters")
            return {"tables": self.database.list_tables(app)}
        if action == "schema":
            return self.database.table_schema(app, parameters["table"])
        if action == "rows":
            return self.database.rows(
                app,
                parameters["table"],
                page=parameters.get("page", 1),
                size=parameters.get("size", 50),
                order=parameters.get("order"),
            )
        if action == "update":
            return self.database.update_row(app, parameters["table"], parameters["key"], parameters["values"])
        if action == "export":
            path = self.database.export_csv(app, parameters["table"])
            target = self.export_path(claims["request_id"], exists=False)
            os.replace(path, target)
            with target.open("rb") as source:
                os.fsync(source.fileno())
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            self._sync_directory(target.parent)
            return {
                "export": {"request_id": claims["request_id"], "size_bytes": target.stat().st_size, "sha256": digest}
            }
        raise DataGrantError("data_action_refused")

    def export_path(self, request_id, *, exists=True):
        self._journal_path(request_id)
        path = self.volume / "platform/exports" / (request_id + ".csv")
        if path.is_symlink() or (exists and not path.is_file()):
            raise DataGrantError("data_export_unavailable")
        return path


def create_app(helper):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, StreamingResponse
    from starlette.concurrency import run_in_threadpool

    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @application.get("/healthz")
    async def health():
        return {"status": "ok", "key_ids": sorted(helper.current_keys())}

    @application.get("/execution-state")
    async def execution_state():
        return await run_in_threadpool(helper.execution_state)

    @application.post("/actions")
    async def action(request: Request):
        try:
            raw = await request.body()
            if len(raw) > 1024 * 1024:
                raise DataGrantError("data_request_size_limit")
            document = json.loads(raw)
            if not isinstance(document, dict) or set(document) != {"grant", "parameters"}:
                raise DataGrantError("data_request_fields_invalid")
            result = await run_in_threadpool(helper.submit, document["grant"], document["parameters"])
            if result.get("state") == "unknown":
                return JSONResponse(result, status_code=409)
            if result.get("error"):
                return JSONResponse(result, status_code=result.get("status_code", 400))
            if "export" not in result:
                return result
            path = helper.export_path(result["export"]["request_id"])
            deadline = document["grant"]["claims"]["deadline"]

            def content():
                with path.open("rb") as source:
                    while chunk := source.read(64 * 1024):
                        if helper.clock() >= deadline:
                            raise RuntimeError("data_export_deadline")
                        yield chunk

            return StreamingResponse(
                content(),
                media_type="text/csv",
                headers={
                    "Content-Length": str(result["export"]["size_bytes"]),
                    "X-Content-Sha256": result["export"]["sha256"],
                },
            )
        except (DataGrantError, ValueError, TypeError, KeyError):
            return JSONResponse(
                {"error": {"code": "data_busy", "message": "Data authorization or request is invalid"}}, status_code=403
            )

    return application


def main():
    import uvicorn

    context = json.loads(os.environ["DATA_CONTEXT"])
    keys = json.loads(Path("/run/data/public-keys.json").read_text())
    helper = DataHelper(
        Path("/volume"),
        app_id=context["app_id"],
        exec_ref=context["exec_ref"],
        pod_uid=os.environ["DATA_POD_UID"],
        public_keys=keys,
        key_loader=lambda: json.loads(Path("/run/data/public-keys.json").read_text()),
    )
    uvicorn.run(create_app(helper), host="0.0.0.0", port=8092, access_log=False)


if __name__ == "__main__":
    main()
