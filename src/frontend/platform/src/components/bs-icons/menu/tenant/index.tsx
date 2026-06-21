import React, { forwardRef } from "react";

// Tenant management menu icon: a two-building "organization / company" glyph
// (shorter annex on the left, taller tower on the right).
// Filled style with even-odd cut-out windows + a doorway, to match the
// other filled sidebar menu icons and stay distinct from the system gear.
export const TenantMenuIcon = forwardRef<
  SVGSVGElement & { className: any },
  React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
  return (
    <svg
      ref={ref}
      {...props}
      className={className || ""}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M3.5 8 H11 V3.5 H20.5 V21 H3.5 Z
           M5 11 H6.5 V12.5 H5 Z
           M8 11 H9.5 V12.5 H8 Z
           M5 14.5 H6.5 V16 H5 Z
           M8 14.5 H9.5 V16 H8 Z
           M13 6.5 H14.5 V8 H13 Z
           M17 6.5 H18.5 V8 H17 Z
           M13 10.5 H14.5 V12 H13 Z
           M17 10.5 H18.5 V12 H17 Z
           M14.5 16 H17 V21 H14.5 Z"
      />
    </svg>
  );
});
