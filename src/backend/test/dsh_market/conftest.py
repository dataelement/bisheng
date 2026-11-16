import pytest


@pytest.fixture(autouse=True)
def market_items_visible(request, monkeypatch):
    """F022: market business tests run without F048, so every item is visible.

    Registration after an import is a no-op here. Authorization tests set
    ``REAL_MARKET_PERMISSION = True`` in their module and install their own
    fakes below the decision functions instead.
    """
    if getattr(request.module, "REAL_MARKET_PERMISSION", False):
        return
    from bisheng.dsh_market.domain import permission

    async def visible_ids(actor, resource_type, records):
        return {record.id for record in records if record.tenant_id == int(actor.tenant_id)}

    async def ensure_registered(resource_type, *, tenant_id, resource_id, operator_id):
        return None

    monkeypatch.setattr(permission, "_visible_ids", visible_ids)
    monkeypatch.setattr(permission, "ensure_registered", ensure_registered)
