import React, { forwardRef } from "react";

export const ApprovalMenuIcon = forwardRef<
  SVGSVGElement & { className: any },
  React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
  return (
    <svg
      ref={ref}
      {...props}
      className={className || ""}
      viewBox="0 0 1024 1024"
      xmlns="http://www.w3.org/2000/svg"
      fill="currentColor"
    >
      <path d="M422.399 601.6V493.323c-79.111-34.622-134.4-113.655-134.4-205.323 0-123.711 100.54-224 224-224 123.711 0 224 100.545 224 224 0 91.814-55.379 170.725-134.4 205.313V601.6h201.472c61.925 0 112.128 49.716 112.128 112.003V825.6H108.801V713.598c0-61.855 50.444-111.998 112.126-111.998h201.472zM153.601 870.4h716.793V960H153.6v-89.6z" />
    </svg>
  );
});
