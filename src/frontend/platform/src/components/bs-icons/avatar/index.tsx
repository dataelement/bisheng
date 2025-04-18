import React, { forwardRef } from "react";
import Avatar from "./Avatar.svg?react";

export const AvatarIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Avatar ref={ref} {...props} />;
});
