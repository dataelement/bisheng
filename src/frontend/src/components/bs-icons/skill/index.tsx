import React, { forwardRef } from "react";
import { ReactComponent as Skill } from "./Skill.svg";

export const SkillIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Skill ref={ref} {...props} />;
});
