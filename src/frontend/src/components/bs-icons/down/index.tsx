import React, { forwardRef } from "react";
import { ReactComponent as DropDown } from "./DropDown.svg";

export const DropDownIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <DropDown ref={ref} {...props} />;
});