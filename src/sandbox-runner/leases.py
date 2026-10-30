"""In-memory session leases for one runner replica. Must not import bisheng."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from logutil import get_logger
from procutil import chown_tree, kill_group, kill_uid, uid_processes

_log = get_logger()

UID_BASE = 10000
DEFAULT_MAX_UIDS = 1000
# How long DELETE waits for the session lock after killing its processes before
# it hands the final cleanup to the current lock holder.
DEFAULT_DELETE_WAIT_S = 5.0
# kill(-1) is not atomic against a process that forks while it runs: repeat.
_UID_KILL_ROUNDS = 3
_UID_KILL_PAUSE_S = 0.05


@dataclass
class Lease:
    session_id: str
    lease_token: str
    work_dir: str
    created_at: float
    last_active: float
    uid: int
    # HOME / XDG dirs live outside work_dir so app caches never become artifacts.
    home_dir: str = ""
    md5_index: dict[str, str] = field(default_factory=dict)
    # Bytes currently attributed to each copied-in path (per-session total cap).
    copy_in_sizes: dict[str, int] = field(default_factory=dict)
    pre_exec_snapshot: dict[str, tuple[float, int]] | None = None
    copy_out_allowed: bool = False
    # Serializes exec / copy-in / copy-out on the same session. Take it through
    # LeaseStore.locked() so a holder that outlives DELETE finishes the cleanup.
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Guards ``proc`` / ``deleted`` / ``kill_requested`` between the worker
    # thread running exec and a concurrent DELETE. Never held while waiting.
    state_lock: threading.Lock = field(default_factory=threading.Lock)
    # Requests that hold or wait for ``lock``. Guarded by LeaseStore._guard.
    inflight: int = 0
    proc: subprocess.Popen | None = None
    deleted: bool = False
    kill_requested: bool = False
    # Set once the final cleanup (kill uid, remove trees, free uid) is claimed.
    finalized: bool = False


class LeaseStore:
    def __init__(
        self,
        *,
        sessions_root: str,
        max_sessions: int = 1,
        lease_ttl_s: float = 900,
        enable_uid_isolation: bool = False,
        default_uid: int = 65534,
        max_uids: int = DEFAULT_MAX_UIDS,
        clock: Callable[[], float] | None = None,
        geteuid: Callable[[], int] | None = None,
        delete_wait_s: float = DEFAULT_DELETE_WAIT_S,
        uid_killer: Callable[..., bool] | None = None,
        uid_scanner: Callable[[int], list[int]] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        if max_sessions > 1 and not enable_uid_isolation:
            raise RuntimeError("max_sessions > 1 requires enable_uid_isolation")
        self.sessions_root = sessions_root
        self.max_sessions = max_sessions
        self.lease_ttl_s = lease_ttl_s
        self.enable_uid_isolation = enable_uid_isolation
        self.default_uid = default_uid
        self.max_uids = max_uids
        self._clock = clock or time.monotonic
        self._geteuid = geteuid or os.geteuid
        self.delete_wait_s = delete_wait_s
        self._sleep = sleep or time.sleep
        # Killing by uid needs root (the helper drops to the session uid) and
        # only makes sense when each session has a uid of its own.
        uid_kill_on = enable_uid_isolation and self._geteuid() == 0
        self._uid_killer = uid_killer or (kill_uid if uid_kill_on else None)
        self._uid_scanner = uid_scanner or (uid_processes if uid_kill_on else None)
        self._leases: dict[str, Lease] = {}
        # uids whose processes may have survived a failed kill; never reissued.
        self._quarantined_uids: set[int] = set()
        # uids of deleted leases whose cleanup has not finished yet.
        self._releasing_uids: set[int] = set()
        self._guard = threading.Lock()
        os.makedirs(self.sessions_root, exist_ok=True)
        if self.enable_uid_isolation:
            os.chmod(self.sessions_root, 0o711)

    def _now(self) -> float:
        return self._clock()

    # ---- reaping ----------------------------------------------------------------

    def reap_expired(self) -> None:
        now = self._now()
        with self._guard:
            expired = [
                sid
                for sid, lease in self._leases.items()
                if lease.inflight == 0 and now - lease.last_active > self.lease_ttl_s
            ]
        for sid in expired:
            self.delete(
                sid, lease_token=None, force=True, reason="idle", only_if_idle=True
            )

    # ---- create -----------------------------------------------------------------

    def _allocate_uid(self) -> int:
        """Lowest uid in [UID_BASE, UID_BASE + max_uids) not held by a live lease.

        uids still being released or quarantined are never handed out.
        """
        used = (
            {lease.uid for lease in self._leases.values()}
            | self._quarantined_uids
            | self._releasing_uids
        )
        for uid in range(UID_BASE, UID_BASE + self.max_uids):
            if uid not in used:
                return uid
        raise CapacityError()

    def create(self) -> Lease:
        self.reap_expired()
        with self._guard:
            if len(self._leases) >= self.max_sessions:
                raise CapacityError()
            uid = (
                self._allocate_uid() if self.enable_uid_isolation else self.default_uid
            )
            session_id = str(uuid.uuid4())
            work_dir = os.path.join(self.sessions_root, session_id)
            home_dir = os.path.join(self.sessions_root, session_id + ".home")
            now = self._now()
            lease = Lease(
                session_id=session_id,
                lease_token=uuid.uuid4().hex + uuid.uuid4().hex,
                work_dir=work_dir,
                home_dir=home_dir,
                created_at=now,
                last_active=now,
                uid=uid,
            )
            # Reserve the slot and uid before touching the disk so concurrent
            # creates cannot both pass the capacity check or share a uid.
            self._leases[session_id] = lease
            slots = len(self._leases)
        try:
            self._prepare_dirs(lease)
        except OSError:
            with self._guard:
                self._leases.pop(session_id, None)
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(home_dir, ignore_errors=True)
            raise
        _log.info(
            "session created session_id=%s uid=%s slots=%s/%s isolation=%s",
            session_id,
            uid,
            slots,
            self.max_sessions,
            self.enable_uid_isolation,
        )
        return lease

    def _prepare_dirs(self, lease: Lease) -> None:
        os.makedirs(lease.work_dir, exist_ok=True)
        if self.enable_uid_isolation:
            # Keep the work tree root-owned until exec: supervisor drops
            # DAC_OVERRIDE, so copy-in cannot write a 0700 directory already
            # chown'ed to the session uid.
            os.chmod(lease.work_dir, 0o700)
        else:
            os.chmod(lease.work_dir, 0o755)
        os.makedirs(lease.home_dir, exist_ok=True)
        os.chmod(lease.home_dir, 0o700)
        # Only the session uid ever writes HOME, so it is owned by that uid for
        # the whole lease (copy-in never targets it).
        if self._geteuid() == 0 and lease.uid != 0:
            os.chown(lease.home_dir, lease.uid, lease.uid)

    # ---- lookup / in-flight accounting -------------------------------------------

    def get(self, session_id: str, lease_token: str) -> Lease:
        self.reap_expired()
        with self._guard:
            lease = self._lookup(session_id, lease_token)
            lease.last_active = self._now()
        return lease

    def acquire(self, session_id: str, lease_token: str) -> Lease:
        """Look up a lease and mark one request in flight on it.

        Lookup and the in-flight increment happen under one guard so the idle
        reaper cannot remove the lease in between. Pair with ``release``.
        """
        self.reap_expired()
        with self._guard:
            lease = self._lookup(session_id, lease_token)
            lease.inflight += 1
            lease.last_active = self._now()
        return lease

    def release(self, lease: Lease) -> None:
        """End one in-flight request; the idle clock restarts when work finishes."""
        with self._guard:
            lease.inflight = max(lease.inflight - 1, 0)
            lease.last_active = self._now()

    def _lookup(self, session_id: str, lease_token: str) -> Lease:
        lease = self._leases.get(session_id)
        if lease is None:
            raise UnknownLeaseError()
        if lease.lease_token != lease_token:
            raise ForbiddenLeaseError()
        return lease

    def quarantine_uid(self, uid: int, reason: str = "kill_failed") -> None:
        """Never hand ``uid`` to a new session again (a process may still run as it)."""
        if not self.enable_uid_isolation:
            return
        with self._guard:
            self._quarantined_uids.add(uid)
        _log.error("uid quarantined uid=%s reason=%s", uid, reason)

    # ---- per-uid process cleanup -----------------------------------------------------

    def kill_uid_processes(self, lease: Lease, reason: str) -> None:
        """SIGKILL every process running as the lease's uid (no-op without uid kill).

        Catches background jobs and setsid escapes that a process-group kill misses.
        """
        if self._uid_killer is None:
            return
        self._uid_killer(lease.uid, session_id=lease.session_id, reason=reason)

    def _uid_clear(self, lease: Lease, reason: str) -> bool:
        """Kill the uid's processes until none is left. True when the uid is clean."""
        if self._uid_killer is None or self._uid_scanner is None:
            return True
        for attempt in range(_UID_KILL_ROUNDS):
            self._uid_killer(lease.uid, session_id=lease.session_id, reason=reason)
            if not self._uid_scanner(lease.uid):
                return True
            if attempt + 1 < _UID_KILL_ROUNDS:
                self._sleep(_UID_KILL_PAUSE_S)
        left = self._uid_scanner(lease.uid)
        if not left:
            return True
        _log.error(
            "uid still has processes session_id=%s uid=%s pids=%s",
            lease.session_id,
            lease.uid,
            left[:20],
        )
        return False

    # ---- session lock -------------------------------------------------------------

    @contextmanager
    def locked(self, lease: Lease) -> Iterator[Lease]:
        """Hold ``lease.lock``; if the lease was deleted meanwhile, finish its cleanup.

        DELETE does not wait forever for a busy lock: when it gives up, the
        holder that releases the lock after DELETE removes the trees and frees
        the uid, so nothing is written into a tree after it was removed.
        """
        lease.lock.acquire()
        try:
            yield lease
        finally:
            try:
                if lease.deleted:
                    self._finalize(lease)
            finally:
                lease.lock.release()

    def _finalize(self, lease: Lease) -> None:
        """Final cleanup of a deleted lease. Caller holds ``lease.lock``. Runs once."""
        with lease.state_lock:
            if lease.finalized:
                return
            lease.finalized = True
        clean = self._uid_clear(lease, reason="delete")
        self._remove_tree(lease.work_dir)
        if lease.home_dir:
            self._remove_tree(lease.home_dir)
        if not clean:
            self.quarantine_uid(lease.uid, reason="processes_left")
        with self._guard:
            self._releasing_uids.discard(lease.uid)

    # ---- delete -----------------------------------------------------------------

    def delete(
        self,
        session_id: str,
        lease_token: str | None,
        *,
        force: bool = False,
        reason: str = "",
        only_if_idle: bool = False,
    ) -> None:
        with self._guard:
            lease = self._leases.get(session_id)
            if lease is None:
                if force:
                    return
                raise UnknownLeaseError()
            if not force and lease.lease_token != lease_token:
                raise ForbiddenLeaseError()
            # Re-check under the guard: a request may have started or finished
            # on this lease since reap_expired took its snapshot.
            if only_if_idle and (
                lease.inflight > 0
                or self._now() - lease.last_active <= self.lease_ttl_s
            ):
                return
            self._leases.pop(session_id, None)
            # Keep the uid out of the pool until no process of it is left.
            if self.enable_uid_isolation:
                self._releasing_uids.add(lease.uid)
            remaining = len(self._leases)
        # Mark the lease deleted and kill its processes first so that a running
        # exec returns promptly and releases lease.lock.
        with lease.state_lock:
            lease.deleted = True
            proc = lease.proc
            if proc is not None:
                lease.kill_requested = True
        # Check returncode, not poll(): poll() would reap the child here and the
        # exec thread would lose its wait4 rusage (needed for killed_reason).
        if proc is not None and proc.returncode is None:
            if not kill_group(proc, session_id=session_id, reason="delete"):
                self.quarantine_uid(lease.uid)
        self.kill_uid_processes(lease, reason="delete")
        # Remove the trees only while holding lease.lock: a copy-in or exec
        # holding it would otherwise recreate the tree after rmtree.
        if lease.lock.acquire(timeout=max(self.delete_wait_s, 0)):
            try:
                self._finalize(lease)
            finally:
                lease.lock.release()
            finished = "done"
        else:
            # The holder sees deleted=True when it leaves locked() and finalizes.
            finished = "handed_to_holder"
        _log.info(
            "session deleted session_id=%s reason=%s cleanup=%s slots=%s/%s",
            session_id,
            reason or ("force" if force else "client"),
            finished,
            remaining,
            self.max_sessions,
        )

    def _remove_tree(self, path: str) -> None:
        if not os.path.lexists(path):
            return
        if self._geteuid() == 0:
            # The tree may be owned by the session uid (exec in flight, or HOME):
            # take it back first so rmtree works without DAC_OVERRIDE.
            try:
                chown_tree(path, 0, 0, owner_rwx=True)
            except OSError as exc:
                _log.warning("reclaim tree failed path=%s error=%r", path, exc)
        shutil.rmtree(path, onerror=_log_rmtree_error)

    def expires_at_iso(self, lease: Lease) -> str:
        wall = datetime.now(UTC).timestamp() + max(
            self.lease_ttl_s - (self._now() - lease.last_active), 0
        )
        return datetime.fromtimestamp(wall, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_rmtree_error(_func, path, exc_info) -> None:
    _log.warning("remove session tree failed path=%s error=%r", path, exc_info[1])


class CapacityError(Exception):
    pass


class UnknownLeaseError(Exception):
    pass


class ForbiddenLeaseError(Exception):
    pass
