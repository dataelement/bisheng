from sqlalchemy.dialects import registry
from . import base, dmPython, types
from types import ModuleType
import sqlalchemy
from .base import dmsessionmaker, dmSession
current_version = sqlalchemy.__version__.split('b')[0].split('rc')[0].split('.post')[0].split('beta')[0]

current_ver = list(map(int, current_version.split('.')))

def get_async_info():
    from . import dmAsync
    dm_async = type(
        "dm_async", (ModuleType,), {"dialect": dmAsync.dialect_async}
    )

if current_ver[0] > 2 and len(current_ver) == 3:
    get_async_info()
elif current_ver[0] == 2:
    if current_ver[1] > 0:
        get_async_info()
    else:
        if current_ver[2] > 22:
            get_async_info()

base.dialect = dialect = dmPython.dialect

from .types import \
    VARCHAR, NVARCHAR, CHAR, DATE, DATETIME, NUMBER,\
    BLOB, BFILE, CLOB, NCLOB, TIMESTAMP, JSON,\
    FLOAT, DOUBLE_PRECISION, LONGVARCHAR, INTERVAL,\
    VARCHAR2, NVARCHAR2, ROWID, VECTOR, VectorAdaptor
from .vector import VectorWordSeek, VectorImageSeek

from .base import dialect

__all__ = (
    'VARCHAR', 'NVARCHAR', 'CHAR', 'DATE', 'DATETIME', 'NUMBER',
    'BLOB', 'BFILE', 'CLOB', 'NCLOB', 'TIMESTAMP', 'JSON',
    'FLOAT', 'DOUBLE_PRECISION', 'dialect', 'INTERVAL',
    'VARCHAR2', 'NVARCHAR2', 'ROWID', 'VECTOR', 'VectorAdaptor',
    'VectorWordSeek', 'VectorImageSeek'
)
