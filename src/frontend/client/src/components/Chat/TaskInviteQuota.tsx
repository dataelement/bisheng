import { useCallback, useEffect, useState } from 'react';
import { Button } from '@bisheng/ui';
import InvitationCodeForm from '~/components/Chat/InviteCode';
import { useLocalize } from '~/hooks';
import { subscribeInviteQuotaRefresh } from '~/hooks/inviteQuotaRefresh';
import { useGetUserLinsightCountQuery } from '~/hooks/queries/queries';

/**
 * Task-mode invite quota. Shown only while `linsight_invitation_code` is on.
 * A send with zero remaining uses opens the bind dialog and does not submit.
 */
export function useTaskInviteQuota(enabled: boolean) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);
    const { data: count, refetch } = useGetUserLinsightCountQuery();

    useEffect(() => {
        if (!enabled) {
            return;
        }
        void refetch();
        return subscribeInviteQuotaRefresh(() => {
            void refetch();
        });
    }, [enabled, refetch]);

    const allowSend = useCallback(() => {
        if (!enabled || count !== 0) {
            return true;
        }
        setOpen(true);
        return false;
    }, [enabled, count]);

    const bar = enabled && typeof count === 'number' ? (
        <div className="mb-2 flex items-center justify-end gap-3 pr-2">
            <span className="text-caption text-text-3">
                {localize('com_linsight_remaining_times', { count })}
            </span>
            {count === 0 && (
                <Button type="button" color="default" variant="outlined" size="small" onClick={() => setOpen(true)}>
                    {localize('com_linsight_activate')}
                </Button>
            )}
        </div>
    ) : null;

    const dialog = enabled ? <InvitationCodeForm showCode={open} setShowCode={setOpen} /> : null;

    return { bar, dialog, allowSend };
}
