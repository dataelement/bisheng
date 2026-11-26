import * as Dialog from '@radix-ui/react-dialog';
import type { MutableRefObject, ReactNode } from 'react';
import { useRef } from 'react';

interface WorkbenchSidebarUnderlayProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  triggerRef: MutableRefObject<HTMLElement | null>;
  label: string;
  closeLabel: string;
  children: ReactNode;
}

/** The page slides over this layer; Radix owns focus and background interaction. */
export function WorkbenchSidebarUnderlay({
  open, onOpenChange, triggerRef, label, closeLabel, children,
}: WorkbenchSidebarUnderlayProps) {
  const contentRef = useRef<HTMLDivElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content
        ref={contentRef}
        className="workbench-sidebar-underlay absolute inset-y-0 left-0 z-0 w-[240px] outline-none"
        aria-describedby={undefined}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          // Focusing the close button would open its tooltip and consume Escape.
          const target = contentRef.current?.querySelector<HTMLElement>('a[href]') ?? contentRef.current;
          target?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const trigger = triggerRef.current;
          if (trigger?.isConnected && trigger.getClientRects().length > 0) trigger.focus();
        }}
      >
        <Dialog.Title className="sr-only">{label}</Dialog.Title>
        {children}
      </Dialog.Content>
      <Dialog.Overlay asChild>
        <button
          type="button"
          tabIndex={-1}
          aria-label={closeLabel}
          className="absolute inset-y-0 left-[240px] right-0 z-20 cursor-default bg-transparent"
          onClick={() => onOpenChange(false)}
        />
      </Dialog.Overlay>
    </Dialog.Root>
  );
}
