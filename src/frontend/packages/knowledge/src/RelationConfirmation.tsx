import * as AlertDialog from '@radix-ui/react-alert-dialog';
import { Button } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useTranslation } from 'react-i18next';

interface RelationConfirmationProps {
  open: boolean;
  busy: boolean;
  title?: string;
  description: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function RelationConfirmation({ open, busy, title, description, onCancel, onConfirm }: RelationConfirmationProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  return (
    <AlertDialog.Root open={open} onOpenChange={(next) => { if (!next && !busy) onCancel(); }}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-[110] bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <AlertDialog.Content onOpenAutoFocus={(event) => event.preventDefault()} onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }} className="fixed inset-0 z-[110] m-auto flex h-fit max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col items-center gap-4 rounded-2xl border border-border-base bg-bg-page p-5 text-text-1 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] outline-none sm:max-w-[400px]">
          <div className="flex w-full items-center justify-center gap-2 text-center sm:justify-start sm:text-left">
            <Outlined.Attention className="size-5 shrink-0 text-warning" />
            <AlertDialog.Title className="text-h4 font-medium text-text-1">{title ?? t('confirm_link_title')}</AlertDialog.Title>
          </div>
          <AlertDialog.Description className="w-full whitespace-pre-line text-left text-body text-text-1">{description}</AlertDialog.Description>
          <div className="flex w-full flex-row justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <Button color="default" variant="outlined" disabled={busy} onClick={onCancel} className="flex-1 sm:flex-none">{t('cancel')}</Button>
            </AlertDialog.Cancel>
            <Button loading={busy} onClick={onConfirm} className="flex-1 sm:flex-none">{t('confirm')}</Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
