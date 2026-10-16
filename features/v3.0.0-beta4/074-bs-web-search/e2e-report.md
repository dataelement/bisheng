# F074 Local Validation and Deployment Acceptance

Date: 2026-10-15. Overall: PARTIAL deployment acceptance; local implementation
and available deterministic checks pass. Nothing has been pushed or deployed.

## Executed Checks

Combined focused suite: 106 passed on Python 3.12, including existing DSH access,
models, credential middleware and ToolExecutor permission regressions. Separate
isolated Python 3.11 core selection: 70 passed. The latter is a minimal dependency
environment, not a full frozen backend installation. No full backend/CI claim.

Local HTTP stories use actual signed DSH JWT verification, ToolPublicationService,
PublishedToolService, ToolExecutor, a socket HTTP upstream, and isolated real Redis.
Identity lookup, Gateway seat introspection, OpenFGA permission decisions and
publication storage are injected adapters in those stories. Administrative HTTP
tests override the browser actor dependency. Portable repository tests separately
exercise the real Config repository on temporary SQLite. SQLite does not implement
the production SELECT FOR UPDATE contract and cannot prove disable/update races.

Ruff format/check (including F821), architecture guard, locale generation/check,
check-i18n and uv lock --check pass. The architecture guard emits one fixture-only
secret warning for the explicit fake query credential in test_published_openapi.py;
there are no production-code warnings or violations. jsonschema 4.25.1 uses the MIT
license and was already locked; the lock diff adds only two direct-dependency lines.
Frontend lint/typecheck and deployed UI acceptance were not run; no TS/UI changed.

## Reproduce

From src/backend, with the project's dependencies installed and redis-server on
PATH, use config=test/e2e/helpers/published-tools.yaml. This test configuration
contains only import-time defaults, never deployment credentials. Unset shell
HTTP/HTTPS/ALL proxy variables for legacy SDK import-time initialization; the
published transport independently disables environment proxies.

```bash
config=test/e2e/helpers/published-tools.yaml python -m pytest --confcutdir=test/dsh \
  test/e2e/test_e2e_published_tools.py \
  test/dsh/test_tool_publication_repository.py \
  test/dsh/test_tool_publication_admin_http.py \
  test/dsh/test_tool_invoke_http.py test/dsh/test_tool_publications.py \
  test/tool/test_published_tools.py test/tool/test_published_schema.py \
  test/tool/test_published_openapi.py test/dsh/test_tool_results.py \
  test/dsh/test_tool_leases.py test/dsh/test_access.py \
  test/dsh/test_models_api.py test/dsh/test_middleware.py \
  test/tool/test_tool_executor_permissions.py -q
```

The confcutdir isolates the existing global test fixture's environment/middleware
requirements. The global fixture could not load the copied docker configuration
without missing BS_MILVUS_CONNECTION_ARGS and other environment values. These are
environment collection failures, not passing middleware tests.

## AC Traceability

Paths in this table are relative to src/backend/test. A local pass does not imply
that the corresponding deployed dependency or database dialect passed.

| AC | Local evidence | Remaining deployment evidence |
| --- | --- | --- |
| AC-01 | dsh/test_tool_publication_admin_http.py; service PUT/GET stories | Real tenant-admin browser identity and current edit grant |
| AC-02 | Admin denial pair; tool/test_published_tools.py | Actual non-admin and OpenFGA decisions |
| AC-03 | dsh/test_tool_publication_repository.py complete replace/revision | MySQL/DM8 persistence |
| AC-04 | SQL tenant-qualified keys, paging and cross-tenant stories | Production dialect/tenant filter |
| AC-05 | Strict schemas, limits, reserved search fields and unsupported kinds | Real saved tool import |
| AC-06 | Disabled invocation rejection; admission/update source review | Concurrent disable under MySQL/DM8 row locks |
| AC-07 | SQL replacement/rollback; unique/savepoint source review | Concurrent insert/update on MySQL/DM8 |
| AC-08 | e2e/test_e2e_published_tools.py signed JWT | Deployed Gateway introspection/header forwarding |
| AC-09 | dsh/test_access.py credential variants; auth before body tests | Actual PAT/SAK/browser rejection through ingress |
| AC-10 | Verified tenant dispatch; inherited admin/bypass restoration | Deployed tenant membership records |
| AC-11 | Root/category tenant fact denials before permission shortcuts | Production tenant filter and saved-tool records |
| AC-12 | Fresh permission denial/outage and disabled state checks | Actual permission/store outages |
| AC-13 | dsh/test_tool_invoke_http.py strict envelope/duplicates/query controls | Gateway request preservation |
| AC-14 | tool/test_published_schema.py enums, exact numeric types and bounds | Real saved schemas |
| AC-15 | Saved snapshot execution; category extra cannot replace validated path | Production server credential configuration |
| AC-16 | Two saved schemas through real ToolExecutor and socket upstream | Two deployed saved tools |
| AC-17 | Top-level tool/result HTTP contract | Work result unwrapping |
| AC-18 | dsh/test_tool_results.py JSON once and stable ordinary text | None beyond deployment smoke |
| AC-19 | Bounded HTTP non-2xx/redirect/encoding failure tests | Actual provider failures |
| AC-20 | Safe status/code envelopes; permission unavailable differs from denial | Ingress status preservation |
| AC-21 | Ambient callbacks/trace collector and httpx query-credential log tests | Deployment log/trace configuration |
| AC-22 | Trimmed query, strict optional maxResults and publication subset | Compatible query-only provider |
| AC-23 | Search rows/URLs and result envelope | Real search response |
| AC-24 | Genuine empty result accepted; errors/text/encrypted output rejected | Real provider zero-results case |
| AC-25 | All rows checked before local truncation | None beyond provider smoke |
| AC-26 | Saved flat body schema and real transport placement | Real upstream compatibility; raw Sub2API is not compatible |
| AC-27 | Preflight/body cap, current input limit, configured deadline, Redis cap | Production shared Redis and database |
| AC-28 | Chunked body stops after limit, closes stream; serialized cap | Actual ingress/provider streaming |
| AC-29 | Service cancellation, ASGI disconnect, deadline and owner cleanup | Kill/failure acceptance in deployed topology |
| AC-30 | Real Redis multi-client atomic cap, cooldown, owner-safe expiry | Failover drain and silent rollback operations |
| AC-31 | Saved aliases/ambiguous destinations and redirects rejected | Operator reverse-proxy rewrites |
| AC-32 | Existing models/access/middleware/executor permission tests pass | Full Agent/workflow and installed Work acceptance |

## Deployment Checklist

1. Run Config create/replace/revision and concurrent update/disable stories on an
   isolated MySQL database and on the central Linux DM8 regression environment.
2. Verify real browser tenant administrators/global scope, ordinary allowed and
   denied tool users, root/category tenant mismatch, and permission outage handling.
3. Create a compatible flat query-only saved search tool, configure its server
   credentials, grant use permission, then publish its ID as bs_web_search. Publish
   a second supported tool with a different schema and verify both via Gateway.
4. Verify DSH signature/session introspection, credential forwarding, license,
   request path, status codes and top-level tool/result through actual ingress.
5. Verify real search/empty/error results and Work's result unwrapping separately.
   Raw Sub2API model/commands requires an external adapter; none was created here.
6. Verify shared Redis admission, cancellation/worker death and the documented
   65-second recovery. A failover that silently rolls back acknowledged writes
   requires an operational admission drain; these tests do not prove otherwise.

No management UI was added; there is no new page interaction to accept. The
Gateway, Work, provider and deployment checklist remains outside this local change.
