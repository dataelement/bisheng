import React from 'react';
import { useClearConversationsMutation } from '~/hooks/queries';
import { Label, Button } from '~/components';
import { useConfirm } from '~/Providers';
import { useLocalize, useNewConvo } from '~/hooks';

export const ClearChats = () => {
  const localize = useLocalize();
  const confirm = useConfirm();
  const { newConversation } = useNewConvo();
  const clearConvosMutation = useClearConversationsMutation();

  const handleClear = async () => {
    const ok = await confirm({
      variant: 'destructive',
      title: localize('com_nav_confirm_clear'),
      description: localize('com_nav_clear_conversation_confirm_message'),
      confirmText: localize('com_ui_delete'),
    });
    if (!ok) {
      return;
    }
    clearConvosMutation.mutate({}, { onSuccess: () => newConversation() });
  };

  return (
    <div className="flex items-center justify-between">
      <Label className="font-light">{localize('com_nav_clear_all_chats')}</Label>
      <Button
        variant="destructive"
        className="flex items-center justify-center rounded-lg transition-colors duration-200"
        onClick={handleClear}
      >
        {localize('com_ui_delete')}
      </Button>
    </div>
  );
};
