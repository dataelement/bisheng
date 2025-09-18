import React, { forwardRef } from "react";
import Knowledge from "./Knowledge.svg?react";
import Book from "./file-logo.svg?react";
import Qa from "./qa-logo.svg?react";

export const KnowledgeIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Knowledge ref={ref} {...props} className={className || ''} />;
});

export const BookIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Book ref={ref} {...props} className={className || ''} />;
});


export const QaIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Qa ref={ref} {...props} className={className || ''} />;
});