import React, { forwardRef } from "react";
import { ReactComponent as Assistant } from "./icon.svg";

export const AssistantIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Assistant ref={ref} {...props} />;
});
