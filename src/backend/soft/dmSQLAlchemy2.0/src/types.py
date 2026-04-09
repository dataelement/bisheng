import json
from sqlalchemy import util, sql, ARRAY
from sqlalchemy import types as sqltypes
from sqlalchemy.types import VARCHAR, NVARCHAR, CHAR, \
    BLOB, CLOB, DATE, TIME, TIMESTAMP, FLOAT, BIGINT, String, Interval, VARBINARY
from .json import JSON, JSONPathType, JSONIndexType

class NCLOB(sqltypes.Text):
    __visit_name__ = 'NCLOB'


class VARCHAR2(VARCHAR):
    __visit_name__ = 'VARCHAR2'

NVARCHAR2 = NVARCHAR


class NUMBER(sqltypes.Numeric, sqltypes.Integer):
    __visit_name__ = 'NUMBER'

    def __init__(self, precision=None, scale=None, asdecimal=None):
        if asdecimal is None:
            asdecimal = bool(scale and scale > 0)

        super(NUMBER, self).__init__(
            precision=precision, scale=scale, asdecimal=asdecimal)

    def adapt(self, impltype):
        ret = super(NUMBER, self).adapt(impltype)
        # leave a hint for the DBAPI handler
        ret._is_dm_number = True
        return ret

    @property
    def _type_affinity(self):
        if bool(self.scale and self.scale > 0):
            return sqltypes.Numeric
        else:
            return sqltypes.Integer


class DOUBLE_PRECISION(sqltypes.Numeric):
    __visit_name__ = 'DOUBLE_PRECISION'

    def __init__(self, precision=None, asdecimal=None):
        if asdecimal is None:
            asdecimal = False

        super(DOUBLE_PRECISION, self).__init__(
            precision=precision, asdecimal=asdecimal)


class BFILE(sqltypes.LargeBinary):
    __visit_name__ = 'BFILE'

class ARRAYCLOB(ARRAY):
    def result_processor(self, dialect, coltype):
        def to_list(val):
            if val is not None:
                val = json.loads(val)
            return val

        return to_list
class LONGVARCHAR(sqltypes.Text):
    __visit_name__ = 'LONGVARCHAR'

class DATE(sqltypes.Date):
    __visit_name__ = 'DATE'

    def _compare_type_affinity(self, other):
        return other._type_affinity in (sqltypes.DateTime, sqltypes.Date)
    
class TIME(sqltypes.TIME):
    __visit_name__ = 'TIME'
    
    def __init__(self, timezone=False):
        super(TIME, self).__init__(timezone=timezone)
    
class DATETIME(sqltypes.DATETIME):
    __visit_name__ = 'DATETIME'
    

class INTERVAL(Interval):
    __visit_name__ = 'INTERVAL'

    def __init__(self,
                 year_precision=None,
                 to_month=False,
                 month_precision=None,
                 day_precision=None,
                 to_hour=False,
                 to_minute=False, 
                 hour_precision=None,
                 minute_precision=None,
                 second_precision=None,
                 native: bool = True):
        super(Interval, self).__init__()
        self.native = native
        self.year_precision = year_precision
        self.to_month = to_month
        self.month_precision = month_precision
        
        self.day_precision = day_precision
        self.to_hour = to_hour
        self.to_minute = to_minute
        self.hour_precision = hour_precision
        self.minute_precision = minute_precision
        self.second_precision = second_precision

    @classmethod
    def _adapt_from_generic_interval(cls, interval):
        return INTERVAL(day_precision=interval.day_precision,
                        second_precision=interval.second_precision)

    @property
    def _type_affinity(self):
        return sqltypes.Interval

class ROWID(sqltypes.TypeEngine):
    __visit_name__ = 'ROWID'

class _DMBoolean(sqltypes.Boolean):
    def get_dbapi_type(self, dbapi):
        return dbapi.NUMBER

class _DMNumeric(sqltypes.Numeric):
    pass
    
class _DMDate(sqltypes.Date):
    def bind_processor(self, dialect):
        return None

    def result_processor(self, dialect, coltype):
        def process(value):
            return value
        return process


