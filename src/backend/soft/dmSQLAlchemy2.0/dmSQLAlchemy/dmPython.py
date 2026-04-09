from __future__ import absolute_import

import re
import json
import random
import decimal
import ipaddress
from . import base as dm
from .globalvars import globalvars
from sqlalchemy.exc import DBAPIError
from importlib.metadata import version
import sqlalchemy.engine.result as _result
from sqlalchemy import types as sqltypes, util, exc
from .base import DMCompiler, DMDialect, DMExecutionContext, DMDialect_Adapter, DMMySQLDialect_Adapter, Quote_Method, No_Quote_Method, \
    NoCompatible_Mode, MySQLCompatible_Mode, TSQLCompatible_Mode, OracleCompatible_Mode
from sqlalchemy.engine import cursor as _cursor
from .types import _DMBinary, _DMBoolean, _DMChar, _DMDate, _DMEnum, \
     _DMInteger, _DMInterval, _DMLongVarchar, _DMNumeric, \
     _DMNVarChar, _DMRowid, _DMString, _DMText, _DMUnicodeText, INTERVAL, \
     LONGVARCHAR, ROWID, _DMBLOB, DMBINARY, ARRAYCLOB, JSON, JSONIndexType, JSONPathType,\
     VECTORTYPE, VECTOR

class DMCompiler_dmPython(DMCompiler):

    _dm_returning = False

    def bindparam_string(self, name, **kw):
        self.dialect.trace_process('DMCompiler_dmPython', 'bindparam_string', name, **kw)
        
        quote = getattr(name, 'quote', None)
        if quote is True or quote is not False and \
                self.preparer._bindparam_requires_quotes(name):
            quoted_name = '"%s"' % name
            self._quoted_bind_names[name] = quoted_name
            return DMCompiler.bindparam_string(self, name, **kw)
        else:
            return DMCompiler.bindparam_string(self, name, **kw)

    
class DMExecutionContext_dmPython(DMExecutionContext):
    out_parameters = None

    version_info = globalvars.get_var('DMPYTHON_VERSION').split(".")

    support_stream = int(version_info[0]) > 2 or (int(version_info[0]) == 2 and int(version_info[1]) > 5) or (int(version_info[0]) == 2 and int(version_info[1]) == 5 and int(version_info[2]) > 9)

    def _generate_out_parameter_vars(self):

        if self.compiled is not None:
            if hasattr(self.compiled, 'has_out_parameters') or hasattr(self.compiled, '_dm_returning'):
                if self.compiled.has_out_parameters or self.compiled._dm_returning or self.executemany:
                    if self.support_stream:
                        self.cursor.output_stream = 1

                    out_parameters = self.out_parameters
                    assert out_parameters is not None

                    len_params = len(self.parameters)

                    for bindparam in self.compiled.binds.values():
                        if bindparam.isoutparam:
                            name = self.compiled.bind_names[bindparam]
                            type_impl = bindparam.type.dialect_impl(self.dialect)

                            dbtype = type_impl.get_dbapi_type(self.dialect.dbapi)

                            if dbtype is None:
                                raise exc.InvalidRequestError(
                                    "Cannot create out parameter for "
                                    "parameter "
                                    "%r - its type %r is not supported by"
                                    " dmPython" % (bindparam.key, bindparam.type)
                                )

                            out_parameters[name] = self.cursor.var(
                                dbtype, arraysize=len_params
                            )

                            for i in range(len(self.parameters)):
                                param = self.parameters[i]
                                compiled_param = self.compiled_parameters[i]
                                keys_list = list(compiled_param.keys())
                                positiontup = self.compiled.positiontup
                                index = positiontup.index(name)
                                index_temp = index
                                for i in range(index_temp):
                                    if positiontup[i] not in keys_list:
                                        pattern = re.compile(r'^' + positiontup[i] + r'_\d+$')
                                        result = [item for item in keys_list if pattern.match(item)]
                                        index = (index - 1 + len(result))
                                if (type(compiled_param) == dict):
                                    param[index] = out_parameters[name]

    def pre_exec(self):
        self.dialect.trace_process('DMExecutionContext_dmPython', 'pre_exec')
        super().pre_exec()

        self.out_parameters = {}

        self._generate_out_parameter_vars()
        self._generate_cursor_outputtype_handler()

    def post_exec(self):
        if (
            self.compiled
            and self.compiled._dm_returning
        ):

            numcols = len(self.out_parameters)

            result_list = []

            if self.support_stream:
                for j in range(numcols):
                    temp_list = []
                    if (type(self.out_parameters[f"ret_{j}"]) != list):
                        temp_list.append(self.out_parameters[f"ret_{j}"])
                    else:
                        temp_list = self.out_parameters[f"ret_{j}"]
                    result_list.append(temp_list)
            else:
                for j in range(numcols):
                    temp_list = []
                    temp_list.append(self.out_parameters[f"ret_{j}"].getvalue())
                    result_list.append(temp_list)

            initial_buffer = list(zip(*result_list))

            fetch_strategy = _cursor.FullyBufferedCursorFetchStrategy(
                self.cursor,
                [
                    (entry.keyname, None)
                    for entry in self.compiled._result_columns
                ],
                initial_buffer=initial_buffer,
            )

            self.cursor_fetch_strategy = fetch_strategy


    def create_cursor(self):
        self.dialect.trace_process('DMExecutionContext_dmPython', 'create_cursor')

        c = self._dbapi_connection.cursor()
        if self.dialect.arraysize:
            c.arraysize = self.dialect.arraysize

        return c

    def _generate_cursor_outputtype_handler(self):
        output_handlers = {}

        if output_handlers:
            default_handler = self._dbapi_connection.outputtypehandler

            def output_type_handler(
                cursor, name, default_type, size, precision, scale
            ):
                if name in output_handlers:
                    return output_handlers[name](
                        cursor, name, default_type, size, precision, scale
                    )
                else:
                    return default_handler(
                        cursor, name, default_type, size, precision, scale
                    )

            self.cursor.outputtypehandler = output_type_handler

