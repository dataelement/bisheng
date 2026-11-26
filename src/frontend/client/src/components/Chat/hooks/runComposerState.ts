/**
 * F004 — what the conversation input box shows for the state of the run.
 * The run store only holds conversations whose events the page follows, so
 * every reader here is inert on a carrier that follows none.
 */
import { useEffect, type Dispatch, type SetStateAction } from "react";
import { useRunStore } from "~/store/runStore";
import { mergeReturnedText } from "~/store/runUnread";

/**
 * F004: true after the user stopped the run of this conversation and until
 * the next run starts. The input box then says that a message continues the
 * work.
 */
export function useRunStopped(conversationId: string): boolean {
  return useRunStore((state) => {
    if (!conversationId) return false;
    return state.conversations[conversationId]?.run?.status === "stopped";
  });
}

/**
 * F004 design §7 items 1 and 6: messages a run never read come back when the
 * user stops it (or when the run that should have answered them could not be
 * created). Their text is put into the input box, before what the user has
 * typed there since, so nothing is lost and it can be sent again.
 */
export function useReturnedDraft(conversationId: string, setInputText: Dispatch<SetStateAction<string>>): void {
  const returned = useRunStore((state) =>
    conversationId ? (state.conversations[conversationId]?.draftReturn ?? null) : null,
  );
  useEffect(() => {
    if (!returned) return;
    setInputText((current) => mergeReturnedText(returned, current));
    useRunStore.getState().clearDraftReturn(conversationId);
  }, [returned, conversationId, setInputText]);
}

interface ComposerPlaceholderState {
  /** The run waits for an answer the input box can take. */
  runAwaitingAnswer: boolean;
  /** The user stopped the latest run. */
  runStopped: boolean;
  /** A run is going on and takes further messages. */
  runTakesMessages?: boolean;
  taskMode: boolean;
  /** Admin-configured placeholder of deep research. */
  taskPlaceholder?: string;
}

/** Placeholder of the conversation input box; undefined keeps the input's own default. */
export function composerPlaceholder(
  t: (key: string) => string,
  state: ComposerPlaceholderState,
): string | undefined {
  if (state.runAwaitingAnswer) return t("com_linsight_answer_placeholder");
  if (state.runStopped) return t("runComposer.stoppedPlaceholder");
  if (state.runTakesMessages) return t("runComposer.runningPlaceholder");
  if (state.taskMode) return state.taskPlaceholder || t("com_linsight_input_placeholder");
  return undefined;
}
