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
   - Look for `title extraction skipped, ...`
   - Look for `file alias generated file_id=... alias_name=...`
   - Look for any traceback after the start line.

5. Verify database state for a recently uploaded file:
   ```sql
   SELECT id, file_name, alias_name, status, object_name, parse_type
   FROM knowledge_file
   WHERE id = <file_id>;
   ```
