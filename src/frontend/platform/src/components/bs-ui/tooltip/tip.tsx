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
    side: "top" | "right" | "bottom" | "left"|"top-right";
    asChild?: boolean;
    children: React.ReactNode;
    styleClasses?: string;
    delayDuration?: number
}): JSX.Element {
    return (
        <Tooltip delayDuration={delayDuration}>
            <TooltipTrigger asChild={asChild}>{children}</TooltipTrigger>

            <TooltipContent
                className={`${styleClasses} text-sm shadow-md`}
                side={side}
                avoidCollisions={false}
                sticky="always"
            >
                <div className=" max-w-96 text-left break-all whitespace-normal">{content}</div>
            </TooltipContent>
        </Tooltip>
    );
}
