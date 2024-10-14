import React, { forwardRef } from "react";
import Flag from "./Flag.svg?react";

export const FlagIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Flag ref={ref} {...props} />;
});
