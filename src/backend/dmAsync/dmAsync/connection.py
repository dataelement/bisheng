import abc
import asyncio
import datetime
import enum
import errno
import platform
import sys
import traceback
import uuid
import warnings
import weakref
from collections.abc import Mapping
from types import TracebackType
from typing import (
    Any,
    Callable,
    Generator,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    cast,
)

import dmPython

from .log import logger
from .utils import (
    ClosableQueue,
    _ContextManager,
    create_completed_future,
    get_running_loop,
)

WSAENOTSOCK = 10038

def connect(host=None, user=None, password=None, port=None, dsn=None, autoCommit=True,
            connection_timeout=0, login_timeout=5, loop=None, **kwargs):
    connection = Connection(host=host, user=user, password=password, port=port, dsn=dsn, autoCommit=autoCommit,
                            connection_timeout=connection_timeout, login_timeout=login_timeout, loop=loop, **kwargs)

    return connection

async def disconnect(c: "Connection") -> None:
    await c.close()

def _is_bad_descriptor_error(os_error: OSError) -> bool:
    if platform.system() == "Windows":  # pragma: no cover
        winerror = int(getattr(os_error, "winerror", 0))
        return winerror == WSAENOTSOCK
    return os_error.errno == errno.EBADF

class IsolationCompiler(abc.ABC):
    __slots__ = ("_isolation_level", "_readonly", "_deferrable")

    def __init__(
        self, isolation_level: Optional[str], readonly: bool, deferrable: bool
    ):
        self._isolation_level = isolation_level
        self._readonly = readonly
        self._deferrable = deferrable

    @property
    def name(self) -> str:
        return self._isolation_level or "Unknown"

    def savepoint(self, unique_id: str) -> str:
        return f"SAVEPOINT {unique_id}"

    def release_savepoint(self, unique_id: str) -> str:
        return f"RELEASE SAVEPOINT {unique_id}"

    def rollback_savepoint(self, unique_id: str) -> str:
        return f"ROLLBACK TO SAVEPOINT {unique_id}"

    def commit(self) -> str:
        return "COMMIT"

    def rollback(self) -> str:
        return "ROLLBACK"

    def begin(self) -> str:
        query = "START TRANSACTION"
        if self._isolation_level is not None:
            query += f" ISOLATION LEVEL {self._isolation_level.upper()}"
            if self._readonly:
                query += ", READ ONLY"
        elif self._readonly:
            query += " READ ONLY"

        return query

    def __repr__(self) -> str:
        return self.name

class ReadCommittedCompiler(IsolationCompiler):
    __slots__ = ()

    def __init__(self, readonly: bool, deferrable: bool):
        super().__init__("Read committed", readonly, deferrable)


class RepeatableReadCompiler(IsolationCompiler):
    __slots__ = ()

    def __init__(self, readonly: bool, deferrable: bool):
        super().__init__("Repeatable read", readonly, deferrable)

class SerializableCompiler(IsolationCompiler):
    __slots__ = ()

    def __init__(self, readonly: bool, deferrable: bool):
        super().__init__("Serializable", readonly, deferrable)

class DefaultCompiler(IsolationCompiler):
    __slots__ = ()

    def __init__(self, readonly: bool, deferrable: bool):
        super().__init__(None, readonly, deferrable)

    @property
    def name(self) -> str:
        return "Default"

class IsolationLevel(enum.Enum):
    serializable = SerializableCompiler
    repeatable_read = RepeatableReadCompiler
    read_committed = ReadCommittedCompiler
    default = DefaultCompiler

    def __call__(self, readonly: bool, deferrable: bool) -> IsolationCompiler:
        return self.value(readonly, deferrable)  # type: ignore

async def _release_savepoint(t: "Transaction") -> None:
    await t.release_savepoint()


async def _rollback_savepoint(t: "Transaction") -> None:
    await t.rollback_savepoint()

