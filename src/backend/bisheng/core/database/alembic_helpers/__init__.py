"""Reusable migration helpers extracted from Alembic revisions.

Keeping side-effecting SQL logic here (instead of inline in ``versions/*.py``)
makes it importable from pytest so the business logic can be unit-tested
against a SQLite engine without running the full Alembic pipeline. The
Alembic revision files themselves stay thin orchestrators that call these
helpers plus the DDL ``op.*`` operations.
"""
