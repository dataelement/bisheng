# F074 Task Review

Date: 2026-10-15. Local self-review using task-review/references/task-checklist.md.
Current constitution C1-C8 overrides historical DAO/permission examples in that
checklist. No independent reviewer or CI result is claimed.

| Task | Applicable checks / evidence | Result |
| --- | --- | --- |
| T001 | Safe 26131-26141 registry and strict immutable limits; no ORM change | PASS |
| T002 | Named strict schema/result tests and explicit AC IDs | PASS |
| T003 | Full saved schema, bounded JSON and search results; test pair passes | PASS |
| T004 | Real isolated Redis and bounded HTTP tests | PASS |
| T005 | Opt-in executor factory, verified snapshot, task-local HTTP log filter; legacy default preserved | PASS |
| T006 | Lua atomic owner leases, persistent marker/cooldown and owner-only release | PASS |
| T007 | Services, admin/invoke HTTP and portable repository test pairs | PASS |
| T008 | Config key locking/savepoint, escaped prefix, tool/category join in repository; dual-dialect runtime pending | PASS_WITH_NOTES |
| T009 | Tenant/type/deletion facts before current edit/use checks; no permission infrastructure import | PASS |
| T010 | Service orchestration and lazy dsh/tool_runtime.py composition; no SQL/FastAPI in service | PASS |
| T011 | Body/auth/error/status/ASGI disconnect tests and AC IDs | PASS |
| T012 | Bounded shared tool_bodies.py parsing; PublishedToolRoute safe errors; separate OpenAPI request schemas | PASS |
| T013 | Shared desktop_principal; models import alias retains dependency identity | PASS |
| T014 | Exact POST credential pattern; neighboring routes retain browser policy | PASS |
| T015 | Only publication-management prefix added to admin scope | PASS |
| T016 | jsonschema MIT, explicit existing pinned version; two-line lock change only | PASS |
| T017 | en/zh-Hans source-only error additions | PASS |
| T018 | Matching ja source; six artifacts regenerated; locale/i18n checks pass | PASS |
| T019 | Local HTTP/socket/Redis stories and 32-AC coverage table; real deployment checklist documented | PASS_WITH_NOTES |
| T020 | Seven-dimension local review, scoped checks and commit preparation | PASS_WITH_NOTES |

File scope includes the implementation helpers listed above and the test helpers
under test/e2e/helpers, declared with the relevant task rather than a new feature.
No schema/table/migration, Worker, component, styling, Gateway or Work edits.

Serialization: admin success retains resp_200 and data/total paging; invoke follows
the confirmed top-level tool/result exception. Errors use real HTTP statuses and
the DSH error envelope. No business ORM/config/credential dump is serialized.

Information disclosure checks cover ambient callbacks, trace collectors and HTTP
library logging, not only explicit logger calls. One architecture-guard warning
identifies an intentionally fake query credential in a test fixture; it is not a
production secret. Python comments are English. No frozen lint/type baseline changed.

Required external evidence remains in e2e-report.md. SQLite is not evidence for
production locking, and injected permission/identity adapters are not real account
or Gateway acceptance. Local commit does not authorize push/merge/deployment.
