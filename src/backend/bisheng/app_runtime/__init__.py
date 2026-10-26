"""F054 hosted application runtime module.

Layout note (design D8 "模型落点"): this module holds ``domain/services`` and
``api`` only — the three ORM tables live in ``bisheng/database/models/``
because the build-page UNION has to import them from ``database/models/flow.py``
and arch-guard RULE-2 forbids that file from importing any ``*.domain.*``.
"""
