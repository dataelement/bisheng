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
  /** Stable model ID chosen in the originating input. */
  modelId?: number;
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
  sendMessage: (text: string) => boolean | Promise<boolean>;
  /** Daily mode, model catalog and the fresh chat state are ready. */
  ready: boolean;
  selectedModelId: number;
  selectModel: (id: number) => boolean;
  onModelUnavailable: (ask: ChatAsk) => void;
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
  ready,
  selectedModelId,
  selectModel,
  onModelUnavailable,
  onTake,
}: UseChatAskHandoffParams) {
  const [mountedAsk, setMountedAsk] = useState<ChatAsk | null>(null);
  const submittedAskRef = useRef<ChatAsk | null>(null);
  const preparingAskRef = useRef<ChatAsk | null>(null);
  const [preparedAsk, setPreparedAsk] = useState<ChatAsk | null>(null);
  const [attachmentAsk, setAttachmentAsk] = useState<AttachmentAsk | null>(null);

  const takePendingAsk = useCallback(() => {
    // A fresh conversation owns the imported question.
    if (!pendingAsk || conversationId !== 'new' || activeConversationId !== 'new') return;
    const ask = pendingAsk;
    pendingAsk = null;
    preparingAskRef.current = null;
    setPreparedAsk(null);
    onTake?.();
    setMountedAsk(ask);
  }, [conversationId, activeConversationId, onTake]);

  useEffect(takePendingAsk, [takePendingAsk, locationKey]);
  useActivate(takePendingAsk);

  useEffect(() => {
    const ask = mountedAsk;
    if (!ask || submittedAskRef.current === ask) return;
    if (conversationId !== 'new' || activeConversationId !== 'new' || !ready) return;
    if (preparingAskRef.current !== ask) {
      // Claim preparation before publishing to external stores: their synchronous
      // subscribers can flush this effect again during the same commit.
      preparingAskRef.current = ask;
      setSelectedKbs(ask.space
        ? [{ id: ask.space.id, name: ask.space.name, type: 'space' }]
        : []);
      if (ask.modelId !== undefined && !selectModel(ask.modelId)) {
        setMountedAsk(null);
        onModelUnavailable(ask);
        return;
      }
      // Preparation owns its render transition, including when both selections
      // already match and their setters preserve the existing state.
      setPreparedAsk(ask);
      return;
    }
    // A reentrant commit observes the claim and waits for preparation to finish.
    if (preparedAsk !== ask) return;
    if (ask.modelId !== undefined && selectedModelId !== ask.modelId) return;
    const mounted = ask.space
      ? selectedKbs.length === 1 && selectedKbs[0].type === 'space' && String(selectedKbs[0].id) === ask.space.id
      : selectedKbs.length === 0;
    if (!mounted) return;
    if (ask.attachment) {
      askSeq += 1;
      submittedAskRef.current = ask;
      setAttachmentAsk({ key: `ask-${askSeq}`, text: ask.text, file: ask.attachment });
      setMountedAsk(null);
    } else {
      // Claimed before the (possibly async) send resolves so a re-run cannot send it
      // twice; a rejected send stays staged until the sender accepts it.
      submittedAskRef.current = ask;
      void Promise.resolve(sendMessage(ask.text)).then((accepted) => {
        if (submittedAskRef.current !== ask) return;
        if (accepted) setMountedAsk(null);
        else submittedAskRef.current = null;
      });
    }
  }, [mountedAsk, preparedAsk, conversationId, activeConversationId, ready, selectedModelId, selectModel, onModelUnavailable, selectedKbs, setSelectedKbs, sendMessage]);

  const retireAttachmentAsk = useCallback(() => setAttachmentAsk(null), []);

  return { attachmentAsk, retireAttachmentAsk };
}
