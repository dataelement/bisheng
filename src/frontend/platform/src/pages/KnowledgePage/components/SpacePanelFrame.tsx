import { Button, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { ReactNode } from "react";
import {
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";

interface SpacePanelFrameProps {
  title: string;
  presentation?: "page" | "inline";
  hideTitle?: boolean;
  busy?: boolean;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  back?: { label: string; onClick: () => void };
}

export function SpacePanelFrame({
  title,
  presentation,
  hideTitle = false,
  busy = false,
  children,
  footer,
  className,
  back,
}: SpacePanelFrameProps) {
  if (presentation === "inline")
    return (
      <section className="min-w-0 space-y-4">
        {!hideTitle && (
          <h4 className="text-base font-medium text-text-1">{title}</h4>
        )}
        {children}
        {footer && (
          <div className="flex flex-wrap justify-end gap-2">{footer}</div>
        )}
      </section>
    );
  if (presentation === "page" && back)
    return (
      <section className="flex h-full min-h-0 min-w-0 flex-col px-4 pt-4">
        <header className="flex h-8 shrink-0 items-center gap-3">
          <Tooltip content={back.label}>
            <Button
              type="button"
              variant="text"
              color="default"
              size="small"
              iconOnly
              aria-label={back.label}
              disabled={busy}
              onClick={back.onClick}
            >
              <Outlined.ArrowLeft aria-hidden />
            </Button>
          </Tooltip>
          <span aria-hidden className="h-3 w-px bg-border-base" />
          <h1 className="text-body font-medium text-text-1">{title}</h1>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto py-4">
          <div className="mx-auto w-full max-w-[648px]">{children}</div>
        </div>
        {footer && (
          <footer className="flex min-h-16 shrink-0 flex-wrap items-center justify-center gap-3 border-t border-border-base py-2 max-[768px]:[&>button]:flex-1">
            {footer}
          </footer>
        )}
      </section>
    );
  if (presentation === "page")
    return (
      <section className="max-w-4xl space-y-4 py-4">
        <h2 className="text-heading-sm font-medium text-text-1">{title}</h2>
        {children}
        {footer && (
          <div className="flex flex-wrap justify-end gap-2">{footer}</div>
        )}
      </section>
    );
  return (
    <DialogContent
      close={!busy}
      className={className ?? "max-h-[90vh] overflow-y-auto sm:max-w-3xl"}
      aria-describedby={undefined}
      onEscapeKeyDown={(event) => {
        if (busy) event.preventDefault();
      }}
      onPointerDownOutside={(event) => {
        if (busy) event.preventDefault();
      }}
    >
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
      </DialogHeader>
      {children}
      {footer && <DialogFooter>{footer}</DialogFooter>}
    </DialogContent>
  );
}
