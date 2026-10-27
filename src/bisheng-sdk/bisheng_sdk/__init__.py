"""BiSheng application SDK — three things an application must not get wrong.

The public surface is **exactly** three capability modules plus the exception
module they all raise from:

* :mod:`bisheng_sdk.auth` — who is visiting *right now*. Read from the headers
  the platform injects; never invented, never defaulted, never ``None``.
* :mod:`bisheng_sdk.retrieve` — search knowledge as **that visitor**, through
  the platform's one retrieval face.
* :mod:`bisheng_sdk.storage` — the application's own attachment space, with no
  bucket, key prefix, endpoint or credential ever reaching the application.
* :mod:`bisheng_sdk.errors` — one exception per next action the caller can take.

Model calls and the application database are **deliberately not here** (PRD-1
DEV-07): they are the official OpenAI-compatible client and a standard database
driver, wired through environment variables the platform injects. The admission
bar for a fourth module is "platform specific ∧ getting it wrong is a security
incident", and ``tests/test_public_surface.py`` is where that bar is enforced —
change the set there first, or the new module does not ship.
"""

from __future__ import annotations

#: Independent of the platform's version on purpose (design D6 / decision 6):
#: an application's dependency list pins this, and a platform upgrade must not
#: invalidate every deployed application.
__version__ = "0.1.1"

from bisheng_sdk import auth, retrieve, storage

#: The capability surface. ``errors`` is importable but not a capability, so it
#: is not listed here (design D2).
__all__ = ("auth", "retrieve", "storage")
