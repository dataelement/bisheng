import { useCallback, useMemo, useRef, useState } from 'react';
import type { SetStateAction } from 'react';
import type { SelectedOrgKb } from '~/store/modeltype';

const EMPTY: SelectedOrgKb[] = [];
const selectionKey = (userId: string, conversationId: string) =>
  `bs-conversation:${userId}:knowledge:${conversationId}`;

function readSelection(key: string): SelectedOrgKb[] | undefined {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? 'null');
    if (Array.isArray(raw) && raw.every((item) => item && typeof item.id === 'string'
      && typeof item.name === 'string' && ['org', 'space'].includes(item.type))) return raw;
  } catch { /* An unavailable record resolves to the conversation's initial scope. */ }
}

function writeSelection(key: string, value: SelectedOrgKb[]) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch { /* The mounted conversation retains its selection in memory. */ }
}

/** One account and conversation own both the picker value and the request scope. */
export function useConversationKnowledge(
  userId: string | undefined,
  conversationId: string,
  defaults: SelectedOrgKb[] = EMPTY,
  orgEnabled = true,
  draftScope = 'chat',
) {
  const recordsRef = useRef(new Map<string, SelectedOrgKb[]>());
  const [records, setRecords] = useState(recordsRef.current);
  const scopedId = conversationId === 'new' ? `new:${draftScope}` : conversationId;
  const key = selectionKey(userId ?? '', scopedId);
  const initial = conversationId === 'new' ? defaults : EMPTY;
  const selected = useMemo(() => {
    if (!userId) return EMPTY;
    const saved = records.get(key) ?? readSelection(key) ?? initial;
    return orgEnabled ? saved : saved.filter((item) => item.type === 'space');
  }, [userId, key, initial, records, orgEnabled]);

  const setSelected = useCallback((update: SetStateAction<SelectedOrgKb[]>) => {
    if (!userId) return;
    const current = recordsRef.current.get(key) ?? readSelection(key) ?? initial;
    const next = typeof update === 'function' ? update(current) : update;
    if (JSON.stringify(next) === JSON.stringify(current) && recordsRef.current.has(key)) return;
    recordsRef.current.set(key, next);
    writeSelection(key, next);
    setRecords(new Map(recordsRef.current));
  }, [userId, key, initial]);

  // The turn supplies its captured scope, so a late response always saves the
  // selection belonging to that turn, even after the user opens another chat.
  const promoteSelection = useCallback((from: string, to: string, snapshot: SelectedOrgKb[]) => {
    if (!userId || from === to) return;
    const source = selectionKey(userId, from === 'new' ? `new:${draftScope}` : from);
    const target = selectionKey(userId, to);
    recordsRef.current.set(target, snapshot);
    writeSelection(target, snapshot);
    const draft = recordsRef.current.get(source) ?? readSelection(source);
    if (JSON.stringify(draft) === JSON.stringify(snapshot)) {
      recordsRef.current.delete(source);
      try { localStorage.removeItem(source); } catch { /* Memory has already advanced. */ }
    }
    setRecords(new Map(recordsRef.current));
  }, [userId, draftScope]);

  return { selectedOrgKbs: selected, setSelectedOrgKbs: setSelected, promoteSelection };
}
