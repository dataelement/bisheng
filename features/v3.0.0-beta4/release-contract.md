# Release Contract - v3.0.0-beta4

Status: user confirmed F074 discovery/spec/design and subsequent corrections on
2026-10-15. Local branch codex/bs-web-search; deployment acceptance pending.
Baseline beta4: db23811133b397eff1f572c8e5404c262a8f1332.
Existing release contracts and docs/constitution.md remain authoritative.

## Ownership

- Existing tool module owns tool_key, saved OpenAPI, destination, credentials and
  lifecycle. No new publication object, mapping, enable state or revision exists.
- F074 owns the DSH-authenticated invocation entry and common execution limits.
- Existing permission facade owns current category use authorization.
- Existing F062 owns Desktop identity/access/session. No new token issuance.
- Gateway and Work repositories remain outside this branch's write scope.

## Invariants

| ID | Invariant |
| --- | --- |
| INV-SEARCH-1 | Arguments only; actual saved tool_key selects saved schema/destination/credentials without extra registration. |
| INV-SEARCH-2 | Verified Desktop identity, strict tenant facts and current saved-tool use permission precede execution. |
| INV-SEARCH-3 | All keys use the same OpenAPI validation and bounded generic tool/result normalization; tools own business semantics. |
| INV-SEARCH-4 | No Gateway/Work edits or production provider claims in this change. |

No new database table, mapping/config persistence or management API.
Supported protocols remain the first implementation's OpenAPI subset. No extra
publication prerequisite applies to supported existing tools.

## Confirmed Corrections

2026-10-15: Replace fixed search endpoint with generic tool invocation.
2026-10-15: Remove bs_web_search-specific argument/schema/result constraints.
2026-10-15: Remove independent publication management; invoke all supported
existing API tools through their existing keys and authorization.
