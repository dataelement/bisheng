import { cloneElement, type MouseEvent, type ReactElement, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '~/utils';

export const SIDEBAR_NAV_ROW_CLASS_NAME = 'flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-body text-text-1 transition-colors hover:bg-fill-1';

interface SidebarNavRowProps {
  to: string;
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
  entryId?: string;
}

export function SidebarNavRow({ to, icon, label, active = false, onClick, entryId }: SidebarNavRowProps) {
  return (
    <Link to={to} onClick={onClick} aria-current={active ? 'page' : undefined} data-zh-home-entry={entryId === 'home' ? 'true' : undefined} id={entryId === 'zhgyl-forecast' ? 'procurement-forecast-navigation' : undefined} className={cn(SIDEBAR_NAV_ROW_CLASS_NAME, active && 'active bg-fill-2 hover:bg-fill-2', entryId === 'zhgyl-orders' && 'zh-orders-entry', entryId === 'zhgyl-forecast' && 'zh-forecast-entry')}>
      {cloneElement(icon as ReactElement, { className: 'size-4 shrink-0' })}
      <span className="min-w-0 flex-1 truncate py-px">{label}</span>
    </Link>
  );
}
