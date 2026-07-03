import { useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import type { TMessage } from '~/types/chat';
import { QueryKeys } from '~/types/chat';
import { useDeleteConversationMutation } from '~/hooks/queries/data-provider';
import { useConfirm } from '~/Providers';
import { useLocalize, useNewConvo } from '~/hooks';

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

      const messages = queryClient.getQueryData<TMessage[]>([QueryKeys.messages, conversationId]);
      const thread_id = messages?.[messages.length - 1]?.thread_id;
      const endpoint = messages?.[messages.length - 1]?.endpoint;

      deleteConvoMutation.mutate(
        { conversationId, thread_id, endpoint, source: 'button' },
        {
          onSuccess: () => {
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
