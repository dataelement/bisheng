import React, { forwardRef } from "react";
import { ReactComponent as Tool } from "./icon.svg";

export const ToolIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Tool ref={ref} {...props} />;
});
