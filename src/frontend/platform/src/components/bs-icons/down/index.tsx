import React, { forwardRef } from "react";
import DropDown from "./DropDown.svg?react";

export const DropDownIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <DropDown ref={ref} {...props} />;
});