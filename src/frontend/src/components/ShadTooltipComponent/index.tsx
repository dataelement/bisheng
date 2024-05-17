import { ShadToolTipType } from "../../types/components";
import { Tooltip, TooltipContent, TooltipTrigger } from "../bs-ui/tooltip";

export default function ShadTooltip({
  content,
  side,
  asChild = true,
  children,
  styleClasses,
  delayDuration = 500,
}: ShadToolTipType): JSX.Element {
  return (
    <Tooltip delayDuration={delayDuration}>
      <TooltipTrigger asChild={asChild}>{children}</TooltipTrigger>

      <TooltipContent
        className={`${styleClasses} bg-popover text-sm shadow-md text-popover-foreground`}
        side={side}
        avoidCollisions={false}
        sticky="always"
      >
        {content}
      </TooltipContent>
    </Tooltip>
  );
}
