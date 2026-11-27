# Tasks

- [x] Implement MK client and protocol regression tests.
- [x] Implement deterministic semantic Markdown/source spans.
- [x] Implement tenant-scoped persisted remote checkpoints and artifact reuse.
- [x] Register provider, loader and configuration.
- [x] Integrate parse locking and recoverable ingestion.
- [x] Run targeted tests, lint and repository checks; document middleware limitations.
- [x] Wire platform/client citation preview to DocFlow, retaining one-based PDF pages.
- [x] Fix ElasticsearchStore 1.0 target index access and verify ES retry with the actual locked SDK.
- [x] Correct configuration documentation to database-backed knowledges (plural).
- [ ] Forward DocFlow ingestion and semantic splitting through the OFD wrapper.
- [ ] Persist remote in-flight capacity across polling timeouts, or narrow the advertised concurrency contract.
- [ ] Handle mixed mapped/unmapped citation chunks safely in platform/client UI.
- [ ] Manually verify platform/client preview, paragraph selection and citation positioning against the deployed feature build.
- [ ] Target-environment MySQL/DM8 + Redis/MinIO/Milvus/ES + MK integration acceptance.

Known limits: the three review findings above remain open. Split-task page mapping and rotated PDF highlighting remain explicit fail-closed/text-only boundaries. Table schemas require real response samples; unsupported schemas preserve OCR lines with warnings. No deployment is performed by this change.
