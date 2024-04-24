import React, { forwardRef } from "react";
import { ReactComponent as Clear } from "./Clear.svg";

export const ClearIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Clear ref={ref} {...props} />;
});
