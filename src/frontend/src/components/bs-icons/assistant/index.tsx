import React, { forwardRef } from "react";
import Assistant from "./icon.svg?react";

export const AssistantIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Assistant ref={ref} {...props} />;
});
