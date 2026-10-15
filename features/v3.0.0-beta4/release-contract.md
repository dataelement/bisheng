# Release Contract - v3.0.0-beta4

Status: draft, pending F074 discovery confirmation. Scope: additions on the
`codex/bs-web-search` branch; this does not redefine previously shipped features.

## Baseline

- `origin/feat/3.0.0-beta4` and `v3.0.0-beta4` resolve to
  `db23811133b397eff1f572c8e5404c262a8f1332` (verified 2026-10-15).
- Existing feature contracts remain authoritative, including F062 in
  `features/v3.0.0-beta2/062-dsh-desktop-model-access/`.
- Architecture laws: `docs/constitution.md`.

## Domain Ownership

| Object | Owner | Boundary |
| --- | --- | --- |
| Tenant tool publication mapping | F074 bs-web-search | Manage stable tool codes, saved-tool bindings, publication state and limits |
| Desktop identity, access token, session | Existing F062 | F074 consumes authenticated identity; no token issuance changes |
| Saved OpenAPI tool and credentials | Existing tool module | F074 references saved records and invokes the existing executor |
| Tool authorization | Existing permission module | F074 requires the current tool `use` decision |

## Invariants

| ID | Invariant |
| --- | --- |
| INV-SEARCH-1 | Invocation accepts arguments only; publication selects the saved tool, credentials and argument schema. |
| INV-SEARCH-2 | Every execution uses a verified DSH identity, its tenant publication and current saved-tool permission. |
| INV-SEARCH-3 | Success is top-level tool/result; bs_web_search validates its result contract and never disguises failure as empty results. |
| INV-SEARCH-4 | Gateway and Work repositories are outside this branch's write scope. |

## Dependencies

F074 depends on the existing F062 credential/runtime and saved OpenAPI tool
execution. No new database table is proposed. Error codes will extend the
existing DSH module (261), with unused codes verified before allocation; this
draft allocates no new numeric codes.

## History

2026-10-15: Initial draft for F074 discovery.
