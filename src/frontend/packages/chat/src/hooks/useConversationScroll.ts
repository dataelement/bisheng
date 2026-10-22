import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
export interface ConversationScrollOptions {
  scrollRef: RefObject<HTMLElement>;
  sessionKey: string;
  messages: readonly { key: string; kind?: string }[];
  canLoadOlder: boolean;
  onLoadOlder: () => void | Promise<unknown>;
  onError?: (error: unknown) => void;
}
/** Client scroll-follow policy with a retained prepend anchor and one active query. */
export function useConversationScroll(options: ConversationScrollOptions) {
  const latest = useRef(options);
  latest.current = options;
  const following = useRef(true);
  const previousScrollTop = useRef(0);
  const autoRequestedKey = useRef<string>();
  const [loadRevision, setLoadRevision] = useState(0);
  const loading = useRef<object | null>(null);
  const previous = useRef<{ sessionKey: string; first?: string; last?: string; height: number }>();
  const { scrollRef, sessionKey, messages } = options;
  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const first = messages[0]?.key;
    const last = messages[messages.length - 1]?.key;
    const before = previous.current;
    if (before?.last !== last && messages[messages.length - 1]?.kind === 'user') following.current = true;
    if (!before || before.sessionKey !== sessionKey) {
      following.current = true;
      loading.current = null;
      node.scrollTop = node.scrollHeight;
    } else if (before.first !== first && before.last === last && before.first !== undefined) {
      node.scrollTop += node.scrollHeight - before.height;
    } else if (following.current) {
      node.scrollTop = node.scrollHeight;
    }
    previous.current = { sessionKey, first, last, height: node.scrollHeight };
    previousScrollTop.current = node.scrollTop;
  }, [messages, scrollRef, sessionKey]);
  const loadOlder = useCallback(() => {
    const current = latest.current;
    if (loading.current || !current.canLoadOlder) return false;
    const token = {};
    loading.current = token;
    void Promise.resolve().then(() => current.onLoadOlder()).catch(error => current.onError?.(error)).finally(() => {
      if (loading.current === token) { loading.current = null; setLoadRevision(value => value + 1); }
    });
    return true;
  }, []);
  const fillViewport = useCallback(() => {
    const current = latest.current;
    const node = current.scrollRef.current;
    const first = current.messages[0]?.key;
    const key = `${current.sessionKey}:${first ?? ''}`;
    if (first === undefined || !node || node.clientHeight <= 0 || node.scrollHeight > node.clientHeight || autoRequestedKey.current === key) return;
    if (loadOlder()) autoRequestedKey.current = key;
  }, [loadOlder]);
  useEffect(() => { fillViewport(); }, [fillViewport, messages, sessionKey, options.canLoadOlder, loadRevision]);
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const handleScroll = () => {
      const movedUp = node.scrollTop < previousScrollTop.current;
      // Reading older content always wins over following, even near the bottom.
      following.current = !movedUp && node.scrollHeight - node.scrollTop - node.clientHeight <= 24;
      previousScrollTop.current = node.scrollTop;
      if (node.scrollTop <= 90) loadOlder();
    };
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(fillViewport);
    observer?.observe(node);
    node.addEventListener('scroll', handleScroll);
    return () => { loading.current = null; observer?.disconnect(); node.removeEventListener('scroll', handleScroll); };
  }, [scrollRef, loadOlder, fillViewport]);
}
