import { Tooltip, TooltipContent, TooltipTrigger } from "./index";

export default function Tip({
    content,
    side,
    asChild = true,
    children,
    styleClasses,
    delayDuration = 200,
}: {
    content: string;
    side: "top" | "right" | "bottom" | "left";
    asChild?: boolean;
    children: React.ReactNode;
    styleClasses?: string;
    delayDuration?: number
}): JSX.Element {
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
