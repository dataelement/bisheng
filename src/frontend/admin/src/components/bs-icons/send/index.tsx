import React, { forwardRef } from "react";
import Send from "./Send.svg?react";

export const SendIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Send ref={ref} {...props} />;
});
