import React, { forwardRef } from "react";
import { ReactComponent as Form } from "./Form.svg";

export const FormIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Form ref={ref} {...props} />;
});
