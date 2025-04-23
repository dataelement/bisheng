import React, { forwardRef } from "react";
import SvgInfiniLogo from "./logo";

export const InfiniIcon = forwardRef<SVGSVGElement, React.PropsWithChildren<{}>>(
  (props, ref) => {
    return <SvgInfiniLogo ref={ref} {...props} />;
  },
);
