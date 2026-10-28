import { useCallback, useEffect, useRef, useState } from 'react';
import { useActivate } from 'react-activation';

/**
 * Module page → 对话 handoff (desktop). A question typed into a module's ask bar — a
 * knowledge space, a channel article — is not answered in place any more: the bar parks
 * it here and routes to /c/new, and the chat view picks it up and sends it in a fresh
 * conversation. The exchange is then an ordinary conversation that shows up in the
 * workbench sidebar's 对话 list like any other, which is the point.
 *
 * What the question is ABOUT has to travel in a form the daily chat understands:
 *   - `space`       a knowledge space → mounted as the conversation's only knowledge source
 *   - `attachment`  anything the chat has no native handle for (an article) → uploaded as
 *                   a file on the first turn; the input sends once it has been parsed
 *
 * A module-level slot rather than router state: ChatView lives inside a KeepAlive cache,
 * where a re-activated tree does not reliably re-run its location-keyed effects, and the
 * slot can be read from both the location effect and the activation hook, whichever fires.
 */
export interface ChatAsk {
  text: string;
  space?: { id: string; name: string };
  attachment?: File;
}

/** An ask whose attachment the chat input still has to upload before sending. */
export interface AttachmentAsk {
  /** Unique per ask — the input uses it to run each ask exactly once. */
  key: string;
  text: string;
  file: File;
}

/** The chat's knowledge selection as the store types it (`type` is a plain string there). */
type KbSelection = { id: string; name: string; type: string };

let pendingAsk: ChatAsk | null = null;
let askSeq = 0;

export function parkChatAsk(ask: ChatAsk) {
  pendingAsk = ask;
}

interface UseChatAskHandoffParams {
  conversationId: string;
  /** Conversation currently bound to the send callback. */
  activeConversationId: string;
  /** Changes on every navigation — the usual wake-up call. */
  locationKey: string;
  selectedKbs: KbSelection[];
  setSelectedKbs: (next: KbSelection[]) => void;
  sendMessage: (text: string) => boolean;
  /** Runs as the ask is taken — the cached chat tab may still be in some other mode. */
  onTake?: () => void;
}

/**
 * ChatView side of the handoff. Returns the attachment ask (if any) for the landing
 * input to run, and the callback that retires it.
 */
export function useChatAskHandoff({
  conversationId,
  activeConversationId,
  locationKey,
  selectedKbs,
  setSelectedKbs,
  sendMessage,
  onTake,
}: UseChatAskHandoffParams) {
  // Commit the ask together with its selection before using the send callback.
  const [stagedAsk, setStagedAsk] = useState<ChatAsk | null>(null);
  const submittedAskRef = useRef<ChatAsk | null>(null);
  const [attachmentAsk, setAttachmentAsk] = useState<AttachmentAsk | null>(null);

  const takePendingAsk = useCallback(() => {
    // The route and the chat hook commit their conversation changes separately.
    // Take the ask once both identify the fresh conversation.
    if (!pendingAsk || conversationId !== 'new' || activeConversationId !== 'new') return;
    const ask = pendingAsk;
    pendingAsk = null;
    onTake?.();
    if (ask.attachment) {
      // The article is the whole context; a knowledge source left mounted from an
      // earlier chat would only blur the answer.
      setSelectedKbs([]);
      askSeq += 1;
      setAttachmentAsk({ key: `ask-${askSeq}`, text: ask.text, file: ask.attachment });
      return;
    }
    if (ask.space) {
      setSelectedKbs([{ id: ask.space.id, name: ask.space.name, type: 'space' }]);
    }
    setStagedAsk(ask);
  }, [conversationId, activeConversationId, setSelectedKbs, onTake]);

  useEffect(takePendingAsk, [takePendingAsk, locationKey]);
  useActivate(takePendingAsk);

  useEffect(() => {
    if (!stagedAsk || submittedAskRef.current === stagedAsk) return;
    if (conversationId !== 'new' || activeConversationId !== 'new') return;
    if (stagedAsk.space) {
      const mounted = selectedKbs.length === 1 && selectedKbs[0].type === 'space'
        && String(selectedKbs[0].id) === stagedAsk.space.id;
      if (!mounted) return;
    }
    // A rejected send remains staged until the chat is ready to accept it.
    if (sendMessage(stagedAsk.text)) {
      submittedAskRef.current = stagedAsk;
      setStagedAsk(null);
    }
  }, [stagedAsk, conversationId, activeConversationId, selectedKbs, sendMessage]);

  const retireAttachmentAsk = useCallback(() => setAttachmentAsk(null), []);

  return { attachmentAsk, retireAttachmentAsk };
}
