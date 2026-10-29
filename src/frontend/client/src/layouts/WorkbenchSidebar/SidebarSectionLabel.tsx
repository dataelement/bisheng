import type { ReactNode } from 'react';

interface SidebarSectionLabelProps {
  children: ReactNode;
}

/** Muted 12px group heading (项目 / 对话) — Figma 13139:111606. */
export function SidebarSectionLabel({ children }: SidebarSectionLabelProps) {
  return <div className="w-full shrink-0 truncate px-2 py-[5px] text-caption text-text-3">{children}</div>;
}
