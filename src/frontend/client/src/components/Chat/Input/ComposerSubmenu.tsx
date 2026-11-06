import { createContext, useContext, useId, useLayoutEffect, useRef, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';

export const ComposerMenuContext = createContext<{
  page: string | null;
  setPage: (page: string | null) => void;
}>({ page: null, setPage: () => {} });

/** A clicked category opens its own page within the composer-anchored menu. */
export function ComposerSubmenu({ label, icon, disabled, children }: {
  label: string; icon: ReactNode; disabled?: boolean; children: ReactNode;
}) {
  const { page, setPage } = useContext(ComposerMenuContext);
  const id = useId();
  const localize = useLocalize();
  const active = page === id;
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (active) panel.current?.querySelector<HTMLInputElement>('input')?.focus();
  }, [active]);
  if (page && !active) return null;
  if (active) return <div ref={panel} className="dsh-command-submenu">
    <DropdownMenuItem aria-label={localize('dshChat.backToCapabilities')} className="gap-2" onSelect={(event) => {
      event.preventDefault(); setPage(null);
      requestAnimationFrame(() => trigger.current?.focus());
    }}>
      <ChevronLeft size={16} /><span>{label}</span>
    </DropdownMenuItem>
    <div className="dsh-command-skills">{children}</div>
  </div>;
  return <DropdownMenuItem ref={trigger} disabled={disabled} aria-haspopup="menu" className="gap-2"
    onSelect={(event) => { event.preventDefault(); setPage(id); }}>
    {icon}<span className="dsh-command-name">{label}</span><ChevronRight size={14} className="ml-auto shrink-0" />
  </DropdownMenuItem>;
}
