"""BiSheng application capabilities, independent of the backend package.

* auth: the current visitor, supplied by trusted platform ingress.
* retrieve: search through the platform as that visitor.
* storage: application attachments without exposing storage credentials.
* realtime: F113 single-writer record revisions, idempotency and durable events.
* errors: exceptions for the platform request capabilities.

F113 adds an optional transactional collaboration protocol. It is not an ORM
or a platform-database client: application data stays in the application's
persistent SQLite volume. The application still authorizes every business
operation and event. Model clients and general database drivers remain outside
the SDK. The public-surface tests pin this deliberate 0.1.2 extension.
"""

from __future__ import annotations

#: Independent of the platform's version on purpose (design D6 / decision 6):
#: an application's dependency list pins this, and a platform upgrade must not
#: invalidate every deployed application.
__version__ = "0.1.2"

from bisheng_sdk import auth, realtime, retrieve, storage

#: The capability surface. ``errors`` is importable but not a capability, so it
#: is not listed here (design D2).
__all__ = ("auth", "realtime", "retrieve", "storage")
