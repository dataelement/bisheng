"""F055 hosted-application publish pipeline module.

Layout note (design D16): the publish pipeline is a **separate module** from
F054's ``bisheng/app_runtime/`` — the judgement is file count and owner
boundary, not a machine guard (``scripts/arch-guard.sh`` does not check
cross-module imports below the API layer). ``app_publish`` calls
``app_runtime`` (``AppStateService`` / ``AppMetaService`` /
``orchestrator_client``); the reverse direction is resolved by F054's
``lifecycle_hooks`` callbacks, never by an import.

The one shape this rule forces: ``ResourceTier`` is owned by F055 but **read**
by F054, so its SQLModel definition lives in ``bisheng/database/models/
resource_tier.py`` — putting it here would make ``app_runtime`` import
``app_publish`` and the dependency would become bidirectional with nothing to
stop it. The business logic still lives here, in ``ResourceTierService``.
"""
