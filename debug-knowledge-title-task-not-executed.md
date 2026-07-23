# Debug Session: knowledge-title-task-not-executed

**Status**: `[OPEN]`

**Problem**: 
- User reports that `extract_knowledge_file_title_celery` task registration status is unclear.
- In the testing environment, the title extraction task is not being executed after file upload.

**Expected Behavior**:
- After uploading a file to a knowledge space, `extract_knowledge_file_title_celery` should be enqueued and executed by a Celery worker.
- The worker should extract the title, generate an AI alias, and then trigger `parse_knowledge_file_celery`.

**Actual Behavior**:
- It is unclear whether the task is registered.
- In testing environment, the title extraction task does not appear to run.

**Known Code State**:
- `bisheng/worker/__init__.py` imports `extract_knowledge_file_title_celery` from `bisheng.worker.knowledge.file_title_worker`.
- `bisheng/worker/main.py` uses `include=["bisheng.worker"]` for Celery app creation.
- `knowledge_space_service.py` now imports and calls `extract_knowledge_file_title_celery.delay(...)` from `file_title_worker`.
- `file_title_worker.py` defines the task and calls `parse_knowledge_file_celery.delay(...)` afterwards.

**Reproduction Steps (TBD in testing env)**:
1. Upload a file via `POST /api/v1/knowledge/space/{id}/files`.
2. Check Celery worker logs for `extract_knowledge_file_title_celery start file_id=...`.
3. Check Redis broker for enqueued task messages.
4. Check `KnowledgeFile.alias_name` after parsing completes.

**Hypotheses**:

| ID | Hypothesis | Likelihood | Effort | Expected Signal |
|----|------------|------------|--------|-----------------|
| A | Celery worker was not restarted after code deployment; task not registered in worker memory. | High | Low | `inspect registered` does **not** list `bisheng.worker.knowledge.file_title_worker.extract_knowledge_file_title_celery`. |
| B | Task is registered but routed to a queue not consumed by any worker. | Medium | Low | `inspect registered` lists the task, but `inspect active/scheduled` never shows it; Redis queue length grows for a queue the worker is **not** listening to. |
| C | Task was enqueued by API but failed during execution (exception swallowed in best-effort code). | Medium | Low | Worker log shows `extract_knowledge_file_title_celery start ...` followed by a warning/exception; `parse_knowledge_file_celery` is still enqueued. |
| D | Task executed but skipped because preconditions not met. | Medium | Low | Worker log shows `title extraction skipped, ...` with reason (status, missing object_name, no title extracted). |
| E | Redis broker contains stale messages or API/worker code versions are inconsistent. | Low | Medium | Old error `module 'bisheng.worker.knowledge.file_worker' has no attribute 'extract_knowledge_file_title_celery'` still appears in worker logs after API restart. |

**Code Changes Made (Instrumentation / Logging)**:

To make root-cause identification easier in the testing environment, the following logging-only changes were applied (no business logic changed):

1. [src/backend/bisheng/worker/knowledge/file_title_worker.py](file:///Users/xuhualiang/ai_coding/shougang/online/bisheng/src/backend/bisheng/worker/knowledge/file_title_worker.py)
   - Added `title extraction preparing ...` log showing `status`, `object_name`, `tenant_id`.
   - Added `title extraction skipped, file status=... is not WAITING` guard (precondition check).
   - Added `title extraction downloaded ... local_path=... exists=...` log.
   - Added `title extraction result ... raw_title=...` log.
   - Added `alias generation result ... alias_name=...` log.

2. [src/backend/bisheng/knowledge/domain/services/file_alias_name_generator.py](file:///Users/xuhualiang/ai_coding/shougang/online/bisheng/src/backend/bisheng/knowledge/domain/services/file_alias_name_generator.py)
   - Added `alias generation config ... file_alias_model_id=...` log.
   - Upgraded `file_alias_model_id not configured` from `debug` to `warning`.
   - Added `alias generation llm response ... content=...` log.
   - Added `alias generation parsed raw_alias=...` log.

3. [src/backend/bisheng/knowledge/domain/services/file_title_extractor.py](file:///Users/xuhualiang/ai_coding/shougang/online/bisheng/src/backend/bisheng/knowledge/domain/services/file_title_extractor.py)
   - Added `title extraction dispatch ... extension=... extractor=...` log.
   - Added `title extraction done ... title=...` log.

4. [src/backend/bisheng/knowledge/domain/services/file_alias_name_generator.py](file:///Users/xuhualiang/ai_coding/shougang/online/bisheng/src/backend/bisheng/knowledge/domain/services/file_alias_name_generator.py) — robustness & fallback improvements
   - Changed `_JSON_BLOCK_RE` from greedy `{.*}` to non-greedy `{.*?}` so it does not swallow trailing explanation text.
   - Added `_CODE_BLOCK_RE` to support JSON wrapped in markdown code blocks (e.g. ```json {...} ```).
   - Refactored `_parse_llm_json` to try: code block -> direct JSON -> first JSON object.
   - Added detailed logs in `_extract_alias_from_dict` and `_normalize_alias_name`.
   - **Added fallback logic**: when `file_alias_model_id` is empty, use `extract_title_model_id` instead. Only return `None` when both are missing.

**Verification Commands (run in testing env)**:

1. Check task registration:
   ```bash
   cd src/backend
   celery -A bisheng.run_celery inspect registered
   ```

2. Check active/scheduled tasks:
   ```bash
   celery -A bisheng.run_celery inspect active
   celery -A bisheng.run_celery inspect scheduled
   ```

3. Check Redis queue lengths (adjust db index if needed):
   ```bash
   redis-cli -n 0 LLEN celery
   redis-cli -n 0 LLEN knowledge_celery
   ```

4. Check worker logs for title extraction logs after uploading a file:
   - Look for `extract_knowledge_file_title_celery start file_id=...`
   - Look for `title extraction preparing ...`
   - Look for `title extraction dispatch ... extension=... extractor=...`
   - Look for `title extraction result ... raw_title=...`
   - Look for `alias generation config ... file_alias_model_id=...`
   - Look for `alias generation llm response ...`
   - Look for `file alias generated file_id=... alias_name=...`
   - Look for any traceback after the start line.

5. Verify database state for a recently uploaded file:
   ```sql
   SELECT id, file_name, alias_name, status, object_name, parse_type
   FROM knowledge_file
   WHERE id = <file_id>;
   ```

**Mandatory Deployment Note**: Because new files (`file_title_worker.py`, `file_title_extractor.py`, `file_alias_name_generator.py`, `gen_title.yaml`) were added, the Docker image **must be rebuilt** and the API + Celery Worker containers **must be restarted** for any of these changes to take effect in the testing environment.