class Transaction:
    __slots__ = ("_cursor", "_is_begin", "_isolation", "_unique_id")

    def __init__(
        self,
        cursor: "Cursor",
        isolation_level: Callable[[bool, bool], IsolationCompiler],
        readonly: bool = False,
        deferrable: bool = False,
    ):
        self._cursor = cursor
        self._is_begin = False
        self._unique_id: Optional[str] = None
        self._isolation = isolation_level(readonly, deferrable)

    @property
    def is_begin(self) -> bool:
        return self._is_begin

    async def begin(self) -> "Transaction":
        if self._is_begin:
            raise RuntimeError("The transaction has been initiated!")
        self._is_begin = True
        await self._cursor.execute(self._isolation.begin())
        return self

    async def commit(self) -> None:
        self._check_commit_rollback()
        await self._cursor.execute(self._isolation.commit())
        self._is_begin = False

    async def rollback(self) -> None:
        self._check_commit_rollback()
        if not self._cursor.closed:
            await self._cursor.execute(self._isolation.rollback())
        self._is_begin = False

    async def rollback_savepoint(self) -> None:
        self._check_release_rollback()
        if not self._cursor.closed:
            await self._cursor.execute(
                self._isolation.rollback_savepoint(
                    self._unique_id  # type: ignore
                )
            )
        self._unique_id = None

    async def release_savepoint(self) -> None:
        self._check_release_rollback()
        await self._cursor.execute(
            self._isolation.release_savepoint(self._unique_id)  # type: ignore
        )
        self._unique_id = None

    async def savepoint(self) -> "Transaction":
        self._check_commit_rollback()
        if self._unique_id is not None:
            raise RuntimeError("Savepoint name is not None")

        self._unique_id = f"s{uuid.uuid1().hex}"
        await self._cursor.execute(self._isolation.savepoint(self._unique_id))

        return self

    def _savepoint(self) -> _ContextManager["Transaction"]:
        return _ContextManager[Transaction](
            self.savepoint(),
            _release_savepoint,
            _rollback_savepoint,
        )

    def _check_commit_rollback(self) -> None:
        if not self._is_begin:
            raise RuntimeError("The transaction has not yet started")

    def _check_release_rollback(self) -> None:
        self._check_commit_rollback()
        if self._unique_id is None:
            raise RuntimeError("Savepoint name is None")

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"transaction={self._isolation} id={id(self):#x}>"
        )

    def __del__(self) -> None:
        if self._is_begin:
            warnings.warn(
                f"You have not closed transaction {self!r}", ResourceWarning
            )

        if self._unique_id is not None:
            warnings.warn(
                f"You have not closed savepoint {self!r}", ResourceWarning
            )

    async def __aenter__(self) -> "Transaction":
        return await self.begin()

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

async def _commit_transaction(t: Transaction) -> None:
    await t.commit()

async def _rollback_transaction(t: Transaction) -> None:
    await t.rollback()

