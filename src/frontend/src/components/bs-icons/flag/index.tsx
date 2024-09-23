import React, { forwardRef } from "react";
import { ReactComponent as Flag } from "./Flag.svg";

export const FlagIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Flag ref={ref} {...props} />;
});
