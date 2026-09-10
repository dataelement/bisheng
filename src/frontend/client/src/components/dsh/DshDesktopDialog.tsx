import { Button } from '@bisheng/ui';
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query';
import { dshLaunchUrl } from '~/utils/dshLaunch';
import { getDshSessions, getDshUsage, revokeDshSession } from '~/api/dsh';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '~/components/ui/Dialog';
import { useAuthContext, useLocalize } from '~/hooks';
import { useConfirm } from '~/Providers/ConfirmContext';

interface DshDesktopDialogProps { open: boolean; onOpenChange: (open: boolean) => void; downloadUrl: string | null; launchUrl: string }

export function DshDesktopDialog({ open, onOpenChange, downloadUrl, launchUrl }: DshDesktopDialogProps) {
  const t = useLocalize();
  const { user } = useAuthContext();
  const confirm = useConfirm();
  const sessions = useInfiniteQuery({
    queryKey: ['dsh-self-sessions', user?.id], enabled: open, retry: false, staleTime: 0,
    queryFn: ({ pageParam, signal }) => getDshSessions(pageParam as string | undefined, signal),
    getNextPageParam: (page) => page.has_more ? page.next_cursor : undefined,
  });
  const usage = useQuery({ queryKey: ['dsh-self-usage', user?.id], enabled: open, retry: false, staleTime: 0,
    queryFn: ({ signal }) => getDshUsage(signal) });
  const revoke = useMutation({ mutationFn: revokeDshSession, onSuccess: () => { void sessions.refetch(); } });
  async function handleRevoke(sessionId: string, label: string) {
    if (await confirm({ title: t('dsh_revoke_title'), description: t('dsh_revoke_help', { name: label }),
      confirmText: t('dsh_revoke'), variant: 'destructive' })) revoke.mutate(sessionId);
  }
  const time = (value: string | null) => value ? new Date(value).toLocaleString() : '—';
  const number = (value: number | null) => value == null ? '—' : value.toLocaleString();
  const rows = sessions.data?.pages.flatMap((page) => page.items) ?? [];
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="w-[calc(100vw-32px)] max-w-5xl max-h-[85dvh] overflow-y-auto rounded-2xl sm:rounded-2xl text-text-primary">
      <DialogTitle>{t('dsh_title')}</DialogTitle>
      <DialogDescription>{t('dsh_intro')}</DialogDescription>
      <section className="space-y-3 border-b border-border-base pb-5">
        <h3 className="text-h4 font-medium">{t('dsh_local_models')}</h3>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => window.location.assign(dshLaunchUrl(launchUrl))}>{t('dsh_open')}</Button>
          {downloadUrl && <Button color="secondary" variant="outline" onClick={() => window.open(downloadUrl, '_blank', 'noopener,noreferrer')}>{t('dsh_download')}</Button>}
        </div>
        <p className="text-body-sm text-text-secondary">{t('dsh_download_help')}</p>
      </section>
      <section className="space-y-3 border-b border-border-base pb-5">
        <h3 className="text-h4 font-medium">{t('dsh_sessions')}</h3>
        {sessions.isLoading ? <p role="status">{t('dsh_loading')}</p> : sessions.isError ?
          <p role="alert">{t('dsh_load_error')} <Button variant="link" onClick={() => void sessions.refetch()}>{t('dsh_retry')}</Button></p> :
          !rows.length ? <p>{t('dsh_no_sessions')}</p> : <div className="overflow-x-auto">
            <table className="w-full text-body text-left"><thead><tr>
              {['device', 'created', 'last_seen', 'expires', 'state', 'actions'].map((key) => <th key={key} className="p-2 font-medium text-text-secondary">{t(`dsh_${key}`)}</th>)}
            </tr></thead><tbody>{rows.map((row) => {
              const label = row.device_label || t('dsh_unknown_device');
              return <tr key={row.session_id} className="border-t border-border-base">
                <td className="p-2 break-words">{label}</td><td className="p-2">{time(row.created_at)}</td>
                <td className="p-2">{time(row.last_seen_at)}</td><td className="p-2">{time(row.expires_at)}</td>
                <td className="p-2">{['ACTIVE', 'REVOKED', 'EXPIRED'].includes(row.state) ? t(`dsh_state_${row.state}`) : row.state}</td>
                <td className="p-2">{row.state === 'ACTIVE' && <Button variant="link" disabled={revoke.isLoading}
                  loading={revoke.isLoading && revoke.variables === row.session_id} onClick={() => void handleRevoke(row.session_id, label)}>{t('dsh_revoke')}</Button>}</td>
              </tr>;
            })}</tbody></table>
          </div>}
        {revoke.isError && <p role="alert">{t('dsh_revoke_error')}</p>}
        {revoke.isSuccess && <p role="status">{t('dsh_revoked')}</p>}
        {sessions.hasNextPage && <Button color="secondary" variant="outline" loading={sessions.isFetchingNextPage} onClick={() => void sessions.fetchNextPage()}>{t('dsh_more')}</Button>}
      </section>
      <section className="space-y-3">
        <h3 className="text-h4 font-medium">{t('dsh_month_usage')}</h3>
        <p className="text-body-sm text-text-secondary">{t('dsh_quota_help')}</p>
        {usage.isLoading ? <p role="status">{t('dsh_loading')}</p> : usage.isError ?
          <p role="alert">{t('dsh_load_error')} <Button variant="link" onClick={() => void usage.refetch()}>{t('dsh_retry')}</Button></p> : usage.data && <>
            <p className="text-body-sm text-text-secondary">{usage.data.month} · {t(`dsh_source_${usage.data.source}`)} · {time(usage.data.as_of)}</p>
            {!usage.data.models.length ? <p>{t('dsh_no_models')}</p> : <div className="overflow-x-auto"><table className="w-full text-body text-left"><thead><tr>
              {['model', 'used', 'limit', 'remaining'].map((key) => <th key={key} className="p-2 font-medium text-text-secondary">{t(`dsh_${key}`)}</th>)}
            </tr></thead><tbody>{usage.data.models.map((model) => <tr key={model.model_id} className="border-t border-border-base">
              <td className="p-2 break-words">{model.name}</td><td className="p-2">{number(model.used)}</td><td className="p-2">{number(model.limit)}</td><td className="p-2">{number(model.remaining)}</td>
            </tr>)}</tbody></table></div>}
            {!!usage.data.unknown_pending && <p>{t('dsh_unknown_usage', { count: usage.data.unknown_pending })}</p>}
          </>}
      </section>
    </DialogContent>
  </Dialog>;
}
