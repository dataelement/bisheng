import React, { forwardRef } from "react";
import Helper from "./helper.svg?react";
import Flow from "./flow.svg?react";
import Abilities from "./Abilities.svg?react";

export const HelperIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Helper ref={ref} {...props} />;
});

export const FlowIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Flow ref={ref} {...props} />;
});

export const AbilitiesIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Abilities ref={ref} {...props} />;
});
