import { isLinsightTaskRunning, type LinsightInfo } from "~/store/linsight";

// The desktop host accepts the identities it opens; draft buckets ("new", "new:…") are skipped.
const CONVERSATION_ID = /^[a-zA-Z0-9_-]{1,128}$/;

/** Conversations with a streaming answer or a task-mode run that still drives the spinner. */
export function runningConversationIds(
  streaming: Readonly<Record<string, boolean>>,
  tasks: ReadonlyMap<string, LinsightInfo>,
): string[] {
  const ids = Object.keys(streaming).filter((id) => streaming[id]);
  for (const info of tasks.values()) {
    if (info.session_id && isLinsightTaskRunning(info)) ids.push(info.session_id);
  }
  return [...new Set(ids.filter((id) => id !== "new" && CONVERSATION_ID.test(id)))].sort();
}
