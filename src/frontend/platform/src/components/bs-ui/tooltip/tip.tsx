import { Tooltip, TooltipContent, TooltipTrigger, Portal } from "./index";

export default function Tip({
    content,
    side,
    asChild = true,
    children,
    styleClasses,
    delayDuration = 200,
    align = "center"
}: {
    content: string;
    side: "top" | "right" | "bottom" | "left" | "top-right";
    asChild?: boolean;
    children: React.ReactNode;
    styleClasses?: string;
    delayDuration?: number
    align?: "center" | "start" | "end"
}): JSX.Element {
    return content ? <Tooltip delayDuration={delayDuration}>
        <TooltipTrigger asChild={asChild}>{children}</TooltipTrigger>
        <Portal>
            <TooltipContent
                className={`${styleClasses} text-sm shadow-md`}
                side={side}
                align={align}
                avoidCollisions={false}
                sticky="always"
            >
                <div className=" max-w-96 text-left break-all whitespace-normal">{content}</div>
            </TooltipContent>
        </Portal>
    </Tooltip> : children
}
