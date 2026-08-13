import type { ReactNode } from "react";
import { useRef, useState } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";

interface TruncatedTooltipProps {
  /** Full text, shown only when the rendered element is actually clipped. */
  content: string;
  className?: string;
  as?: "span" | "p" | "div";
  children: ReactNode;
}

/**
 * Tooltip that stays silent unless the wrapped text is truncated — so rows that
 * fit never fire a hover popup.
 */
export function TruncatedTooltip({
  content,
  className,
  as: Tag = "span",
  children,
}: TruncatedTooltipProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- polymorphic `as`: no single element type covers span/p/div refs
  const ref = useRef<any>(null);
  const [open, setOpen] = useState(false);

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setOpen(false);
      return;
    }
    const el = ref.current;
    if (el && (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight)) {
      setOpen(true);
    }
  };

  return (
    <Tooltip open={open} onOpenChange={handleOpenChange}>
      <TooltipTrigger asChild>
        <Tag ref={ref} className={className}>{children}</Tag>
      </TooltipTrigger>
      <TooltipContent side="top" className="z-[120] max-w-xs break-all">
        {content}
      </TooltipContent>
    </Tooltip>
  );
}
