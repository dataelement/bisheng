import React, { forwardRef } from "react";
import BookOpen from "./BookOpen.svg?react";

export const BookOpenIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <BookOpen ref={ref} {...props} className={className || ''} />;
});
