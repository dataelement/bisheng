import React, { forwardRef } from "react";
import Clear from "./Clear.svg?react";

export const ClearIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Clear ref={ref} {...props} />;
});