class Cursor:
    def __init__(
        self,
        conn: "Connection",
        impl: Any,
        timeout: float,
        echo: bool,
        isolation_level: Optional[IsolationLevel] = None,
    ):
        self._conn = conn
        self._impl = impl
        self._timeout = timeout
        self._echo = echo
        self._transaction = Transaction(
            self, isolation_level or IsolationLevel.default
        )
        self.closed =False

    @property
    def echo(self) -> bool:
        return self._echo

    @property
    def description(self) -> Optional[Sequence[Any]]:
        return self._impl.description

    def close(self) -> None:
        if not self.closed:
            self._impl.close()
            return create_completed_future(self.connection._loop)
        else:
            raise RuntimeError("The cursor has been closed")

    @property
    def connection(self) -> "Connection":
        return self._conn

    @property
    def raw(self) -> Any:
        return self._impl

    @property
    def name(self) -> str:
        return self._impl.name  # type: ignore

    @property
    def scrollable(self) -> Optional[bool]:
        return self._impl.scrollable

    @scrollable.setter
    def scrollable(self, val: bool) -> None:
        self._impl.scrollable = val

    @property
    def withhold(self) -> bool:
        return self._impl.withhold

    @withhold.setter
    def withhold(self, val: bool) -> None:
        # Not supported
        self._impl.withhold = val

    async def execute(
        self,
        operation: str,
        parameters: Any = None,
    ) -> None:
        self._conn.isexecuting = True
        self._conn._create_waiter("cursor.execute")
        if self._echo:
            logger.info(operation)
            logger.info("%r", parameters)
        try:
            await asyncio.to_thread(self._impl.execute, operation, parameters)
        except BaseException:
            self._conn._waiter = None
            raise
        finally:
            self._conn.isexecuting = False

    async def executemany(
        self,
        operation: str,
        parameters: Any = None,
    ) -> None:
        self._conn.isexecuting = True
        self._conn._create_waiter("cursor.executemany")
        if self._echo:
            logger.info(operation)
            logger.info("%r", parameters)
        try:
            await asyncio.to_thread(self._impl.executemany, operation, parameters)
        except BaseException:
            self._conn._waiter = None
            raise
        finally:
            self._conn.isexecuting = False

    async def callproc(
        self,
        procname: str,
        *args
    ) -> None:
        self._conn.isexecuting = True
        self._conn._create_waiter("cursor.callproc")
        if self._echo:
            logger.info("CALL %s", procname)
            logger.info("%r", *args)
        try:
            await asyncio.to_thread(self._impl.callproc, procname, *args)
        except BaseException:
            self._conn._waiter = None
            raise
        finally:
            self._conn.isexecuting = False

    async def callfunc(
        self,
        procname: str,
        *args
    ) -> None:
        self._conn.isexecuting = True
        self._conn._create_waiter("cursor.callfunc")
        if self._echo:
            logger.info("CALL %s", procname)
            logger.info("%r", *args)
        try:
            return await asyncio.to_thread(self._impl.callfunc, procname, *args)
        except BaseException:
            self._conn._waiter = None
            raise
        finally:
            self._conn.isexecuting = False

    def begin(self) -> _ContextManager[Transaction]:
        return _ContextManager[Transaction](
            self._transaction.begin(),
            _commit_transaction,
            _rollback_transaction,
        )

    def begin_nested(self) -> _ContextManager[Transaction]:
        if self._transaction.is_begin:
            return self._transaction._savepoint()

        return _ContextManager[Transaction](
            self._transaction.begin(),
            _commit_transaction,
            _rollback_transaction,
        )

    def mogrify(self, operation: str, parameters: Any = None) -> bytes:
        ret = self._impl.mogrify(operation, parameters)
        assert (
            not self._conn.isexecuting
        ), "Don't support server side mogrify"
        return ret

    async def prepare(self, operation: str) -> None:
        await asyncio.to_thread(self._impl.prepare, operation)

    async def executedirect(
            self,
            operation: str,
    ) -> None:
        self._conn.isexecuting = True
        self._conn._create_waiter("cursor.executedirect")
        if self._echo:
            logger.info(operation)
        try:
            await asyncio.to_thread(self._impl.executedirect, operation)
        except BaseException:
            self._conn._waiter = None
            raise
        finally:
            self._conn.isexecuting = False

    async def setinputsizes(self, *args) -> None:
        return await asyncio.to_thread(self._impl.setinputsizes, *args)

    async def setoutputsize(self, *args) -> None:
        return await asyncio.to_thread(self._impl.setoutputsize, *args)

    async def fetchone(self) -> Any:
        ret = await asyncio.to_thread(self._impl.fetchone)
        return ret

    async def next(self) -> Any:
        ret = await asyncio.to_thread(self._impl.next)
        return ret

    async def nextset(self) -> None:
        await asyncio.to_thread(self._impl.nextset)

    async def fetchmany(self, size: Optional[int] = None) -> List[Any]:
        if size is None:
            size = self._impl.arraysize
        ret = await asyncio.to_thread(self._impl.fetchmany, size)
        assert (
            not self._conn.isexecuting
        ), "Don't support server side cursors yet"
        return ret

    async def fetchall(self) -> List[Any]:
        ret = await asyncio.to_thread(self._impl.fetchall)
        return ret

    async def scroll(self, value: int, mode: str = "relative") -> None:
        await asyncio.to_thread(self._impl.scroll, value, mode)

    @property
    def arraysize(self) -> int:
        return self._impl.arraysize

    @arraysize.setter
    def arraysize(self, val: int) -> None:
        self._impl.arraysize = val

    @property
    def itersize(self) -> int:
        return self._impl.itersize

    @itersize.setter
    def itersize(self, val: int) -> None:
        self._impl.itersize = val

    @property
    def rowcount(self) -> int:
        return self._impl.rowcount

    @property
    def rownumber(self) -> int:
        return self._impl.rownumber

    @property
    def lastrowid(self) -> int:
        return self._impl.lastrowid

    @property
    def query(self) -> Optional[str]:
        return self._impl.query

    @property
    def timeout(self) -> float:
        return self._timeout

    def __aiter__(self) -> "Cursor":
        return self

    async def __anext__(self) -> Any:
        ret = await self.fetchone()
        if ret is not None:
            return ret
        raise StopAsyncIteration

    async def __aenter__(self) -> "Cursor":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await asyncio.to_thread(self.close)

    def __repr__(self) -> str:
        return (
            f"<"
            f"{type(self).__module__}::{type(self).__name__} "
            f"name={self.name}, "
            f"closed={self.closed}"
            f">"
        )

async def _close_cursor(c: Cursor) -> None:
    await asyncio.to_thread(c.close)

