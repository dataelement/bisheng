import React, { forwardRef } from "react";
import { ReactComponent as Quit } from "./Quit.svg";
import { ReactComponent as QuitDark } from "./Quit-dark.svg";

export const QuitIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Quit ref={ref} {...props} className={className || ''}/>;
});

export const QuitIconDark = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <QuitDark ref={ref} {...props} className={className || ''}/>;
});