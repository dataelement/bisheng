import React, { forwardRef } from "react";
import Assistant from "./assistant.svg?react";
import Skill from "./Skill.svg?react";
import Flow from "./flow.svg?react";

export const AssistantIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Assistant ref={ref} {...props} />;
});

export const SkillIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Skill ref={ref} {...props} />;
});

export const FlowIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Flow ref={ref} {...props} />;
});
