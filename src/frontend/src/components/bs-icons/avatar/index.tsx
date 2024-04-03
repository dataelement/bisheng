import React, { forwardRef } from "react";
import { ReactComponent as Avatar } from "./Avatar.svg";

export const AvatarIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Avatar ref={ref} {...props} />;
});
