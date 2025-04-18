import React, { forwardRef } from "react";
import Tip from "./icon.svg?react";

export const TipIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Tip ref={ref} {...props} />;
});
