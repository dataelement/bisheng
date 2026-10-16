# F074 Discovery - Direct Existing Tool Invocation

Latest user decisions confirmed 2026-10-15:
- Use POST /api/v1/dsh/tools/{toolCode}/invoke with arguments and top-level tool/result.
- OpenAPI/tool services own business contracts. No bs_web_search-specific code.
- Remove independent publication management. All supported existing API tools use
  the same external entry point, subject to their existing tenant/use permissions.
- toolCode resolves the actual existing tool_key. No alias, extra enable flag,
  mapping revision or DSH registration step is required.

Existing source provides tenant-qualified unique tool_key, saved OpenAPI,
destination/credentials, category deletion/tenant facts and resource use permission.
Reuse these through the current ToolExecutor with bounded transport.

The added work is Desktop authentication and generic saved-tool invocation,
common execution bounds, safe errors and regression coverage. No management UI,
Gateway/Work source changes, provider hosting or automatic retries.
Protocol coverage remains the supported OpenAPI subset; MCP/preset are explicit
unsupported results in this implementation. Search is an example use case only.

Implementation uses isolated branch codex/bs-web-search based on beta4
db23811133b397eff1f572c8e5404c262a8f1332. Original checkout WIP is outside scope.
Current contracts and evidence: spec.md, design.md, e2e-report.md.
Local work does not imply push, merge, deployment or live provider acceptance.
