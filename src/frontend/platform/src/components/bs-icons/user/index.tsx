import React, { forwardRef } from "react";
import User from "./User.svg?react";

export const UserIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <User ref={ref} {...props} />;
});
