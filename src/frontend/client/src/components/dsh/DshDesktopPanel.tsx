import { Button } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { dshLaunchUrl } from '~/utils/dshLaunch';
import { getDshUsageSummary } from '~/api/dsh';
import { useAuthContext, useLocalize } from '~/hooks';
import { DshUsageCalendar } from './DshUsageCalendar';

interface DshDesktopPanelProps {
  /** Usage loads only when the panel is on screen; the dialog passes its open state. */
  active: boolean;
  downloadUrl: string | null;
  launchUrl: string;
}

/**
 * Launch/download actions plus the usage calendar. Shared so the dialog and the
 * settings section show the same thing rather than drifting apart.
 */
export function DshDesktopPanel({ active, downloadUrl, launchUrl }: DshDesktopPanelProps) {
  const t = useLocalize();
  const { user } = useAuthContext();
  const usage = useQuery({
    queryKey: ['dsh-self-usage-summary', user?.id], enabled: active && Boolean(user?.id), retry: false, staleTime: 0,
    queryFn: ({ signal }) => getDshUsageSummary(signal),
  });
  return <>
    <div className="flex flex-wrap gap-2">
      <Button onClick={() => window.location.assign(dshLaunchUrl(launchUrl))}>{t('dsh_open')}</Button>
      {downloadUrl && <Button color="secondary" variant="outline" onClick={() => window.open(downloadUrl, '_blank', 'noopener,noreferrer')}>{t('dsh_download')}</Button>}
    </div>
    {usage.isLoading ? <p role="status">{t('dsh_loading')}</p> : usage.isError ?
      <p role="alert">{t('dsh_load_error')} <Button variant="link" onClick={() => void usage.refetch()}>{t('dsh_retry')}</Button></p> :
      usage.data && <DshUsageCalendar summary={usage.data} />}
  </>;
}
