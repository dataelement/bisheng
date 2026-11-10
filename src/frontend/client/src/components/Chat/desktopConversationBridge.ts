import { useEffect, useRef } from "react";
import { getClientEnvironment, readDesktopPresentation } from "~/utils/clientEnvironment";

/*
 * Conversation sync with the BISHENG desktop host. The host draws its own
 * conversation list beside this document, so it cannot see which turns are
 * still generating here, and this document cannot see a rename made there.
 * Kept free of chat and Recoil state so the shell bridge can import it.
 */

const MAX_REPORTED = 100;

// One entry per chat hook instance: a KeepAlive view and an app chat can stream at once.
const activityByOwner = new Map<string, readonly string[]>();
let lastReport: string | undefined;

const onDesktop = () => getClientEnvironment().channel === "desktop";

function flush(force = false): void {
  if (!onDesktop()) return;
  const ids = [...new Set([...activityByOwner.values()].flat())].sort().slice(0, MAX_REPORTED);
  const key = ids.join(",");
  if (!force && key === (lastReport ?? "")) return;
  lastReport = key;
  readDesktopPresentation().reportRunning?.(ids);
}

/** Re-send after navigation: the host matches each report against the document's current path. */
export function resendConversationActivity(): void {
  if (lastReport !== undefined) flush(true);
}

/** Publish one chat instance's running conversations to the desktop host. */
export function useDesktopConversationActivity(owner: string, conversationIds: readonly string[]): void {
  const key = [...new Set(conversationIds)].sort().join(",");
  useEffect(() => {
    activityByOwner.set(owner, key ? key.split(",") : []);
    flush();
  }, [owner, key]);
  useEffect(() => () => {
    activityByOwner.delete(owner);
    flush();
  }, [owner]);
}

/** Run `onRenamed` when the desktop host renames a conversation from its own list. */
export function useDesktopConversationRenamed(onRenamed: (conversationId: string) => void): void {
  const latest = useRef(onRenamed);
  useEffect(() => {
    latest.current = onRenamed;
  });
  useEffect(() => {
    const subscribe = readDesktopPresentation().onConversationRenamed;
    if (!onDesktop() || !subscribe) return;
    return subscribe((conversationId) => latest.current(conversationId));
  }, []);
}

/** Test seam: module state outlives a single render tree. */
export function resetDesktopConversationBridge(): void {
  activityByOwner.clear();
  lastReport = undefined;
}
