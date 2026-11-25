import * as Dialog from '@radix-ui/react-dialog';
import cn from '@bisheng/ui/cn';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { versionDialogStyles as styles } from './versionDialogStyles';

export interface DialogShellProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  closeLabel: string;
  busy?: boolean;
  appearance?: 'history';
  className?: string;
  children: ReactNode;
  footer?: ReactNode;
}

export function DialogShell({ open, onOpenChange, title, closeLabel, busy = false, appearance, className, children, footer }: DialogShellProps) {
  const history = appearance === 'history';
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!busy) onOpenChange(next); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[100] bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          aria-describedby={undefined}
          onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }}
          onPointerDownOutside={(event) => { if (busy) event.preventDefault(); }}
          onInteractOutside={(event) => {
            if (history && event.target instanceof Element && event.target.closest('[data-bisheng-notice]')) event.preventDefault();
          }}
          className={cn(
            'fixed left-1/2 top-1/2 z-[100] flex w-full -translate-x-1/2 -translate-y-1/2 flex-col gap-0 rounded-xl border-none bg-bg-page p-0 text-text-1 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            history && `${styles.historySize} ${styles.historyFrame} border-solid shadow-lg`,
            className,
          )}
        >
          <div className={history ? styles.historyHeader : 'relative shrink-0 border-b border-border-base px-6 py-4 text-left'}>
            <Dialog.Title className={history ? styles.historyTitle : 'text-h4 font-semibold text-text-1'}>{title}</Dialog.Title>
            <Dialog.Close disabled={busy} aria-label={closeLabel} className={`${styles.close} disabled:pointer-events-none disabled:opacity-50`}>
              <X className="size-4" />
            </Dialog.Close>
          </div>
          {children}
          {footer && <div className={history ? styles.footer : 'flex shrink-0 items-center justify-end border-t border-border-base px-6 py-3'}>{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
