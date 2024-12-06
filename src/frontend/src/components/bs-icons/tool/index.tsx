import React, { forwardRef } from "react";
import Tool from "./icon.svg?react";

export const ToolIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Tool ref={ref} {...props} />;
});
