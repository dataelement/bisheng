import React, { forwardRef } from "react";
import { ReactComponent as Send } from "./Send.svg";

export const SendIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Send ref={ref} {...props} />;
});