class _LOBMixin(object):
    def result_processor(self, dialect, coltype):
        if not dialect.auto_convert_lobs:
            return None

        def process(value):
            if value is not None:
                if isinstance(value, dialect.dbapi.LOB):
                    return value.read()
                else:
                    return value
            else:
                return value
        return process


class _NativeUnicodeMixin(object):
      pass

    # we apply a connection output handler that returns
    # unicode in all cases, so the "native_unicode" flag
    # will be set for the default String.result_processor.


class _DMChar(_NativeUnicodeMixin, sqltypes.CHAR):
    def get_dbapi_type(self, dbapi):
        return dbapi.FIXED_STRING
    
class CHARACTER(sqltypes.CHAR):
    pass

class TINYINT(sqltypes.TypeEngine):
    __visit_name__ = 'TINYINT'

    def result_processor(self, dialect, coltype):
        def process(value):
            return value
        return process
    
class BYTE(TINYINT):
    pass

class _DMDOUBLE(sqltypes.DOUBLE):
    pass

class _DMDECIMAL(sqltypes.DECIMAL):
    pass

class _DMSMALLINT(sqltypes.SMALLINT):
    pass

class _DMBIGINT(sqltypes.BIGINT):
    pass

class _DMREAL(sqltypes.REAL):
    __visit_name__ = "REAL"

    def as_generic(self, allow_nulltype=False):
        return sqltypes.REAL

class BIT(sqltypes.TypeEngine):
    __visit_name__ = 'BIT'
    
    def result_processor(self, dialect, coltype):
        def process(value):
            return value
        return process
    
class TIMESTAMP(sqltypes.TIMESTAMP):
    __visit_name__ = 'DMTIMESTAMP'
    
    def __init__(self, timezone = False, local_timezone = False):
        self.timezone = timezone
        self.local_timezone = False
        
        if timezone:
            self.local_timezone = False
        else:
            self.local_timezone = local_timezone
            
        super(TIMESTAMP, self).__init__(timezone=timezone)

class _DMNVarChar(_NativeUnicodeMixin, sqltypes.NVARCHAR):
    def get_dbapi_type(self, dbapi):
        return getattr(dbapi, 'UNICODE_STRING', dbapi.STRING)

class _DMText(_LOBMixin, sqltypes.Text):
    def get_dbapi_type(self, dbapi):
        return dbapi.CLOB
    
class _DMBLOB(sqltypes.BLOB):
    
    __visit_name__ = 'BLOB'
    
    def get_dbapi_type(self, dbapi):
        return dbapi.BLOB
    
    def bind_processor(self, dialect):
        def process(value):
            if value is not None:
                if isinstance(value, dialect.dbapi.LOB):
                    return value.read()
                else:
                    return value
            else:
                return value
        return process    
    
    def result_processor(self, dialect, coltype):
        if not dialect.auto_convert_lobs:
            return None

        def process(value):
            if value is not None:
                if isinstance(value, dialect.dbapi.LOB):
                    return value.read()
                else:
                    return value
            else:
                return value
        return process
    
class IMAGE(sqltypes.TypeEngine):

    __visit_name__ = 'IMAGE'

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is not None:
                if isinstance(value, dialect.dbapi.LOB):
                    return value.read()
                else:
                    return value
            return value
        return process
    def get_dbapi_type(self, dbapi):
        return dbapi.LOB    

class _DMLongVarchar(_LOBMixin, LONGVARCHAR):
    def get_dbapi_type(self, dbapi):
        return dbapi.LONG_STRING

class _DMLongVarBinary(_LOBMixin, sqltypes.BLOB):
    __visit_name__ = 'LongVarBinary'
    def get_dbapi_type(self, dbapi):
        return dbapi.LOB 

class _DMString(_NativeUnicodeMixin, sqltypes.String):
    pass

class _DMEnum(_NativeUnicodeMixin, sqltypes.Enum):
    def bind_processor(self, dialect):
        enum_proc = sqltypes.Enum.bind_processor(self, dialect)

        def process(value):
            raw_str = enum_proc(value)
            return raw_str
        return process


class _DMUnicodeText(
        _LOBMixin, _NativeUnicodeMixin, sqltypes.UnicodeText):
    def get_dbapi_type(self, dbapi):
        return dbapi.CLOB

    def result_processor(self, dialect, coltype):
        lob_processor = _LOBMixin.result_processor(self, dialect, coltype)
        if lob_processor is None:
            return None

        string_processor = sqltypes.UnicodeText.result_processor(
            self, dialect, coltype)

        if string_processor is None:
            return lob_processor
        else:
            def process(value):
                return string_processor(lob_processor(value))
            return process


