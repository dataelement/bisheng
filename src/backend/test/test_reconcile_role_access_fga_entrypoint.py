import types

import pytest

from bisheng.permission.migration import reconcile_role_access_fga


@pytest.mark.asyncio
async def test_main_initializes_application_context(monkeypatch):
    fake_settings = object()
    calls = []

    fake_config_service = types.ModuleType('bisheng.common.services.config_service')
    fake_config_service.settings = fake_settings

    fake_context = types.ModuleType('bisheng.core.context')

    async def fake_initialize_app_context(config):
        calls.append(('initialize', config))

    async def fake_close_app_context():
        calls.append(('close', None))

    async def fake_reconcile(dry_run):
        calls.append(('reconcile', dry_run))
        return reconcile_role_access_fga.Stats(
            desired=1,
            actual=1,
            to_write=0,
            to_delete=0,
            protected=0,
        )

    fake_context.initialize_app_context = fake_initialize_app_context
    fake_context.close_app_context = fake_close_app_context

    monkeypatch.setitem(
        __import__('sys').modules,
        'bisheng.common.services.config_service',
        fake_config_service,
    )
    monkeypatch.setitem(__import__('sys').modules, 'bisheng.core.context', fake_context)
    monkeypatch.setattr(reconcile_role_access_fga, 'reconcile', fake_reconcile)

    await reconcile_role_access_fga._main(dry_run=True)

    assert calls == [
        ('initialize', fake_settings),
        ('reconcile', True),
        ('close', None),
    ]
