import React, { forwardRef } from "react";
import { ReactComponent as Search } from "./Search.svg";

export const SearchIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Search ref={ref} {...props} />;
});
