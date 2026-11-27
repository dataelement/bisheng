"""Durable, tenant-scoped OCR orchestration shared by previews and ingestion."""

import hashlib
import json
import time

from bisheng.knowledge.docflow.client import DocFlowClient, DocFlowError, SubmissionUnknown


class DocFlowService:
    def __init__(self, config, state, client=None, clock=time.monotonic, sleep=time.sleep):
        self.config, self.state = config, state
        self.client = client or DocFlowClient(config)
        self.clock, self.sleep = clock, sleep

    def reconcile(self, key, file_ids, batch_number=""):
        """Operator-only recovery after confirming the task in the same workspace.

        This is not a public endpoint. Call under the correct tenant context.
        The original upload is never replayed by this operation.
        """
        if not isinstance(file_ids, (list, tuple)) or not file_ids or len(set(map(str, file_ids))) != len(file_ids):
            raise DocFlowError("DocFlow reconciliation requires unique remote file IDs")
        with self.state.lease(key) as owned:
            checkpoint = self.state.read(key)
            if checkpoint.get("stage") not in ("submitting", "submission_unknown"):
                raise DocFlowError("Only an uncertain submission can be reconciled")
            self.client.authenticate()
            for file_id in file_ids:
                if not self.client.fetch(str(file_id)):
                    raise DocFlowError("Remote file is not visible in the configured workspace")
            owned()
            checkpoint.update(
                stage="submitted",
                remote={"batch_number": batch_number, "files": [{"id": str(file_id)} for file_id in file_ids]},
            )
            self.state.write(key, checkpoint)

    def parse(self, path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for part in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(part)
        # Include credentials as a one-way fingerprint so rotations cannot reuse
        # another account's artifacts. No secret is stored in the checkpoint.
        fingerprint = {
            key: self.config.get(key)
            for key in (
                "url",
                "host",
                "workspace_id",
                "parser_revision",
                "app_key",
                "app_secret",
                "docflow_app_id",
                "docflow_secret_code",
            )
        }
        key = hashlib.sha256(
            json.dumps([self.state.tenant_id, digest.hexdigest(), fingerprint], sort_keys=True).encode()
        ).hexdigest()
        with self.state.lease(key) as owned:
            checkpoint = self.state.read(key)
            if checkpoint.get("artifact"):
                cached = self.state.load_artifact(checkpoint["artifact"])
                if cached is not None:
                    return cached
            if checkpoint.get("stage") in ("submitting", "submission_unknown"):
                raise SubmissionUnknown("DocFlow submission outcome unknown; reconcile stored attachment before retry")
            return self._resume(key, checkpoint, path, owned)

    def _resume(self, key, checkpoint, path, job_owned):
        account = hashlib.sha256(
            json.dumps([self.config["url"], self.config["app_key"], self.config["workspace_id"]]).encode()
        ).hexdigest()
        with self.state.capacity(account, int(self.config.get("max_concurrency", 5))) as slot_owned:

            def owned():
                job_owned()
                slot_owned()

            self.client.authenticate()
            if not checkpoint.get("attachment_id"):
                attachment = self.client.upload(path)
                owned()
                checkpoint = {"stage": "uploaded", "attachment_id": attachment}
                self.state.write(key, checkpoint)
            if not checkpoint.get("remote"):
                owned()
                checkpoint["stage"] = "submitting"
                self.state.write(key, checkpoint)
                # A crash after this point is ambiguous; never auto-submit again.
                remote = self.client.submit(checkpoint["attachment_id"])
                owned()
                checkpoint.update(stage="submitted", remote=remote)
                self.state.write(key, checkpoint)
            deadline = self.clock() + float(self.config.get("poll_timeout", 120))
            while self.clock() < deadline:
                owned()
                results = []
                ready = True
                for remote in checkpoint["remote"]["files"]:
                    remaining = max(0.1, deadline - self.clock())
                    files = self.client.fetch(remote["id"], timeout=min(30, remaining))
                    if not files:
                        ready = False
                    for file in files:
                        status = str(file.get("recognition_status"))
                        if status == "2":
                            raise DocFlowError(f"DocFlow recognition failed; remote_file_id={remote['id']}")
                        if status == "10":
                            raise DocFlowError("DocFlow workspace stops at classification; enable full recognition")
                        if file.get("child_files") or int(file.get("task_type", 1)) != 1:
                            raise DocFlowError(
                                "DocFlow split tasks require source-page mapping; disable workspace splitting"
                            )
                        ready = ready and status == "1"
                        results.append(file)
                if ready and results:
                    owned()
                    name = self.state.save_artifact(key, results)
                    checkpoint.update(stage="ready", artifact=name)
                    self.state.write(key, checkpoint)
                    return results
                self.sleep(min(float(self.config.get("poll_interval", 3)), max(0, deadline - self.clock())))
            raise DocFlowError("DocFlow polling timed out; retry resumes stored remote tasks without reupload")
