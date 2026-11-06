# F086 independent design review

Initial conclusion: NEEDS_FIX — two medium issues, no architectural blocker.
Reviewer: independent agent `review_shared_app_chat_design`, 2026-10-21.
Scope: documents and source inspection; no tests/builds or file modifications
performed by the reviewer.

1. Original design §4.2 did not establish the raw history boundary. Client
   `api/apps.ts:getChatHistoryApi` already filters/parses/reclassifies records,
   making a second normalizer incomplete and duplicated.
2. Original design §6.1 omitted a session-bound QA operation/completion context.
   QA dialogs invoke an argument-free completion callback, so an old request
   may update status in the newly active conversation.

Both findings were verified against source and addressed in the design:
- §4.2 specifies raw rows, request-only envelope unwrapping, migration of
  transformations into core, pagination and explicit legacy-caller inventory.
- §5/§6.1 specify immutable QA origin IDs, action/session generation, origin-only
  status writes and guarded modal/local-state completion.
- §7 adds targeted raw-history and deferred QA race tests.

Resolution: design revised; production implementation still pending design
confirmation. The amended design has not received a second independent review.
Remaining original findings: none unaddressed in the written design. Runtime
correctness must be demonstrated during implementation and integration tests.
