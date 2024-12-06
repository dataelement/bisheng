import React, { forwardRef } from "react";
import Info from "./Info.svg?react";
import Success from "./Success.svg?react";
import Warning from "./Warning.svg?react";
import Error from "./Error.svg?react";

type Type = 'info' | 'error' | 'success' | 'warning'

export const ToastIcon = forwardRef<
    SVGSVGElement & { type: Type },
    React.PropsWithChildren<{ type?: Type }>
>(({ type = 'info', ...props }, ref) => {
    const coponents = {
        info: Info,
        error: Error,
        success: Success,
        warning: Warning
    }
    const Comp = coponents[type]
    return <Comp ref={ref} {...props} />;
});
