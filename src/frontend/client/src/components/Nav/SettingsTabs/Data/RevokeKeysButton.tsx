import {
  useRevokeAllUserKeysMutation,
  useRevokeUserKeyMutation,
} from '~/hooks/queries';
import React from 'react';
import { Button } from '~/components';
import { useConfirm } from '~/Providers';
import { useLocalize } from '~/hooks';

export const RevokeKeysButton = ({
  endpoint = '',
  all = false,
  disabled = false,
  setDialogOpen,
}: {
  endpoint?: string;
  all?: boolean;
  disabled?: boolean;
  setDialogOpen?: (open: boolean) => void;
}) => {
  const localize = useLocalize();
  const confirm = useConfirm();
  const revokeKeyMutation = useRevokeUserKeyMutation(endpoint);
  const revokeKeysMutation = useRevokeAllUserKeysMutation();

  const handleSuccess = () => {
    if (!setDialogOpen) {
      return;
    }

    setDialogOpen(false);
  };

  const dialogTitle = all
    ? localize('com_ui_revoke_keys')
    : localize('com_ui_revoke_key_endpoint', { 0: endpoint });

  const dialogMessage = all
    ? localize('com_ui_revoke_keys_confirm')
    : localize('com_ui_revoke_key_confirm');

  const handleRevoke = async () => {
    const ok = await confirm({
      variant: 'destructive',
      title: dialogTitle,
      description: dialogMessage,
      confirmText: localize('com_ui_revoke'),
    });
    if (!ok) {
      return;
    }
    if (all) {
      revokeKeysMutation.mutate({});
    } else {
      revokeKeyMutation.mutate({}, { onSuccess: handleSuccess });
    }
  };

  return (
    <Button
      variant="destructive"
      className="flex items-center justify-center rounded-lg transition-colors duration-200"
      onClick={handleRevoke}
      disabled={disabled}
    >
      {localize('com_ui_revoke')}
    </Button>
  );
};