class Connection:
    def __init__(self, host=None, user=None, password=None, port=None, dsn=None,
                autoCommit=True, connection_timeout=0, login_timeout=5, loop=None, **kwargs):

        if loop is None:
            self._loop = get_running_loop()
        else:
            self._loop = loop
        self._waiter: Optional[
            "asyncio.Future[None]"
        ] = self._loop.create_future()
        self._waiter: Optional[
            "asyncio.Future[None]"
        ] = self._loop.create_future()

        self.init_connect_with_param(host, user, password, port, dsn, autoCommit=autoCommit,
                                connection_timeout=connection_timeout, login_timeout=login_timeout, **kwargs)
        self._fileno: Optional[int] = 0
        self.isexecuting = False
        self._last_usage = self._loop.time()
        self._notifies = asyncio.Queue()
        self._notifies_proxy = ClosableQueue(self._notifies, self._loop)
        self._weakref = weakref.ref(self)


        if self._loop.get_debug():
            self._source_traceback = traceback.extract_stack(sys._getframe(1))

    def init_connect_with_param(self, host, user, password, port, dsn, autoCommit=True,
                                connection_timeout=0, login_timeout=5, **kwargs):
        # dsn与host互斥，如果存在dsn，则忽略port设置的port，
        self._user = user if user else 'SYSDBA'
        if dsn is not None:
            if host is not None:
                raise ValueError("Only one of dsn and host can be set at the same time")
            if type(dsn) is not str:
                raise ValueError("The dsn value is set incorrectly")
            else:
                ipv6_flag = False
                if dsn.startswith('[') and ']:' in dsn:
                    ipv6_flag = True
                    dsn_array = dsn.split(']:', 1)
                else:
                    dsn_array = dsn.split(':', 1)
                if len(dsn_array) != 2:
                    raise ValueError("The dsn value is set incorrectly")
                self._dsn = dsn
                if ipv6_flag:
                    self._host = dsn_array[0] + ']' # 分割时会去掉分隔符，此处补充]
                else:
                    self._host = dsn_array[0]
                try:
                    port_num = int(dsn_array[1])
                    self._port = port_num
                except Exception:
                    raise ValueError("The port value is set incorrectly")
        else:
            self._host = host if host else 'localhost'
            self._port = port if port else 5236
            self._dsn = self._host + ':' + str(self._port)

        if password is None:
            raise ValueError("Password cannot be empty")
        else:
            self._password = password

        self._autoCommit = autoCommit
        self._connection_timeout = connection_timeout
        self._login_timeout = login_timeout
        self._timeout = connection_timeout

        self._conn = dmPython.connect(user=self._user, password=self._password, autoCommit=autoCommit, dsn=self._dsn,
                                      connection_timeout=connection_timeout, login_timeout=login_timeout, **kwargs)

        self.version = self.raw.version
        self.max_identifier_length = self.raw.max_identifier_length
        self.outputtypehandler = self.raw.outputtypehandler
        self.stmtcachesize = self.raw.stmtcachesize
        self.closed = False

    @staticmethod
    def _ready(weak_self: "weakref.ref[Any]") -> None:
        self = cast(Connection, weak_self())


    def _fatal_error(self, message: str) -> None:
        self._loop.call_exception_handler(
            {
                "message": message,
                "connection": self,
            }
        )
        self.close()

    def _create_waiter(self, func_name: str) -> "asyncio.Future[None]":
        self._waiter = self._loop.create_future()
        return self._waiter

    async def _poll(
        self, waiter: "asyncio.Future[None]", timeout: float
    ) -> None:
        assert waiter is self._waiter, (waiter, self._waiter)
        self._ready(self._weakref)

        await asyncio.wait_for(self._waiter, timeout)
        self._waiter = None

    async def get_closed(self):
        if self._conn is not None:
            try:
                await asyncio.to_thread(self._conn.ping)
                self.closed = False
            except Exception:
                self.closed = True

    def cursor(
        self,
        name: Optional[str] = None,
        cursor_factory: Any = None,
        scrollable: Optional[bool] = None,
        withhold: bool = False,
        timeout: Optional[float] = None,
        isolation_level: Optional[IsolationLevel] = None,
    ) -> _ContextManager[Cursor]:
        self._last_usage = self._loop.time()
        coro = self._cursor(
            name=name,
            cursor_factory=cursor_factory,
            scrollable=scrollable,
            withhold=withhold,
            timeout=timeout,
            isolation_level=isolation_level,
        )
        return _ContextManager[Cursor](coro, _close_cursor)

    async def _cursor(
        self,
        name: Optional[str] = None,
        cursor_factory: Any = None,
        scrollable: Optional[bool] = None,
        withhold: bool = False,
        timeout: Optional[float] = None,
        isolation_level: Optional[IsolationLevel] = None,
    ) -> Cursor:
        if timeout is None:
            timeout = self._timeout

        impl = await self._cursor_impl(
            name=name,
            cursor_factory=cursor_factory,
            scrollable=scrollable,
            withhold=withhold,
        )
        cursor = Cursor(self, impl, timeout, isolation_level)
        return cursor

    async def _cursor_impl(
        self,
        name: Optional[str] = None,
        cursor_factory: Any = None,
        scrollable: Optional[bool] = None,
        withhold: bool = False,
    ) -> Any:
        impl = self._conn.cursor()

        return impl

    def _close(self) -> None:
        self._conn.close()

    def close(self) -> "asyncio.Future[None]":
        self._close()
        return create_completed_future(self._loop)

    def disconnect(self) -> "asyncio.Future[None]":
        self._close()
        return create_completed_future(self._loop)

    @property
    def raw(self) -> Any:
        return self._conn

    async def commit(self) -> None:
        try:
            await asyncio.to_thread(self._conn.commit)
        except Exception:
            raise

    async def rollback(self) -> None:
        try:
            await asyncio.to_thread(self._conn.rollback)
        except Exception:
            raise

    async def debug(self, *args) -> None:
        try:
            await asyncio.to_thread(self._conn.debug, *args)
        except Exception:
            raise

    async def shutdown(self, *args) -> None:
        try:
            await asyncio.to_thread(self._conn.shutdown, *args)
        except Exception:
            raise

    async def explain(self, operation: str):
        try:
            return await asyncio.to_thread(self._conn.explain, operation)
        except Exception:
            raise

    async def ping(self, reconnect: bool):
        await asyncio.to_thread(self._conn.ping, reconnect)

    async def xid(
        self, format_id: int, gtrid: str, bqual: str
    ) -> Tuple[int, str, str]:
        raise NotImplementedError("Unsupported methods!")

    async def tpc_begin(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Unsupported methods!")

    async def tpc_prepare(self) -> None:
        raise NotImplementedError("Unsupported methods!")

    async def tpc_commit(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Unsupported methods!")

    async def tpc_rollback(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Unsupported methods!")

    async def tpc_recover(self) -> None:
        raise NotImplementedError("Unsupported methods!")

    async def cancel(self) -> None:
        raise NotImplementedError("Unsupported methods!")

    async def reset(self) -> None:
        raise NotImplementedError("Unsupported methods!")

    @property
    def dsn(self) -> Optional[str]:
        return self._dsn

    async def set_session(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Unsupported methods!")

    @property
    def autocommit(self) -> bool:
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, val: bool) -> None:
        self._conn.autocommit = val

    @property
    def isolation_level(self) -> int:
        return self._conn.txn_isolation

    async def set_isolation_level(self, val: int) -> None:
        self._conn.txn_isolation = val

    @property
    def encoding(self) -> str:
        return self._conn.local_code  # type: ignore

    async def set_client_encoding(self, val: str) -> None:
        raise NotImplementedError("Unsupported methods!")

    @property
    def notices(self) -> List[str]:
        raise NotImplementedError("Unsupported methods!")

    @property
    def cursor_factory(self) -> Any:
        raise NotImplementedError("Unsupported methods!")

    async def get_backend_pid(self) -> int:
        raise NotImplementedError("Unsupported methods!")

    async def get_parameter_status(self, parameter: str) -> Optional[str]:
        raise NotImplementedError("Unsupported methods!")

    async def get_transaction_status(self) -> int:
        raise NotImplementedError("Unsupported methods!")

    @property
    def protocol_version(self) -> int:
        raise NotImplementedError("Unsupported methods!")

    @property
    def server_version(self) -> int:
        return self._conn.server_version

    @property
    def status(self) -> int:
        return self._conn.status  # type: ignore

    async def lobject(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("Unsupported methods!")

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def last_usage(self) -> float:
        return self._last_usage

    def __repr__(self) -> str:
        return (
            f"<"
            f"{type(self).__module__}::{type(self).__name__} "
            f">"
        )

    def __del__(self) -> None:
        try:
            _conn = self._conn
        except AttributeError:
            return
        if _conn is not None:
            try:
                _conn.ping()
                self.close()
                warnings.warn(f"Unclosed connection {self!r}", ResourceWarning)

                context = {"connection": self, "message": "Unclosed connection"}

                self._loop.call_exception_handler(context)
            except Exception:
                pass

    @property
    def notifies(self) -> ClosableQueue:
        return self._notifies_proxy

    async def _connect(self) -> "Connection":
        return self

    def __await__(self) -> Generator[Any, None, "Connection"]:
        return self._connect().__await__()

    async def __aenter__(self) -> "Connection":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()
