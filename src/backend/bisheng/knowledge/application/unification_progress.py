"""Owned, secret-free F118 progress; no migration or readiness authority."""

import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from loguru import logger

from bisheng.common.services.metric_log import scoped_metric_sink

_active = ContextVar("f118_progress_recorder", default=None)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_NUMERIC = frozenset(
    {
        "bytes",
        "get_count",
        "sql_count",
        "transaction_count",
        "compiled_count",
        "scanned",
        "verified",
        "pending",
        "resumed_prefix",
        "failed_count",
        "retry_count",
        "batch_count",
        "source_count",
        "reference_count",
        "wait_seconds",
    }
)
_LABELS = frozenset({"waiting", "wait", "status", "step", "commit_outcome"})
_LABEL_VALUES = frozenset(
    {
        "object_get",
        "database",
        "sql",
        "fga",
        "minio",
        "io",
        "planning",
        "decode",
        "compile",
        "transaction_commit",
        "read",
        "write",
        "running",
        "complete",
        "failed",
        "cancelled",
        "idle",
        "unknown",
        "acknowledged",
        "not_attempted",
    }
)


def _utc():
    return datetime.now(UTC).isoformat(timespec="seconds")


def _name(value):
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError("invalid progress identity")
    return value


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("invalid progress count")
    return value


