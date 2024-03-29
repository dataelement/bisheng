import React, { forwardRef } from "react";
import { ReactComponent as Info } from "./Info.svg";
import { ReactComponent as Success } from "./Success.svg";
import { ReactComponent as Warning } from "./Warning.svg";
import { ReactComponent as Error } from "./Error.svg";

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
