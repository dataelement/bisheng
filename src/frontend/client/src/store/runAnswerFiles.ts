/**
 * F004 (design §7 item 11) — the files of a finished answer.
 *
 * A generated file has two ids. Its `file` events carry the id of the
 * workspace object, which gives the file as the workspace has it now (a later
 * run may overwrite the same path). The answer row stores its own copy under
 * another `file_id` and keeps the event's id in `workspace_file_id`. A
 * finished answer always fetches with the row's `file_id`, so an old answer
 * keeps downloading its own version.
 *
 * The terminal event of a direct run carries the row's file items as
 * `answer_files` (backend `run_events.ANSWER_FILES_FIELD`), the same items the
 * history returns in the row's `files`. When a copy failed on the backend the
 * item has no `workspace_file_id` and its `file_id` is the event's id.
 */

/** One item of an answer row's `files`, as the backend stores it. */
export interface RunAnswerFile {
    /** Id of the answer's own copy (the event's id when the copy failed). */
    file_id: string;
    /** Id the live `file` events used; absent when the copy failed. */
    workspace_file_id?: string;
    file_name?: string;
    path?: string;
    type?: string;
    size?: number | null;
    source?: string;
    object_name?: string;
}

/** Read `answer_files` out of a terminal event's `data`. Never throws; null when absent. */
export function answerFilesOf(source: unknown): RunAnswerFile[] | null {
    const list = (source as { answer_files?: unknown } | null | undefined)?.answer_files;
    if (!Array.isArray(list)) return null;
    const out: RunAnswerFile[] = [];
    for (const item of list) {
        const raw = item as { file_id?: unknown } | null;
        if (!raw || typeof raw !== 'object' || raw.file_id == null || raw.file_id === '') continue;
        out.push({ ...(raw as RunAnswerFile), file_id: String(raw.file_id) });
    }
    return out;
}
