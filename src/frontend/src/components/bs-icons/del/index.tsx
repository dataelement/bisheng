import React, { forwardRef } from "react";
import { ReactComponent as Del } from "./Del.svg";

export const DelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Del ref={ref} {...props} />;
});
