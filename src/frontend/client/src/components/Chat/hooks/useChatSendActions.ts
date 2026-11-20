/**
 * Send entries of the conversation page: the composer's send (also used by the
 * question card of a waiting run) and the retry of a failed deep-research
 * turn (F004).
 */
import { useCallback, type MutableRefObject } from "react";
import { isRunActive, isRunAwaitingAnswer } from "~/hooks/unifiedRun";
import { useRunStore } from "~/store/runStore";

type SendMessage = (
  text: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- attachment rows keep the composer's legacy loose shape
  files?: any[] | null,
  opts?: { taskMode?: boolean },
) => Promise<boolean | void>;

export interface UseChatSendActionsOptions {
  /** The composer's deep-research toggle. */
  taskMode: boolean;
  /** The user's role may use deep research. */
  canUseTaskMode: boolean;
  /** Conversation on screen (`"new"` for a draft); key of the run store. */
  conversationId: string;
  sendMessage: SendMessage;
  /** Invite-quota gate of a new deep-research request; false = do not send. */
  allowInviteSend: () => boolean;
  composerIdentity: string;
  composerIdentityRef: MutableRefObject<string>;
  setInputText: (text: string) => void;
}

export function useChatSendActions({
  taskMode,
  canUseTaskMode,
  conversationId,
  sendMessage,
  allowInviteSend,
  composerIdentity,
  composerIdentityRef,
  setInputText,
}: UseChatSendActionsOptions) {
  const handleSend = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- see SendMessage
    async (text: string, files?: any[] | null) => {
      const isTaskTurn = taskMode && canUseTaskMode;
      // F004: an answer to the question a run waits on continues that run. It
      // is not a new deep-research request, so the invite quota is not asked.
      const answering = isRunAwaitingAnswer(useRunStore.getState().conversations[conversationId]?.run);
      if (isTaskTurn && !answering && !allowInviteSend()) return false;
      // Capture the turn's resources before resetting its composer draft. A
      // `false` result (e.g. the department is full) keeps the draft so the
      // user can send again once a slot frees up.
      const sendingIdentity = composerIdentity;
      const accepted = await sendMessage(text, files, { taskMode: isTaskTurn });
      if (accepted && composerIdentityRef.current === sendingIdentity) setInputText("");
      return accepted;
    },
    [
      taskMode,
      canUseTaskMode,
      conversationId,
      sendMessage,
      allowInviteSend,
      composerIdentity,
      composerIdentityRef,
      setInputText,
    ],
  );

  /**
   * F004: retry a failed deep-research turn. The turn's question is sent again
   * as a new deep-research message with the composer's current model, skills,
   * tools and knowledge selection; the composer's draft is left alone. Not sent
   * while a run of the conversation is in progress (the message would steer
   * that run instead of starting a new one).
   */
  const handleRetryTaskTurn = useCallback(
    async (question: string): Promise<boolean> => {
      const text = question.trim();
      if (!canUseTaskMode || !text) return false;
      if (isRunActive(useRunStore.getState().conversations[conversationId]?.run)) return false;
      if (!allowInviteSend()) return false;
      const accepted = await sendMessage(text, null, { taskMode: true });
      return accepted !== false;
    },
    [canUseTaskMode, conversationId, sendMessage, allowInviteSend],
  );

  return { handleSend, handleRetryTaskTurn };
}
