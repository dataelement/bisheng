import type { ReactNode } from 'react';

export interface MessageFrameProps {
  title: string;
  logo?: ReactNode;
  children: ReactNode;
}

/** Layout extracted from client workflow output messages. */
export function MessageFrame({ title, logo, children }: MessageFrameProps) {
  return <div className="max-w-[600px] min-w-0 w-full px-4">
    <div className="flex items-center gap-3 font-medium pt-3">
      <div className="shrink-0">{logo}</div>
      <span className="text-base">{title}</span>
    </div>
    <div className="p-3 ml-6">{children}</div>
  </div>;
}
