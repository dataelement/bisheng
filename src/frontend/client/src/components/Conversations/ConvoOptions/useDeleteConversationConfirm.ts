import { showApiError } from "~/api/request";
import { useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import type { TMessage } from '~/types/chat';
import { QueryKeys } from '~/types/chat';
import { useDeleteConversationMutation } from '~/hooks/queries/data-provider';
import { useConfirm } from '~/Providers';
import { useLocalize, useNewConvo } from '~/hooks';
import { stopConversationRun } from '~/api/runApi';
import { useRunStore } from '~/store/runStore';

/** How long the delete waits for the stop request before it goes ahead. */
export const STOP_BEFORE_DELETE_TIMEOUT_MS = 3000;

/**
 * Ask the backend to stop the run of a conversation and wait for the answer,
 * at most `STOP_BEFORE_DELETE_TIMEOUT_MS`. A failed or slow stop is ignored:
 * the delete goes ahead anyway.
 */
async function stopRunBeforeDelete(conversationId: string): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, STOP_BEFORE_DELETE_TIMEOUT_MS);
  });
  try {
    await Promise.race([stopConversationRun(conversationId).then(() => undefined), timeout]);
  } catch {
    // The stop failed: delete anyway.
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Confirm-then-delete for a conversation, shared by the sidebar convo menu and
 * the archived-chats table. Shows the app-wide useConfirm dialog (destructive
 * variant), then deletes and navigates away when the active conversation was
 * the one removed.
 */
export function useDeleteConversationConfirm() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { newConversation } = useNewConvo();
  const { conversationId: currentConvoId } = useParams();
  const deleteConvoMutation = useDeleteConversationMutation();

  return useCallback(
    async ({
      conversationId,
      title,
      retainView,
    }: {
      conversationId: string;
      title: string;
      retainView: () => void;
    }) => {
      const ok = await confirm({
        variant: 'destructive',
        title: localize('com_ui_delete_conversation'),
        description: `${localize('com_ui_delete_confirm')} "${title}"`,
        confirmText: localize('com_ui_delete'),
      });
      if (!ok) {
        return;
      }

      // A run keeps going after its page is left (F004): stop it, or it goes on
      // writing into the deleted conversation. An idle conversation answers "idle".
      // The stop goes first: after the delete the backend no longer lets this
      // user stop the run of the conversation.
      await stopRunBeforeDelete(conversationId);

      const messages = queryClient.getQueryData<TMessage[]>([QueryKeys.messages, conversationId]);
      const thread_id = messages?.[messages.length - 1]?.thread_id;
      const endpoint = messages?.[messages.length - 1]?.endpoint;

      deleteConvoMutation.mutate(
        { conversationId, thread_id, endpoint, source: 'button' },
        {
          onError: showApiError,
          onSuccess: () => {
            // Drop the run state of the deleted conversation, so no page keeps
            // showing (or following) its run.
            useRunStore.getState().resetConversation(conversationId);
            if (currentConvoId === conversationId || currentConvoId === 'new') {
              newConversation();
              navigate('/c/new', { replace: true });
            }
            retainView();
          },
        },
      );
    },
    [confirm, localize, queryClient, deleteConvoMutation, currentConvoId, newConversation, navigate],
  );
}
