"""MCP server face (F052) — an entrance layer, sibling to ``open_api/api/``.

Everything here is a thin, authenticated wrapper over domain services. It calls
``domain/services`` and ``permission.application`` only: no ORM, no other
module's ``api/``, no direct orchestrator RPC (C1 / RULE-5).

The package is imported unconditionally — registering the route is what
``settings.open_platform.enabled`` gates (``main.py``), so an environment
without the open-capability layer answers 404 and carries no standing cost.
"""
