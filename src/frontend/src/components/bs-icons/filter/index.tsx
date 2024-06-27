import React, { forwardRef } from "react";
import { ReactComponent as Filter } from "./Filter.svg";

export const FilterIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Filter ref={ref} {...props} />;
});