def _cursor(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid progress cursor")
    if len(value) <= 160 and re.fullmatch(r"[A-Za-z0-9_.:-]*", value):
        return value
    # Some native cursors are canonical JSON. Never print their free payload.
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _console(event):
    total = event.get("total")
    fields = (
        f"[F118] run={event['run_id']} mode={event['mode']} event={event['event']}",
        f"phase={event['phase']} tenant={event.get('tenant_id')}",
        f"processed={event['processed']}/{total if total is not None else 'unknown'} unit={event['unit']}",
        f"committed={event.get('committed')} elapsed_s={event['elapsed_s']}",
        f"rate={event.get('rate')} eta_s={event.get('eta_s')} waiting={event.get('waiting')}",
        f"cursor={event.get('cursor')} last_success={event.get('last_success_at')}",
    )
    sys.stderr.write(" ".join(fields) + "\n")
    sys.stderr.flush()


class ProgressRecorder:
    """A single command owns its heartbeat thread, file and ContextVars."""

    def __init__(self, run_id, *, mode, path=None, emit=None, interval=15):
        self.run_id = _name(run_id)
        if mode not in {"dry-run", "apply", "verify"}:
            raise ValueError("invalid progress mode")
        if not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("invalid progress interval")
        self.mode, self.interval = mode, float(interval)
        self.path = Path(path) if path is not None else None
        self.emit = emit or _console
        self._lock, self._output_lock = threading.RLock(), threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._file = None
        self._entered = False
        self._io_error = False
        self._metrics = {}
        self._samples = deque(maxlen=16)
        self._started = self._phase_started = monotonic()
        self._state = {
            "phase": "initialize",
            "tenant_id": None,
            "processed": 0,
            "total": None,
            "unit": "item",
            "committed": None,
            "cursor": None,
            "last_success_at": None,
        }

    @property
    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def __enter__(self):
        if self._entered:
            raise RuntimeError("progress recorder already entered")
        self._entered = True
        try:
            if self.path is not None:
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(self.path, flags, 0o600)
                if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_mode & 0o077:
                    os.close(fd)
                    raise OSError("unsafe progress output file")
                self._file = os.fdopen(fd, "a", encoding="utf-8")
            self._token = _active.set(self)
            self._metric_context = scoped_metric_sink(self._metric)
            self._metric_context.__enter__()
            self._send("started")
            self._thread = threading.Thread(target=self._heartbeat, name="f118-progress", daemon=True)
            self._thread.start()
            return self
        except BaseException:
            if hasattr(self, "_metric_context"):
                self._metric_context.__exit__(None, None, None)
            if hasattr(self, "_token"):
                _active.reset(self._token)
            if self._file is not None:
                self._file.close()
            raise

    def __exit__(self, kind, value, traceback):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            try:
                self._send("failed" if kind is not None else "finished")
            except OSError:
                if kind is None:
                    raise
                logger.warning("F118 progress output failed; original operation error preserved")
            if self.is_alive:
                if kind is None:
                    raise RuntimeError("progress reporter did not stop")
                logger.warning("F118 progress reporter did not stop; original operation error preserved")
            if self._io_error and kind is None:
                raise OSError("progress output failed")
        finally:
            self._metric_context.__exit__(kind, value, traceback)
            _active.reset(self._token)
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    if kind is None:
                        raise
                    logger.warning("F118 progress close failed; original operation error preserved")

    def _heartbeat(self):
        while not self._stop.wait(self.interval):
            try:
                self._send("heartbeat")
            except OSError as error:
                # Telemetry cannot change a committed effect. Surface failure
                # now and fail the final report rather than hiding the error.
                self._io_error = True
                logger.warning("F118 progress output failed type={}", type(error).__name__)
                self._stop.set()

    def _metric(self, domain, fields):
        if domain != "permission_visibility_projection":
            return False
        with self._lock:
            item = self._metrics.setdefault(domain, {"count": 0})
            item["count"] += 1
            for key in ("elapsed_ms", "source_count", "unique_tuple_count", "stale_count", "orphan_count"):
                v = fields.get(key)
                if type(v) in (int, float) and math.isfinite(v):
                    item[key + "_sum"] = item.get(key + "_sum", 0) + v
        return True

    def update(
        self, phase, *, tenant_id=None, processed=0, total=None, unit="item", committed=None, cursor=None, **details
    ):
        _name(phase)
        _name(unit)
        _count(processed)
        if total is not None:
            _count(total)
        if committed is not None:
            _count(committed)
        if tenant_id is not None and (type(tenant_id) is not int or tenant_id <= 0):
            raise ValueError("invalid progress tenant")
        now = monotonic()
        with self._lock:
            changed = (phase, tenant_id, unit) != tuple(self._state[k] for k in ("phase", "tenant_id", "unit"))
            if changed:
                self._phase_started = now
                self._samples.clear()
                self._samples.append((now, committed if committed is not None else processed))
            previous = self._state.get("committed")
            self._state = {
                "phase": phase,
                "tenant_id": tenant_id,
                "processed": processed,
                "total": total,
                "unit": unit,
                "committed": committed,
                "cursor": _cursor(cursor),
                "last_success_at": self._state.get("last_success_at"),
            }
            if committed is not None and committed > 0 and (changed or previous is None or committed > previous):
                self._state["last_success_at"] = _utc()
            self._samples.append((now, committed if committed is not None else processed))
            for key, val in details.items():
                if key in _NUMERIC and type(val) in (int, float) and math.isfinite(val) and val >= 0:
                    self._state[key] = val
                elif key in _LABELS and isinstance(val, str) and val in _LABEL_VALUES:
                    self._state[key] = val
        if changed:
            self._send("phase")

    def _send(self, event):
        now = monotonic()
        with self._lock:
            payload = {"run_id": self.run_id, "mode": self.mode, "event": event, "at": _utc(), **self._state}
            payload["elapsed_s"] = round(now - self._started, 3)
            payload["phase_elapsed_s"] = round(now - self._phase_started, 3)
            payload["rate"] = payload["eta_s"] = None
            if len(self._samples) > 1:
                first, last = self._samples[0], self._samples[-1]
                span, completed = last[0] - first[0], last[1] - first[1]
                if span > 0 and completed > 0:
                    rate = completed / span
                    payload["rate"] = round(rate, 3)
                    if payload["total"] is not None:
                        payload["eta_s"] = round(max(0, payload["total"] - last[1]) / rate, 1)
            payload["metrics"] = {key: dict(value) for key, value in self._metrics.items()}
        with self._output_lock:
            if self._file is not None:
                self._file.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
                self._file.flush()
            self.emit(payload)


def report_progress(phase, **fields):
    recorder = _active.get()
    if recorder is not None:
        recorder.update(phase, **fields)
