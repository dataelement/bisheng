import type { ReactNode } from "react";
import {
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";

interface SpacePanelFrameProps {
  title: string;
  presentation?: "page";
  busy?: boolean;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}

export function SpacePanelFrame({
  title,
  presentation,
  busy = false,
  children,
  footer,
  className,
}: SpacePanelFrameProps) {
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
