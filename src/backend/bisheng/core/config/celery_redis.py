import ast
from typing import Any, Mapping
from urllib.parse import quote


def build_celery_redis_config(redis_config: str | Mapping[str, Any] | None) -> dict[str, Any]:
    """Build Celery broker settings from single-node or sentinel Redis config."""
    if redis_config is None or isinstance(redis_config, str):
        return {'broker_url': redis_config}

    redis_conf = dict(redis_config)
    mode = str(redis_conf.pop('mode', 'single')).lower()

    if mode == 'single':
        broker_url = redis_conf.pop('url', None)
        if not broker_url:
            raise ValueError('Single Redis mode requires `url` in `celery_redis_url`.')
        return {'broker_url': broker_url}

    if mode != 'sentinel':
        raise ValueError(f'Unsupported celery redis mode: {mode}')

    return _build_sentinel_config(redis_conf)


def _build_sentinel_config(redis_conf: dict[str, Any]) -> dict[str, Any]:
    sentinel_hosts = redis_conf.pop('sentinel_hosts', None)
    sentinel_master = redis_conf.pop('sentinel_master', None)
    if not sentinel_hosts:
        raise ValueError('Sentinel Redis mode requires `sentinel_hosts` in `celery_redis_url`.')
    if not sentinel_master:
        raise ValueError('Sentinel Redis mode requires `sentinel_master` in `celery_redis_url`.')

    db = int(redis_conf.pop('db', 0))
    username = redis_conf.pop('username', None)
    password = redis_conf.pop('password', None)
    sentinel_username = redis_conf.pop('sentinel_username', None)
    sentinel_password = redis_conf.pop('sentinel_password', None)

    broker_url = ';'.join(
        _build_sentinel_endpoint(host_item, db=db, username=username, password=password)
        for host_item in sentinel_hosts
    )

    broker_transport_options: dict[str, Any] = {'master_name': sentinel_master}
    sentinel_kwargs = {}
    if sentinel_username:
        sentinel_kwargs['username'] = sentinel_username
    if sentinel_password:
        sentinel_kwargs['password'] = sentinel_password
    if sentinel_kwargs:
        broker_transport_options['sentinel_kwargs'] = sentinel_kwargs

    for option_name in (
            'visibility_timeout',
            'socket_timeout',
            'socket_connect_timeout',
            'socket_keepalive',
            'socket_keepalive_options',
            'health_check_interval',
            'retry_on_timeout',
            'global_keyprefix',
            'max_connections',
            'min_other_sentinels',
    ):
        if option_name in redis_conf:
            broker_transport_options[option_name] = redis_conf.pop(option_name)

    return {
        'broker_url': broker_url,
        'broker_transport_options': broker_transport_options,
    }


def _build_sentinel_endpoint(
    host_item: Any,
    *,
    db: int,
    username: str | None,
    password: str | None,
) -> str:
    host, port = _parse_sentinel_host(host_item)
    auth = _build_auth_segment(username=username, password=password)
    return f'sentinel://{auth}{host}:{port}/{db}'


def _build_auth_segment(*, username: str | None, password: str | None) -> str:
    if username is None and password is None:
        return ''

    encoded_username = quote(username or '', safe='')
    encoded_password = quote(password or '', safe='')
    return f'{encoded_username}:{encoded_password}@'


def _parse_sentinel_host(host_item: Any) -> tuple[str, int]:
    if isinstance(host_item, dict):
        host = host_item.get('host')
        port = host_item.get('port')
    elif isinstance(host_item, (list, tuple)) and len(host_item) == 2:
        host, port = host_item
    elif isinstance(host_item, str):
        host, port = _parse_sentinel_host_string(host_item)
    else:
        raise ValueError(f'Invalid sentinel host entry: {host_item!r}')

    if host is None or port is None:
        raise ValueError(f'Invalid sentinel host entry: {host_item!r}')

    return str(host), int(port)


def _parse_sentinel_host_string(host_item: str) -> tuple[str, int]:
    stripped = host_item.strip()
    if stripped.startswith(('(', '[')):
        parsed = ast.literal_eval(stripped)
        if not isinstance(parsed, (list, tuple)) or len(parsed) != 2:
            raise ValueError(f'Invalid sentinel host entry: {host_item!r}')
        host, port = parsed
        return str(host), int(port)

    if ':' not in stripped:
        raise ValueError(f'Invalid sentinel host entry: {host_item!r}')

    host, port = stripped.rsplit(':', 1)
    return host, int(port)
