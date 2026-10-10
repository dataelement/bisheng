import { Dialog, DialogContent, DialogTitle } from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { DshDesktopPanel } from './DshDesktopPanel';

interface DshDesktopDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  downloadUrl: string | null;
  launchUrl: string;
}

export function DshDesktopDialog({ open, onOpenChange, downloadUrl, launchUrl }: DshDesktopDialogProps) {
  const t = useLocalize();
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent aria-describedby={undefined} className="w-[calc(100vw-32px)] max-w-5xl max-h-[85dvh] overflow-y-auto rounded-2xl sm:rounded-2xl text-text-1">
      <DialogTitle>{t('dsh_title')}</DialogTitle>
      <DshDesktopPanel active={open} downloadUrl={downloadUrl} launchUrl={launchUrl} />
    </DialogContent>
  </Dialog>;
}
