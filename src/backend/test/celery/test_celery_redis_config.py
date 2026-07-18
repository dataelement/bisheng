from bisheng.core.config.celery_redis import build_celery_redis_config


def test_build_celery_redis_config_keeps_single_node_url() -> None:
    result = build_celery_redis_config('redis://127.0.0.1:6379/2')

    assert result == {'broker_url': 'redis://127.0.0.1:6379/2'}


def test_build_celery_redis_config_supports_single_mode_dict() -> None:
    result = build_celery_redis_config({
        'mode': 'single',
        'url': 'redis://127.0.0.1:6379/3',
    })

    assert result == {'broker_url': 'redis://127.0.0.1:6379/3'}


def test_build_celery_redis_config_supports_sentinel_mode() -> None:
    result = build_celery_redis_config({
        'mode': 'sentinel',
        'sentinel_hosts': [
            {'host': 'redis-sentinel-1', 'port': 26379},
            ('redis-sentinel-2', 26379),
            'redis-sentinel-3:26379',
        ],
        'sentinel_master': 'mymaster',
        'sentinel_password': 'sentinel-secret',
        'username': 'default',
        'password': 'redis-secret',
        'db': 5,
        'visibility_timeout': 7200,
    })

    assert result['broker_url'] == (
        'sentinel://default:redis-secret@redis-sentinel-1:26379/5;'
        'sentinel://default:redis-secret@redis-sentinel-2:26379/5;'
        'sentinel://default:redis-secret@redis-sentinel-3:26379/5'
    )
    assert result['broker_transport_options'] == {
        'master_name': 'mymaster',
        'sentinel_kwargs': {'password': 'sentinel-secret'},
        'visibility_timeout': 7200,
    }
