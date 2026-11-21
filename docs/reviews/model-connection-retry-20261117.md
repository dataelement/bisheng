# Task model connection failure retry — 2026-11-17

## Problem and correction

The reported task failed because the configured model endpoint refused a TCP
connection. Error unwrapping discarded the OpenAI SDK connection exception and
reached a generic lower-level cause. The resulting `unknown` label hid Retry.

Preserve recognised SDK/transport exceptions during unwrapping. Connection
failures now use `service_unavailable`; timeouts keep `network_timeout`.
Authentication, quota and content-filter failures retain their existing rules.

For existing failed versions, recover only unknown model failures (11090) whose
stored detail explicitly identifies a transient transport failure. Apply this
projection before public sanitisation in both history reads and failure replay.
Stored database results remain unchanged, and internal details stay sanitised.

## Validation

- Backend: 82 passed across `test_llm_connection_retry.py`,
  `test_llm_error_classifier.py` and `test_task_failure_payload.py`.
- Existing client Retry/error-card tests: 23 passed in 2 suites, run in band.
  The local optional canvas binding was unavailable, so the test process used a
  temporary loader to exercise jsdom's supported no-canvas path.
- Regression cases cover nested SDK/HTTPX failures, refused connections,
  timeouts, authentication priority, stored-result recovery and preservation of
  terminal/platform errors and original dictionaries.
- Read-only review: PASS after correcting recovery to precede sanitisation.
- Ruff formatting, architecture guard and `git diff --check`: passed.
  Full Ruff check retains exactly four pre-existing diagnostics, reproduced on
  HEAD: RUF002 in the classifier docstring and UP042 on three existing enums.
  No other Ruff diagnostics remain.
- Checks ran serially. No database writes, server deployment or model-service
  restarts were performed.

Backend deployment is needed for live tasks and existing conversation reads to
receive the corrected classification. Endpoint availability remains a separate
operational issue; Retry does not start the model service.
