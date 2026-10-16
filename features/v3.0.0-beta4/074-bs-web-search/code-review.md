# F074 Code Review

Updated 2026-10-15. Local self-review; no independent/CI result.

Production behavior: existing tool_key, current tenant/state/use permission,
generic OpenAPI arguments and bounded execution. No extra publication API/store
or search-specific branches. Existing ToolExecutor default behavior is preserved.

Tests now focus on the external invocation API. Five files cover HTTP admission,
actual service/executor dispatch, schema/destination boundaries, bounded transport
and Redis concurrency. There are no tool save/publication suites or separate
integration-harness file. Existing tool CRUD tests are unchanged.

HTTP integration uses injected tool lookup/identity/FGA and MockTransport upstream;
real Redis runs separately. Removed SQL and standalone service/result tests are
no longer acceptance evidence. Current commands/results are in e2e-report.md.

Live database isolation/async drivers/MySQL/DM8, accounts/FGA, Gateway, provider and
installed Work still need integration acceptance. Supported OpenAPI forms remain
limited; MCP/preset are explicit unsupported results. No push or deployment.
