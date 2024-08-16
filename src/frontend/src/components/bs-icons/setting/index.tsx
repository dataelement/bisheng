import React, { forwardRef } from "react";
import { ReactComponent as Setting } from "./Setting.svg";
import { cname } from "@/components/bs-ui/utils";

export const SettingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className, ...props}, ref) => {
    return <Setting ref={ref} className={cname('text-[#9CA3BA]', className)} {...props} />;
});
