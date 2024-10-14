import React, { forwardRef } from "react";
import Skill from "./Skill.svg?react";

export const SkillIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Skill ref={ref} {...props} />;
});
