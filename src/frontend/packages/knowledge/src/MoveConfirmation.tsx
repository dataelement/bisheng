import * as AlertDialog from '@radix-ui/react-alert-dialog';
import { Button } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';

export interface MoveConfirmationProps {
  open: boolean;
  busy?: boolean;
  title: string;
  description: ReactNode;
  cancelText: string;
  confirmText: string;
  canConfirm?: boolean;
  canCancel?: boolean;
  hideCancel?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/** Shared confirmation chrome, matching the client's existing move confirmations. */
export function MoveConfirmation({ open, busy = false, title, description, cancelText, confirmText,
  canConfirm = true, canCancel = true, hideCancel = false, onCancel, onConfirm }: MoveConfirmationProps) {
  return <AlertDialog.Root open={open} onOpenChange={(next) => { if (!next && !busy && canCancel) onCancel(); }}>
    <AlertDialog.Portal>
      <AlertDialog.Overlay className="fixed inset-0 z-modal bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
      <AlertDialog.Content onOpenAutoFocus={(event) => event.preventDefault()}
        onEscapeKeyDown={(event) => { if (busy || !canCancel) event.preventDefault(); }}
        className="fixed inset-0 z-modal m-auto flex h-fit max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col items-center gap-4 rounded-2xl border border-border-base bg-bg-page p-5 text-text-1 shadow-[0_0_16px_0_rgba(3,7,117,0.05)] outline-none sm:max-w-[400px]">
        <div className="flex w-full shrink-0 items-center justify-center gap-2 text-center sm:justify-start sm:text-left">
          <Outlined.Attention aria-hidden className="size-5 shrink-0 text-warning" />
          <AlertDialog.Title className="text-h4 font-medium leading-6 text-text-1">{title}</AlertDialog.Title>
        </div>
        <AlertDialog.Description asChild>
          <div className="min-h-0 w-full overflow-y-auto whitespace-pre-line text-left text-body leading-[22px] text-text-1">{description}</div>
        </AlertDialog.Description>
        <div className="flex w-full shrink-0 flex-row justify-end gap-2">
          {!hideCancel && <Button color="default" variant="outlined" disabled={busy || !canCancel} onClick={onCancel} className="flex-1 sm:flex-none">{cancelText}</Button>}
          <Button loading={busy} disabled={busy || !canConfirm} onClick={onConfirm} className="flex-1 sm:flex-none">{confirmText}</Button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Portal>
  </AlertDialog.Root>;
}
