"""MCP tool handlers — one module per category (design D3).

A handler does three things and nothing else: validate its own arguments, build
the execution identity from the credential already installed in the request
ContextVars, and call a domain service. Permission verdicts belong to the
service it calls (or to the retrieval facade), never here — two places deciding
"may this caller see it" is two places to drift.
"""
