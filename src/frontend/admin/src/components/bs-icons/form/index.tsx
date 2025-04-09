import React, { forwardRef } from "react";
import Form from "./Form.svg?react";

export const FormIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Form ref={ref} {...props} />;
});
