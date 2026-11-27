# DocFlow OCR

Scope and design were approved in the chat before implementation began.

- AC-01: PDF and image parsing can select DocFlow through the existing provider setting.
- AC-02: A loader returns only standard Documents and TextBbox artifacts; it never embeds or writes search indexes.
- AC-03: The MK Host/header/UTF-8 JSON protocol and fileStream upload path match the successful integration prototype.
- AC-04: Preview and ingestion reuse tenant-isolated persisted remote task IDs and raw results for identical file/configuration inputs.
- AC-05: Submission with an unknown outcome is never blindly retried. Polling can resume after timeout/restart.
- AC-06: Semantic Markdown preserves all recognized content, builds source offsets against the final text, and does not fabricate table cells or PDF coordinates.
- AC-07: Partial index failure can be resumed without repeating OCR or a confirmed successful vector write; concurrent processing is serialized independently of fair scheduling.
- AC-08: Failures retain the actual provider and actionable redacted stage/error information. Existing providers remain compatible.
