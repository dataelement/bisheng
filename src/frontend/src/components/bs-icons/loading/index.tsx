import React, { forwardRef } from "react";
import { ReactComponent as Load } from "./Load.svg";
import { cname } from "../../bs-ui/utils";

export const LoadIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Load ref={ref} {...props} className={cname('text-gray-50 animate-spin', className)} />;
});
