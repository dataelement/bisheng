import type { ReactNode } from 'react';
interface GreetingMessageProps { title: string; logo?: ReactNode; children: ReactNode; footer?: ReactNode }
/** Client opening message layout, including right-aligned pointer-hover actions. */
export function GreetingMessage({ title, logo, children, footer }: GreetingMessageProps) {
  return <div className="flex w-full"><div className="w-fit group max-w-[90%]">
    <div className="min-h-8 px-4 pt-4 pb-2 rounded-2xl"><div className="flex gap-3">
      {logo}<div className="text-sm max-w-[calc(100%-24px)]">
        <p className="select-none font-semibold text-base mb-1">{title}</p>
        <div className="bs-mkdown text-base">{children}</div>
      </div>
    </div></div>
    <div className="flex justify-end pr-4 fine-pointer:opacity-0 fine-pointer:group-hover:opacity-100 transition-opacity">{footer}</div>
  </div></div>;
}
