# BiSheng API-key API

All HTTP and WebSocket calls in this contract require an API key in the standard header:

```http
Authorization: Bearer bs-sak-REPLACE_WITH_YOUR_KEY
```

Personal tokens use the same header and a `bs-pat-` prefix. A personal token is limited to `knowledge:read`; service-account key permissions are selected when the key is issued. Keys are shown once and must be stored securely.

## Identity headers

- `X-End-User`: Optional external end-user identifier used to isolate mode-S sessions. It does not change authorization.
- `X-On-Behalf-Of`: Natural-person user ID for mode D. The key needs `delegate`, the target must be active and non-privileged, the target must fall within the configured user or department range, and the endpoint must support mode D.

Do not send raw `user_id` request fields. Identity is expressed only by these headers.

## Daily chat

The five daily-chat endpoints require `chat:invoke`:

- `GET /api/v2/workstation/config`
- `POST /api/v2/workstation/chat/completions`
- `GET /api/v2/chat/list`
- `GET /api/v2/chat/info?chat_id=...`
- `POST /api/v2/knowledge/upload`

`workstation/chat/completions` is synchronous SSE. Its request supports `files` and requires `clientTimestamp`; task mode, personal knowledge-base selection, and asynchronous execution are rejected.

```bash
curl -N "https://example.invalid/api/v2/workstation/chat/completions" \
  -H "Authorization: Bearer bs-sak-REPLACE_WITH_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"MODEL_ID","messages":[{"role":"user","content":"Hello"}],"clientTimestamp":0,"files":[]}'
```

## Workflow input

When a workflow waits for user input, send it in the `input` field together with the returned `session_id`, `message_id`, and node key.

## WebSocket endpoints

- `/api/v2/workflow/chat/{workflow_id}?chat_id=...`
- `/api/v2/assistant/chat/{assistant_id}?chat_id=...`

WebSocket authentication uses the `Authorization` header during the handshake; API keys in query parameters are rejected. `X-End-User` and `X-On-Behalf-Of` have the same semantics as HTTP. A revoked, expired, or disabled credential closes an established connection within the configured recheck interval.

The machine-readable [OpenAPI contract](openapi-v2-key-auth-api.json) contains every registered HTTP operation plus an `x-websocket-endpoints` extension for these two upgrade routes.
