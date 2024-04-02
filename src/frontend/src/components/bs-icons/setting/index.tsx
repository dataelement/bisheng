import React, { forwardRef } from "react";
import { ReactComponent as Setting } from "./Setting.svg";

export const SettingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Setting ref={ref} {...props} />;
});
