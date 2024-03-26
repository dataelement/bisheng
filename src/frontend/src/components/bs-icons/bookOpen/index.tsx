import React, { forwardRef } from "react";
import { ReactComponent as BookOpen } from "./BookOpen.svg";

export const BookOpenIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <BookOpen ref={ref} {...props} className={className || ''} />;
});
