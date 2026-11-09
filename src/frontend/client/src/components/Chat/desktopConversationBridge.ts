import { useEffect, useRef } from 'react';
import { isLinsightTaskRunning, type LinsightInfo } from '~/store/linsight';
import { isDesktopEmbedded } from './desktopEmbedding';

/*
 * Conversation sync with the BISHENG desktop host. The host draws its own
 * conversation list beside this document, so it cannot see which turns are
 * still generating here, and this document cannot see a rename made there.
 */

// The host accepts the same identities it opens; drafts without an id are skipped.
const CONVERSATION_ID = /^[a-zA-Z0-9_-]{1,128}$/;
const MAX_REPORTED = 100;

// One entry per chat hook instance: a KeepAlive view and an app chat can stream at once.
const activityByOwner = new Map<string, readonly string[]>();
let lastReport: string | undefined;

function flush(force = false): void {
  if (!isDesktopEmbedded()) return;
  const ids = [...new Set([...activityByOwner.values()].flat())].sort().slice(0, MAX_REPORTED);
  const key = ids.join(',');
  if (!force && key === (lastReport ?? '')) return;
  lastReport = key;
  window.dshChatPresentation?.reportRunning?.(ids);
}

/** Re-send after navigation: the host matches each report against the document's current path. */
export function resendConversationActivity(): void {
  if (lastReport !== undefined) flush(true);
}

/** Conversations with a streaming answer or a task-mode run that still drives the spinner. */
export function runningConversationIds(
  streaming: Readonly<Record<string, boolean>>,
  tasks: ReadonlyMap<string, LinsightInfo>,
): string[] {
  const ids = Object.keys(streaming).filter((id) => streaming[id]);
  for (const info of tasks.values()) {
    if (info.session_id && isLinsightTaskRunning(info)) ids.push(info.session_id);
  }
  return [...new Set(ids.filter((id) => id !== 'new' && CONVERSATION_ID.test(id)))].sort();
}

/** Publish one chat instance's running conversations to the desktop host. */
export function useDesktopConversationActivity(
  owner: string,
  streaming: Readonly<Record<string, boolean>>,
  tasks: ReadonlyMap<string, LinsightInfo>,
): void {
  const key = runningConversationIds(streaming, tasks).join(',');
  useEffect(() => {
    activityByOwner.set(owner, key ? key.split(',') : []);
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
    const subscribe = window.dshChatPresentation?.onConversationRenamed;
    if (!isDesktopEmbedded() || typeof subscribe !== 'function') return;
    return subscribe((conversationId) => latest.current(conversationId));
  }, []);
}

/** Test seam: module state outlives a single render tree. */
export function resetDesktopConversationBridge(): void {
  activityByOwner.clear();
  lastReport = undefined;
}
