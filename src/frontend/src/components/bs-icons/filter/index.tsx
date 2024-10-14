import React, { forwardRef } from "react";
import Filter from "./Filter.svg?react";

export const FilterIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Filter ref={ref} {...props} />;
});