class _DMInteger(sqltypes.Integer):
    def result_processor(self, dialect, coltype):
        def to_int(val):
            if val is not None:
                val = float(val)
                val = int(val)
            return val
        return to_int

class DMBINARY(sqltypes.BINARY):
    def get_dbapi_type(self, dbapi):
        self.dbapi = dbapi
        return dbapi.BINARY

    def bind_processor(self, dialect):
        def process(value):
            if isinstance(value, dialect.dbapi.LOB):
                return value.read()
            
            if type(value) is dialect.dbapi.LOB:
                return value.read()
            
            if type(value) is bytes:
                return bytes(value)

            if value is None:
                return value
            
            return str(value)
        return process

class _DMBinary(sqltypes._Binary):
    def get_dbapi_type(self, dbapi):
        self.dbapi = dbapi
        return dbapi.BINARY

    def bind_processor(self, dialect):
        def process(value):
            if isinstance(value, dialect.dbapi.LOB):
                return value.read()
            
            if type(value) is dialect.dbapi.LOB:
                return value.read()
            
            if type(value) is bytes:
                return bytes(value)

            if value is None:
                return value

            return str(value)
        return process
    
    def result_processor(self, dialect, coltype):
        if not dialect.auto_convert_lobs:
                return None
    
        def process(value):
            if isinstance(value, dialect.dbapi.LOB):
                return value.read()  
            
            if type(value) is dialect.dbapi.LOB:
                return value.read()
            
            if type(value) is bytes:
                return bytes(value)

            if value is None:
                return value

            return str(value)            
                
        return process    

class _DMInterval(INTERVAL):
    def get_dbapi_type(self, dbapi):
        return dbapi.INTERVAL

class _DMRowid(ROWID):
    def get_dbapi_type(self, dbapi):
        return dbapi.ROWID
    
colspecs = {
    sqltypes.Boolean: _DMBoolean,
    sqltypes.Interval: INTERVAL,
    sqltypes.DateTime: DATE,
    sqltypes.Time: TIME,
    sqltypes.BLOB: _DMBLOB,
    sqltypes.BINARY: _DMBinary,
    sqltypes.JSON.JSONIndexType: JSONIndexType,
    sqltypes.JSON.JSONPathType: JSONPathType,
    sqltypes.JSON: JSON
}

ischema_names = {
    'VARCHAR2': VARCHAR,
    'VARCHAR':VARCHAR,
    'NVARCHAR2': NVARCHAR,
    'CHAR': CHAR,
    'DATE': DATE,
    'DATETIME': DATETIME,
    'NUMBER': NUMBER,
    'BLOB': _DMBLOB,
    'BFILE': BFILE,
    'CLOB': CLOB,
    'NCLOB': NCLOB,
    'TIME WITH TIME ZONE':TIME,
    'TIMESTAMP': TIMESTAMP,
    'TIMESTAMP WITH TIME ZONE': TIMESTAMP,
    'TIMESTAMP WITH LOCAL TIME ZONE': TIMESTAMP(local_timezone = True),
    'INTERVAL DAY TO SECOND': INTERVAL,
    'FLOAT': FLOAT,
    'DOUBLE PRECISION': DOUBLE_PRECISION,
    'LONG': LONGVARCHAR,
    'BIT': BIT,
    'TEXT': _DMText,
    'INTEGER': _DMInteger,
    'INT': _DMInteger,
    'BINARY':DMBINARY,
    'DOUBLE':_DMDOUBLE,
    'DECIMAL':_DMDECIMAL,
    'NUMERIC':_DMNumeric,
    'DEC':_DMDECIMAL,
    'REAL':_DMREAL,
    'TINYINT':_DMSMALLINT,
    'SMALLINT':_DMSMALLINT,
    'BIGINT':_DMBIGINT,
    'TIME':TIME,
    'JSON': JSON,
    'CHARACTER': CHAR,
    'ROWID': ROWID,
    'VARBINARY': VARBINARY,
}
