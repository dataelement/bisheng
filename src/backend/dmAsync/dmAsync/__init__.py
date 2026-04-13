import re
import sys
import warnings
from collections import namedtuple

from .connection import (
    Connection,
    Cursor,
    DefaultCompiler,
    IsolationCompiler,
    IsolationLevel,
    ReadCommittedCompiler,
    RepeatableReadCompiler,
    SerializableCompiler,
    Transaction,
    connect,
    disconnect,
)
from .pool import Pool, create_pool
from .utils import get_running_loop

warnings.filterwarnings(
    "always",
    ".*",
    category=ResourceWarning,
    module=r"aiopg(\.\w+)+",
    append=False,
)

__all__ = (
    "connect",
    "create_pool",
    "get_running_loop",
    "Connection",
    "Cursor",
    "Pool",
    "version",
    "version_info",
    "IsolationLevel",
    "Transaction",
)

__version__ = "0.1.0"

version = f"{__version__}, Python {sys.version}"

VersionInfo = namedtuple(
    "VersionInfo", "major minor micro releaselevel serial"
)


def _parse_version(ver: str) -> VersionInfo:
    RE = (
        r"^"
        r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<micro>\d+)"
        r"((?P<releaselevel>[a-z]+)(?P<serial>\d+)?)?"
        r"$"
    )
    match = re.match(RE, ver)
    if not match:
        raise ImportError(f"Invalid package version {ver}")
    try:
        major = int(match.group("major"))
        minor = int(match.group("minor"))
        micro = int(match.group("micro"))
        levels = {"rc": "candidate", "a": "alpha", "b": "beta", None: "final"}
        releaselevel = levels[match.group("releaselevel")]
        serial = int(match.group("serial")) if match.group("serial") else 0
        return VersionInfo(major, minor, micro, releaselevel, serial)
    except Exception as e:
        raise ImportError(f"Invalid package version {ver}") from e


version_info = _parse_version(__version__)

(
    connect,
    create_pool,
    Connection,
    Cursor,
    Pool,
    IsolationLevel,
    Transaction,
    get_running_loop,
    IsolationCompiler,
    DefaultCompiler,
    ReadCommittedCompiler,
    RepeatableReadCompiler,
    SerializableCompiler,
)
