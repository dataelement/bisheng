import { Button } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { dshLaunchUrl } from '~/utils/dshLaunch';
import { getDshUsageSummary } from '~/api/dsh';
import { useAuthContext, useLocalize } from '~/hooks';
import { DshUsageCalendar } from './DshUsageCalendar';

interface DshDesktopPanelProps {
  downloadUrl: string | null;
  launchUrl: string;
}

export function DshDesktopPanel({ downloadUrl, launchUrl }: DshDesktopPanelProps) {
  const t = useLocalize();
  const { user } = useAuthContext();
  // The launch is a protocol handover the page cannot observe, so the guidance
  // stays up until the user leaves this section.
  const [launchAttempted, setLaunchAttempted] = useState(false);
  const handleOpenDesktop = () => {
    setLaunchAttempted(true);
    window.location.assign(dshLaunchUrl(launchUrl));
  };
  const usage = useQuery({
    queryKey: ['dsh-self-usage-summary', user?.id], enabled: Boolean(user?.id), retry: false, staleTime: 0,
    queryFn: ({ signal }) => getDshUsageSummary(signal),
  });
  return <>
    <div className="flex flex-wrap gap-2">
      <Button onClick={handleOpenDesktop}>{t('dsh_open')}</Button>
      {downloadUrl && <Button color="secondary" variant="outline" onClick={() => window.open(downloadUrl, '_blank', 'noopener,noreferrer')}>{t('dsh_download')}</Button>}
    </div>
    {launchAttempted && <p role="status" className="text-body-sm text-text-2">
      {t(downloadUrl ? 'dsh.launchHelp' : 'dsh.launchHelpNoDownload')}
    </p>}
    {usage.isLoading ? <p role="status">{t('dsh_loading')}</p> : usage.isError ?
      <p role="alert">{t('dsh_load_error')} <Button variant="link" onClick={() => void usage.refetch()}>{t('dsh_retry')}</Button></p> :
      usage.data && <DshUsageCalendar summary={usage.data} />}
  </>;
}
