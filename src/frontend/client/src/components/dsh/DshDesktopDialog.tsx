import { Button } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { dshLaunchUrl } from '~/utils/dshLaunch';
import { getDshUsageSummary } from '~/api/dsh';
import { Dialog, DialogContent, DialogTitle } from '~/components/ui/Dialog';
import { useAuthContext, useLocalize } from '~/hooks';
import { DshUsageCalendar } from './DshUsageCalendar';

interface DshDesktopDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  downloadUrl: string | null;
  launchUrl: string;
}

export function DshDesktopDialog({ open, onOpenChange, downloadUrl, launchUrl }: DshDesktopDialogProps) {
  const t = useLocalize();
  const { user } = useAuthContext();
  const usage = useQuery({
    queryKey: ['dsh-self-usage-summary', user?.id], enabled: open && Boolean(user?.id), retry: false, staleTime: 0,
    queryFn: ({ signal }) => getDshUsageSummary(signal),
  });
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent aria-describedby={undefined} className="w-[calc(100vw-32px)] max-w-5xl max-h-[85dvh] overflow-y-auto rounded-2xl sm:rounded-2xl text-text-1">
      <DialogTitle>{t('dsh_title')}</DialogTitle>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => window.location.assign(dshLaunchUrl(launchUrl))}>{t('dsh_open')}</Button>
        {downloadUrl && <Button color="secondary" variant="outline" onClick={() => window.open(downloadUrl, '_blank', 'noopener,noreferrer')}>{t('dsh_download')}</Button>}
      </div>
      {usage.isLoading ? <p role="status">{t('dsh_loading')}</p> : usage.isError ?
        <p role="alert">{t('dsh_load_error')} <Button variant="link" onClick={() => void usage.refetch()}>{t('dsh_retry')}</Button></p> :
        usage.data && <DshUsageCalendar summary={usage.data} />}
    </DialogContent>
  </Dialog>;
}
