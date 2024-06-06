import React, { forwardRef } from "react";
import { ReactComponent as QuestionCircle } from "./QuestionCircle.svg";

export const QuestionCircleIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <QuestionCircle ref={ref} {...props} className={_className} />;
});