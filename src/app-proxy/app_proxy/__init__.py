"""BiSheng app-proxy — the single entry point in front of every hosted app.

Standalone package on purpose (design D5-C / D6): it **never imports the
``bisheng`` package**. Everything it needs arrives over two HMAC-signed RPCs —
"who is this and may they enter" from the backend, "where does this app live"
from runtime-manager — so the security logic has exactly one implementation
(the backend's F048 chain) and this process stays a proxy, not a second copy of
the platform.

Why self-written rather than oauth2-proxy: CVE-2025-64484 (CVSS 8.5) is exactly
an incomplete header strip, and what we host are uncontrolled Python
application frameworks that trust ``X-BiSheng-*`` unconditionally. See
:mod:`app_proxy.headers` for the normalised-equivalence-class strip that answers
it.
"""

__version__ = "3.0.0"
