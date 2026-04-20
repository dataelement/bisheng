"""F019-admin-tenant-scope (v2.5.1) — admin management-view switch.

This module hosts the global super admin's "management-view scope" facility:
a Redis-backed, 4h-sliding, JWT-independent mechanism that lets a super admin
temporarily narrow the set of tenants visible to *management* APIs without
changing their user/tenant membership.

See ``features/v2.5.1/019-admin-tenant-scope/spec.md`` and PRD §5.1.5.
"""
