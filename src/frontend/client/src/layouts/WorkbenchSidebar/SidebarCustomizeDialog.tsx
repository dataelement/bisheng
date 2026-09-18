import { Button, Switch } from '@bisheng/ui';
import type { ReactElement, ReactNode } from 'react';
import { cloneElement, useId } from 'react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { useWorkbenchHubs } from '../useWorkbenchHubs';
import { SidebarSectionLabel } from './SidebarSectionLabel';
import {
  isDefaultSidebarPrefs, resetSidebarPrefs, setHubVisible, setModulePinned, useSidebarPrefs,
} from './sidebarPrefs';

interface PrefRowProps {
  icon: ReactNode;
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}

/** One setting: the whole row is the switch's label (组件-Switch开关.md §3 — switch at the row end). */
function PrefRow({ icon, label, checked, onCheckedChange }: PrefRowProps) {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className="flex h-10 w-full cursor-pointer items-center gap-2 rounded-lg px-2 text-body text-text-1 transition-colors hover:bg-fill-1"
    >
      {cloneElement(icon as ReactElement, { className: 'size-4 shrink-0' })}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <Switch id={id} size="small" checked={checked} onCheckedChange={onCheckedChange} />
    </label>
  );
}

interface SidebarCustomizeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * 自定义侧栏: which hubs show, and which single modules get a row of their own. Every
 * switch applies at once — the sidebar behind the mask is the preview.
 */
export function SidebarCustomizeDialog({ open, onOpenChange }: SidebarCustomizeDialogProps) {
  const localize = useLocalize();
  const hubs = useWorkbenchHubs();
  const prefs = useSidebarPrefs();

  // A hub holding one granted module IS that module in the sidebar, so it is listed
  // once, under its module name, and has nothing to pin.
  const pinnable = hubs.filter((hub) => hub.modules.length > 1).flatMap((hub) => hub.modules);

  return (
    // @bisheng/ui Modal is still `status: draft`, so this follows the client Dialog family.
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100%-40px)] max-w-[400px] rounded-2xl sm:rounded-2xl">
        <DialogHeader>
          <DialogTitle className="font-medium text-text-1">{localize('com_workbench_sidebar.customize')}</DialogTitle>
          <DialogDescription className="text-body-sm text-text-3">
            {localize('com_workbench_sidebar.customize_desc')}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1 pb-1">
          <SidebarSectionLabel>{localize('com_workbench_sidebar.customize_entries')}</SidebarSectionLabel>
          {hubs.map((hub) => {
            const single = hub.modules.length === 1 ? hub.modules[0] : null;
            return (
              <PrefRow
                key={hub.id}
                icon={single ? single.icon : hub.icon}
                label={single ? single.label : hub.label}
                checked={!prefs.hiddenHubs.includes(hub.id)}
                onCheckedChange={(checked) => setHubVisible(hub.id, checked)}
              />
            );
          })}
          {pinnable.length > 0 && (
            <>
              <div className="h-2 shrink-0" />
              <SidebarSectionLabel>{localize('com_workbench_sidebar.customize_pinned')}</SidebarSectionLabel>
              {pinnable.map((link) => (
                <PrefRow
                  key={link.section}
                  icon={link.icon}
                  label={link.label}
                  checked={prefs.pinnedModules.includes(link.section)}
                  onCheckedChange={(checked) => setModulePinned(link.section, checked)}
                />
              ))}
            </>
          )}
        </div>
        <DialogFooter>
          <Button color="default" variant="outlined" disabled={isDefaultSidebarPrefs(prefs)} onClick={resetSidebarPrefs}>
            {localize('com_workbench_sidebar.customize_reset')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
