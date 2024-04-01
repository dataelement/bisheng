import React, { forwardRef } from "react";
import { ReactComponent as QuestionMark } from "./QuestionMark.svg";

export const QuestionMarkIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <QuestionMark ref={ref} {...props} className={_className} />;
});
