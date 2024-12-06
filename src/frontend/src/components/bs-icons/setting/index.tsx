import React, { forwardRef } from "react";
import { cname } from "@/components/bs-ui/utils";
import Setting from "./Setting.svg?react";

export const SettingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className, ...props}, ref) => {
    return <Setting ref={ref} className={cname('text-[#9CA3BA]', className)} {...props} />;
});
