# DocFlow live acceptance checklist

Status: pending target environment. The local integration tests inject external services and do not replace this checklist. Use a dedicated tenant and resources prefixed `e2e-docflow-`. Delete only those resources; take a baseline of non-test data before testing.

- [ ] API and worker run the feature branch and the standard schema upgrade has created knowledge_docflow_job in the target MySQL/DM8 database.
- [ ] Dedicated DocFlow workspace performs full recognition; splitting/multi-image cutting are disabled. API/worker have the same secret environment variables.
- [ ] Admin uploads a clear image through the existing knowledge UI, previews chunks, confirms ingestion, then reads the file state back as SUCCESS.
- [ ] An ordinary authorized user can retrieve the expected text and open its original citation; an unauthorized user cannot access the file or OCR result.
- [ ] The same-content preview→ingest path creates only one remote OCR task. Inspect checkpoints/vendor logs, not just UI success.
- [ ] A different tenant uploading identical bytes has a distinct checkpoint and cannot read the first tenant's artifact.
- [ ] Multi-page PDF has complete text and correct order. Compare source count with recognized pages.
- [ ] An unrotated PDF citation highlights the correct source region. Rotated-page text remains available without unverified highlights.
- [ ] Real table JSON is added to regression fixtures after removing sensitive data. Compare cells, pipe/HTML escaping, merged cells and repeated values.
- [ ] Stop/restart a worker while querying; retry resumes the remote file ID rather than uploading again.
- [ ] Simulate ES unavailability after Milvus success; retry writes ES without another model embedding call.
- [ ] Simulate an interrupted vector write; retry cleans the document's rows and uses cached vectors when available.
- [ ] Changing workspace/parser_revision invalidates preview/OCR caches. Changing the model configuration invalidates cached embeddings.
- [ ] Concurrent duplicate parse/retry requests do not run destructive cleanup concurrently, regardless of fair_scheduler_enabled.
- [ ] Disable the provider/switch back to the previous provider; existing non-test data remains unchanged.
- [ ] Remove only `e2e-docflow-` knowledge resources and confirm non-test baseline counts are unchanged. Agree remote attachment retention with MK operators.
