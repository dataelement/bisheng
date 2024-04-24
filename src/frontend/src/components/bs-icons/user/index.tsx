import React, { forwardRef } from "react";
import { ReactComponent as User } from "./User.svg";

export const UserIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <User ref={ref} {...props} />;
});
