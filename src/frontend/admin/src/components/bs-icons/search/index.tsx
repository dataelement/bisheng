import React, { forwardRef } from "react";
import Search from "./Search.svg?react";

export const SearchIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Search ref={ref} {...props} />;
});
