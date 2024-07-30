import React, { forwardRef } from "react";
import { ReactComponent as Prompt } from "./Prompt.svg";

export const PromptIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Prompt ref={ref} {...props} className={_className} />;
});