"""Opt-in real ORM tenant filtering without changing later tests' listeners."""

import pytest
from sqlalchemy import event
from sqlmodel import Session

from bisheng.core.database import tenant_filter


@pytest.fixture
def isolated_tenant_filter(monkeypatch):
    initialized = tenant_filter._initialized
    tables = tenant_filter._tenant_aware_tables
    installed = []
    listens_for = event.listens_for

    def record(target, identifier, *args, **kwargs):
        decorate = listens_for(target, identifier, *args, **kwargs)

        def register(function):
            result = decorate(function)
            if target is Session and function.__module__ == tenant_filter.__name__:
                installed.append((target, identifier, function))
            return result

        return register

    with monkeypatch.context() as patch:
        patch.setattr(event, "listens_for", record)
        tenant_filter.register_tenant_filter_events()
    try:
        yield
    finally:
        for target, identifier, function in reversed(installed):
            event.remove(target, identifier, function)
        tenant_filter._initialized = initialized
        tenant_filter._tenant_aware_tables = tables
