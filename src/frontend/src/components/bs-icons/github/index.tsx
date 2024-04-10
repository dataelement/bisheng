import React, { forwardRef } from "react";
import { ReactComponent as Github } from "./Github.svg";

export const GithubIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Github ref={ref} {...props} className={className || ''}/>;
});