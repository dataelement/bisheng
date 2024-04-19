import React, { forwardRef } from "react";
import { ReactComponent as Tip } from "./icon.svg";

export const TipIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Tip ref={ref} {...props} />;
});