class DMDialect_dmPython(DMDialect):
    supports_statement_cache = True
    execution_ctx_cls = DMExecutionContext_dmPython
    statement_compiler = DMCompiler_dmPython
    insert_executemany_returning = True
    
    supports_sane_rowcount = True
    supports_sane_multi_rowcount = False

    supports_unicode_statements = True
    supports_unicode_binds = True

    # dmSession parse_type add_quote_all compatible_mode
    parse_stmt_func = None
    parse_module = DMDialect_Adapter
    quote_module = No_Quote_Method
    compatible_module = NoCompatible_Mode

    driver = "dmPython"

    def my_json_deserializer(self,value):
        import json
        if value is None:
            return None
        try:
            if isinstance(value,str):
                return json.loads(value)
        except Exception as e:
            print(e)
        try:
            return json.loads("{}".format(value))
        except Exception as e:
            print(e)
        return "{}".format(value)
    _json_deserializer = my_json_deserializer

    def my_json_serializer(self,value):
        return value

    _json_serializer=my_json_serializer

    colspecs = {
        sqltypes.Numeric: _DMNumeric,
        sqltypes.Date: _DMDate,
        sqltypes._Binary: _DMBinary,
        sqltypes.Boolean: _DMBoolean,
        sqltypes.BOOLEAN: _DMBoolean,
        sqltypes.Interval: _DMInterval,
        INTERVAL: _DMInterval,
        sqltypes.Text: _DMText,
        sqltypes.TEXT: _DMText,
        sqltypes.BLOB: _DMBLOB,
        sqltypes.String: _DMString,
        sqltypes.UnicodeText: _DMUnicodeText,
        sqltypes.CHAR: _DMChar,
        sqltypes.Enum: _DMEnum,
        sqltypes.BINARY: DMBINARY,
        sqltypes.JSON: JSON,
        sqltypes.JSON.JSONIndexType: JSONIndexType,
        sqltypes.JSON.JSONPathType: JSONPathType,
        LONGVARCHAR: _DMLongVarchar,

        sqltypes.Integer: _DMInteger,
        sqltypes.INTEGER: _DMInteger,

        sqltypes.Unicode: _DMNVarChar,
        sqltypes.NVARCHAR: _DMNVarChar,
        ROWID: _DMRowid,
        sqltypes.ARRAY: ARRAYCLOB,
        VECTORTYPE: VECTOR,
    }

    execute_sequence_format = list

    def __init__(self,
                 auto_convert_lobs=True,
                 coerce_to_decimal=True,
                 autocommit = False,
                 connection_timeout = 0,
                 arraysize=50,
                 **kwargs):
        DMDialect.__init__(self, **kwargs)
        self.arraysize = arraysize
        self.auto_convert_lobs = auto_convert_lobs
        self.autocommit = False
        self.connection_timeout = connection_timeout

        if hasattr(self.dbapi, 'version'):
            self.dmPython_ver = self._parse_dmPython_ver(self.dbapi.version)

        else:
            self.dmPython_ver = (0, 0)

        def types(*names):
            return set(
                getattr(self.dbapi, name, None) for name in names
            ).difference([None])

        self._dmPython_string_types = types("STRING", "UNICODE",
                                             "NCLOB", "CLOB")
        self._dmPython_unicode_types = types("UNICODE", "NCLOB")
        self._dmPython_binary_types = types("BFILE", "CLOB", "NCLOB", "BLOB")
        
        self.supports_native_decimal = coerce_to_decimal

        if self.dmPython_ver is None or \
           not self.auto_convert_lobs or \
           not hasattr(self.dbapi, 'CLOB'):
            self.dbapi_type_map = {}
        else:
            self.dbapi_type_map = {
                self.dbapi.CLOB: dm.CLOB(),
                self.dbapi.BLOB: dm.BLOB(),
            }        

    def _parse_dmPython_ver(self, version):
        m = re.match(r'(\d+)\.(\d+)(?:\.(\d+))?', version)
        if m:
            return tuple(
                int(x)
                for x in m.group(1, 2, 3)
                if x is not None)
        else:
            return (0, 0)

    @classmethod
    def import_dbapi(cls):
        import dmPython
        return dmPython

    def connect(self, *cargs, **cparams):
        self.trace_process('DMDialect_dmPython', 'connect', *cargs, **cparams)
        
        try:
            compatible_mode = None
            if 'compatible_mode' in cparams:
                if type(cparams['compatible_mode']) is str and cparams['compatible_mode'].upper() in ['DM', 'MYSQL', 'TSQL', 'ORACLE']:
                    compatible_mode = cparams['compatible_mode'].upper()
                    del cparams['compatible_mode']
                    if compatible_mode == 'MYSQL':
                        self.compatible_module = MySQLCompatible_Mode
                    elif compatible_mode == 'TSQL':
                        self.compatible_module = TSQLCompatible_Mode
                    elif compatible_mode == 'ORACLE':
                        self.compatible_module = OracleCompatible_Mode
                else:
                    raise ValueError("The compatible_mode must be of string type and specified within the scope of DM, Oracle, MYSQL and TSQL")

            if 'parse_type' in cparams:
                parse_type = cparams['parse_type']
                if type(parse_type) is str and parse_type.upper() in ['DM', 'MYSQL', 'TSQL']:
                    if parse_type.upper() == 'MYSQL':
                        if compatible_mode == None:
                            self.compatible_module = MySQLCompatible_Mode
                        self.parse_module = DMMySQLDialect_Adapter
                        self.parse_stmt_func = parse_mysql_stmt
                    elif parse_type.upper() == 'TSQL':
                        if compatible_mode == None:
                            self.compatible_module = TSQLCompatible_Mode
                        self.parse_stmt_func = parse_tsql_stmt
                else:
                    raise ValueError("The parse_type must be of string type and specified within the scope of DM, MYSQL and TSQL")

            if 'cursorclass' in cparams:
                if cparams['cursorclass'] != 0:
                    raise ValueError("In dmSQLAlchemy, the cursorclass option is only allowed to be dmPython.TupleCursor")

            if 'add_quote_all' in cparams:
                quote_type = cparams['add_quote_all']
                if type(quote_type) is bool:
                    if quote_type is True:
                        self.quote_module = Quote_Method
                    del cparams['add_quote_all']
                else:
                    raise ValueError("The add_quote_all must be of bool type")

            conn = self.dbapi.connect(*cargs, **cparams)
            
            self.encoding = self.get_conn_local_code(conn)
            
            self.case_sensitive = conn.str_case_sensitive
            if self.case_sensitive:
                self.requires_name_normalize = True
            else:
                self.requires_name_normalize = False
                        
            cursor = conn.cursor()
            cursor.execute('SELECT MODE$ FROM V$instance;')
            result = cursor.fetchall()
            if result is not None:
                mode_str = result[0][0]
                if (mode_str != 'STANDBY'):
                    cursor.execute('SELECT SET_SESSION_IDENTITY_CHECK(1);')
            else:
                cursor.execute('SELECT SET_SESSION_IDENTITY_CHECK(1);')
            return conn
        except Exception as err:
            if hasattr(err, 'args') and type(err.args[0]) is str:
                raise DBAPIError(err.args[0], 0, None)
            else:
                raise
        
    def get_conn_local_code(self, conn):
        self.trace_process('DMDialect_dmPython', 'get_conn_local_code', conn)
        
        if conn.local_code == 1:
            return 'utf-8'
        elif conn.local_code == 2:
            return 'gbk'
        elif conn.local_code == 3:
            return 'big5'
        elif conn.local_code == 4:
            return 'iso_8859_9'
        elif conn.local_code == 5:
            return 'euc_jp'
        elif conn.local_code == 6:
            return 'euc_kr'
        elif conn.local_code == 8:
            return 'iso_8859_1'
        elif conn.local_code == 9:
            return 'ascii'
        elif conn.local_code == 10:
            return 'gb18030'
        elif conn.local_code == 11:
            return 'iso_8859_11'

    def get_isolation_level(self, dbapi_connection):
        with dbapi_connection.cursor() as cursor:
            cursor.execute(
                "SELECT CASE ISOLATION WHEN 1 THEN 'READ COMMITTED' WHEN 0 THEN 'READ UNCOMMITTED' ELSE 'SERIALIZABLE' END AS isolation_level"
                " FROM V$TRX WHERE ID = dbms_transaction.local_transaction_id( TRUE );",
            )
            row = cursor.fetchone()
            if row is None:
                raise exc.InvalidRequestError(
                    "could not retrieve isolation level"
                )
            result = row[0]

        return result

    def get_isolation_level_values(self, dbapi_connection):
        return super().get_isolation_level_values(dbapi_connection) + [
            "AUTOCOMMIT"
        ]

    def set_isolation_level(self, dbapi_connection, level):
        if level == "AUTOCOMMIT":
            dbapi_connection.autoCommit = True
        else:
            dbapi_connection.autoCommit = False
            dbapi_connection.rollback()
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f"SET SESSION CHARACTERISTICS AS ISOLATION LEVEL {level}")
    
    def initialize(self, connection):
        self.trace_process('DMDialect_dmPython', 'initialize', connection)
        super(DMDialect_dmPython, self).initialize(connection)
        self._detect_decimal_char(connection)

    def _detect_decimal_char(self, connection):
        self.trace_process('DMDialect_dmPython', '_detect_decimal_char', connection)
        return

    def _detect_decimal(self, value):
        self.trace_process('DMDialect_dmPython', '_detect_decimal', value)
        
        if "." in value:
            return decimal.Decimal(value)
        else:
            return int(value)

    _to_decimal = decimal.Decimal

    def on_connect(self):
        self.trace_process('DMDialect_dmPython', 'on_connect')
        return

    def host_str_handler(self, ip_str):
        try:
            ipaddress.IPv6Address(ip_str)
            return '[' + ip_str + ']'
        except ValueError:
            return ip_str
        
    def create_connect_args(self, url):
        self.trace_process('DMDialect_dmPython', 'create_connect_args', url)
        
        opts = url.translate_connect_args(username='user')

        opts['host'] = self.host_str_handler(opts['host'])
        opts.update(url.query)
        
        util.coerce_kw_type(opts, 'access_mode', int) 
        util.coerce_kw_type(opts, 'autoCommit', bool)
        util.coerce_kw_type(opts, 'connection_timeout', int) 
        util.coerce_kw_type(opts, 'login_timeout', int)
        util.coerce_kw_type(opts, 'txn_isolation', int)
        util.coerce_kw_type(opts, 'compress_msg', bool)
        util.coerce_kw_type(opts, 'use_stmt_pool', bool)
        util.coerce_kw_type(opts, 'ssl_path', str)
        util.coerce_kw_type(opts, 'mpp_login', bool)
        util.coerce_kw_type(opts, 'rwseparate', bool)
        util.coerce_kw_type(opts, 'rwseparate_percent', int)
        util.coerce_kw_type(opts, 'lang_id', int)
        util.coerce_kw_type(opts, 'local_code', int)
        
        opts.setdefault('autoCommit', self.autocommit)
        opts.setdefault('connection_timeout', self.connection_timeout)
        opts.setdefault('host', 'localhost')
        opts.setdefault('port', 5236)
        
        dsn = opts['host'] + ':%d' %opts['port']

        if dsn is not None:
            opts['dsn'] = dsn
        
        return ([], opts)

    def _get_server_version_info(self, connection):
        self.trace_process('DMDialect_dmPython', '_get_server_version_info', connection)
        
        dbapi_con = connection.connection
        version = []
        r = re.compile(r'[.\-]')
        for n in r.split(dbapi_con.server_version):
            try:
                version.append(int(n))
            except ValueError:
                version.append(n)
        return tuple(version)

    def is_disconnect(self, e, connection, cursor):
        self.trace_process('DMDialect_dmPython', 'is_disconnect', e, connection, cursor)
        
        error, = e.args
        if isinstance(e, self.dbapi.InterfaceError):
            return "not connected" in str(e)
        elif hasattr(error, 'code'):
            return error.code in (-70025, -70028, -6010, -70019)
        else:
            return False

    def create_xid(self):
        self.trace_process('DMDialect_dmPython', 'create_xid')
        
        """create a two-phase transaction ID.

        this id will be passed to do_begin_twophase(), do_rollback_twophase(),
        do_commit_twophase().  its format is unspecified."""

        id = random.randint(0, 2 ** 128)
        return (0x1234, "%032x" % id, "%032x" % 9)

    def check_position(self, poslist, parameters):
        poslist_len = len(poslist)
        parameters_len = len(parameters)
        if poslist[-1] - poslist[0] == poslist_len - 1:
            for i in poslist:
                for j in range(parameters_len):
                    parameters[j][i] = None
            return poslist, parameters
        else:
            last_pos = poslist[0]
            list_temp = [i for i in range(poslist[0], poslist[-1] + 1)]
            list_diff = list(set(list_temp) - set(poslist))
            for i in list_diff:
                for j in range(parameters_len):
                    parameters[j][last_pos] = parameters[j][i]
                last_pos += 1
            for i in range(poslist_len):
                for j in range(parameters_len):
                    parameters[j][last_pos] = None
                poslist[i] = last_pos
                last_pos += 1
            return poslist, parameters

    def do_executemany(self, cursor, statement, parameters, context=None):
        self.trace_process('DMDialect_dmPython', 'do_executemany', cursor, statement, parameters, context)
        
        if isinstance(parameters, tuple):
            parameters = list(parameters)
        import datetime
        rows = len(parameters)
        columns = len(parameters[0]) if parameters else 0
        for i in range(rows):
            for j in range(columns):
                if type(parameters[i][j]) == datetime.datetime:
                    temp = parameters[i][j]
                    str_temp = temp.strftime("%Y-%m-%d %H:%M:%S.%f %Z")
                    if 'UTC' in str_temp:
                        parameters[i][j] = str_temp.replace('UTC', '')
                    else:
                        parameters[i][j] = str_temp
                if type(parameters[i][j]) == list:
                    list_element = parameters[i][j]
                    if len(list_element) == 0:
                        result_string = ''
                    else:
                        result_string = json.dumps(list_element)
                    list_element = result_string
                    parameters[i][j] = list_element

        self.parse_module.do_executemany_return(self, columns, rows, self, cursor, statement, parameters, context)


    def do_normalize_name(self, name):
        if name is None:
            return None
        if name.upper() == name or name.lower() == name:
            return name
        else:
            return '"' + name + '"'

    def do_rollback_twophase(self, connection, xid, is_prepared=True,
                             recover=False):
        self.trace_process('DMDialect_dmPython', 'do_rollback_twophase', connection, xid, is_prepared, recover)
        
        self.do_rollback(connection.connection)

    def do_commit_twophase(self, connection, xid, is_prepared=True,
                           recover=False):
        self.trace_process('DMDialect_dmPython', 'do_commit_twophase', connection, xid, is_prepared, recover)
        
        self.do_commit(connection.connection)

def parse_mysql_stmt(statement):
    from sqlalchemy.dialects import mysql
    compile_stmt = statement.compile(dialect=mysql.dialect())
    if compile_stmt is None:
        raise NotImplementedError("Unsupported methods by MySQL dialect!")
    raw_sql = str(compile_stmt)
    params = compile_stmt.params
    positiontup = compile_stmt.positiontup
    for position in positiontup:
        raw_sql = raw_sql.replace("%s", ":" + position, 1)
    return raw_sql, params

def parse_tsql_stmt(statement):
    from sqlalchemy.dialects import mssql
    compile_stmt = statement.compile(dialect=mssql.dialect())
    if compile_stmt is None:
        raise NotImplementedError("Unsupported methods by MSSQL dialect!")
    raw_sql = str(compile_stmt)
    params = compile_stmt.params
    return raw_sql, params


dialect = DMDialect_dmPython
