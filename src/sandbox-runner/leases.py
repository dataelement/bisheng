"""In-memory session leases for one runner replica. Must not import bisheng."""

from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from logutil import get_logger

_log = get_logger()


@dataclass
class Lease:
    session_id: str
    lease_token: str
    work_dir: str
    created_at: float
    last_active: float
    uid: int
    md5_index: dict[str, str] = field(default_factory=dict)
    pre_exec_snapshot: dict[str, tuple[float, int]] | None = None
    copy_out_allowed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class LeaseStore:
    def __init__(
        self,
        *,
        sessions_root: str,
        max_sessions: int = 1,
        lease_ttl_s: float = 900,
        enable_uid_isolation: bool = False,
        default_uid: int = 65534,
        clock: Callable[[], float] | None = None,
    ):
        if max_sessions > 1 and not enable_uid_isolation:
            raise RuntimeError("max_sessions > 1 requires enable_uid_isolation")
        self.sessions_root = sessions_root
        self.max_sessions = max_sessions
        self.lease_ttl_s = lease_ttl_s
        self.enable_uid_isolation = enable_uid_isolation
        self.default_uid = default_uid
        self._clock = clock or time.monotonic
        self._leases: dict[str, Lease] = {}
        self._guard = threading.Lock()
        os.makedirs(self.sessions_root, exist_ok=True)
        if self.enable_uid_isolation:
            os.chmod(self.sessions_root, 0o711)

    def _now(self) -> float:
        return self._clock()

    def reap_expired(self) -> None:
        now = self._now()
        with self._guard:
            expired = [sid for sid, lease in self._leases.items() if now - lease.last_active > self.lease_ttl_s]
        for sid in expired:
            self.delete(sid, lease_token=None, force=True, reason="idle")

    def create(self) -> Lease:
        self.reap_expired()
        with self._guard:
            if len(self._leases) >= self.max_sessions:
                raise CapacityError()
            session_id = str(uuid.uuid4())
            work_dir = os.path.join(self.sessions_root, session_id)
            os.makedirs(work_dir, exist_ok=True)
            uid = self.default_uid
            if self.enable_uid_isolation:
                # Distinct uid per session. Keep the tree root-owned until exec:
                # supervisor drops DAC_OVERRIDE, so copy-in cannot write a 0700
                # directory already chown'ed to the session uid.
                uid = 10000 + (len(self._leases) % 1000)
                os.chmod(work_dir, 0o700)
            else:
                os.chmod(work_dir, 0o755)
            now = self._now()
            lease = Lease(
                session_id=session_id,
                lease_token=uuid.uuid4().hex + uuid.uuid4().hex,
                work_dir=work_dir,
                created_at=now,
                last_active=now,
                uid=uid,
            )
            self._leases[session_id] = lease
        _log.info(
            "session created session_id=%s uid=%s slots=%s/%s isolation=%s",
            session_id,
            uid,
            len(self._leases),
            self.max_sessions,
            self.enable_uid_isolation,
        )
        return lease

    def get(self, session_id: str, lease_token: str) -> Lease:
        self.reap_expired()
        with self._guard:
            lease = self._leases.get(session_id)
        if lease is None:
            raise UnknownLeaseError()
        if lease.lease_token != lease_token:
            raise ForbiddenLeaseError()
        lease.last_active = self._now()
        return lease

    def delete(
        self,
        session_id: str,
        lease_token: str | None,
        *,
        force: bool = False,
        reason: str = "",
    ) -> None:
        with self._guard:
            lease = self._leases.get(session_id)
            if lease is None:
                if force:
                    return
                raise UnknownLeaseError()
            if not force and lease.lease_token != lease_token:
                raise ForbiddenLeaseError()
            self._leases.pop(session_id, None)
            remaining = len(self._leases)
        shutil.rmtree(lease.work_dir, ignore_errors=True)
        _log.info(
            "session deleted session_id=%s reason=%s slots=%s/%s",
            session_id,
            reason or ("force" if force else "client"),
            remaining,
            self.max_sessions,
        )

    def expires_at_iso(self, lease: Lease) -> str:
        wall = datetime.now(UTC).timestamp() + max(self.lease_ttl_s - (self._now() - lease.last_active), 0)
        return datetime.fromtimestamp(wall, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CapacityError(Exception):
    pass


class UnknownLeaseError(Exception):
    pass


class ForbiddenLeaseError(Exception):
    pass
