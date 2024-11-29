import React, { forwardRef } from "react";
import Assistant from "./assistant.svg?react";
import Skill from "./Skill.svg?react";
import Flow from "./flow.svg?react";
import Skill2 from "./skill2.svg?react";
import Flow2 from "./flow2.svg?react";

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

export const Skill2Icon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Skill2 ref={ref} {...props} />;
});

export const Flow2Icon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Flow2 ref={ref} {...props} />;
});

