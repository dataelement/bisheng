import { Button, Switch } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import type { KeyboardEvent, ReactElement } from 'react';
import { cloneElement, useEffect, useId, useRef, useState } from 'react';
import { useDrag, useDrop } from 'react-dnd';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { useWorkbenchNavLinks } from '../useWorkbenchNavLinks';
import type { SidebarPrefs } from './sidebarPrefs';
import {
  DEFAULT_SIDEBAR_PREFS, isDefaultSidebarPrefs, isSameSidebarPrefs, saveSidebarPrefs, useSidebarPrefs,
} from './sidebarPrefs';
import type { SidebarEntry } from './useSidebarEntries';
import { orderSidebarEntries, splitSidebarEntries, useSidebarEntries } from './useSidebarEntries';

const DRAG_TYPE = 'workbench-sidebar-entry';

interface DragItem {
  index: number;
}

interface EntryRowProps {
  entry: SidebarEntry;
  index: number;
  count: number;
  checked: boolean;
  /** Switched on, but past the nav's row cap: it sits under 更多. */
  overflowing: boolean;
  onCheckedChange: (checked: boolean) => void;
  onMove: (from: number, to: number) => void;
}

/**
 * One entry: drag handle, icon + name (the switch's label), switch at the row end
 * (组件-Switch开关.md §3). The whole row is the drop target and the drag preview; only the
 * handle starts a drag, so the switch stays an ordinary click. The handle also reorders
 * from the keyboard with ↑ / ↓.
 */
function EntryRow({ entry, index, count, checked, overflowing, onCheckedChange, onMove }: EntryRowProps) {
  const localize = useLocalize();
  const id = useId();
  const rowRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HTMLButtonElement>(null);

  const [, drop] = useDrop<DragItem>({
    accept: DRAG_TYPE,
    hover(item) {
      if (item.index === index) return;
      onMove(item.index, index);
      // The list has already re-ordered: the dragged entry now lives at this index.
      item.index = index;
    },
  });
  const [{ isDragging }, drag, preview] = useDrag({
    type: DRAG_TYPE,
    item: (): DragItem => ({ index }),
    collect: (monitor) => ({ isDragging: monitor.isDragging() }),
  });
  drag(handleRef);
  preview(drop(rowRef));

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const to = event.key === 'ArrowUp' ? index - 1 : event.key === 'ArrowDown' ? index + 1 : -1;
    if (to < 0 || to >= count) return;
    event.preventDefault();
    onMove(index, to);
  };

  return (
    <div
      ref={rowRef}
      className={cn(
        'flex h-10 w-full items-center gap-1 rounded-lg pr-2 text-body text-text-1 transition-colors hover:bg-fill-1',
        isDragging && 'opacity-40',
      )}
    >
      <button
        ref={handleRef}
        type="button"
        aria-label={`${localize('com_workbench_sidebar.customize_reorder')}: ${entry.label}`}
        onKeyDown={handleKeyDown}
        className="flex h-full w-6 shrink-0 cursor-grab items-center justify-center rounded-md text-text-3 outline-none hover:text-text-1 focus-visible:bg-fill-2 focus-visible:text-text-1 active:cursor-grabbing"
      >
        <Outlined.Drag className="size-4" />
      </button>
      <label htmlFor={id} className="flex h-full min-w-0 flex-1 cursor-pointer items-center gap-2">
        {cloneElement(entry.icon as ReactElement, { className: 'size-4 shrink-0' })}
        <span className="min-w-0 truncate">{entry.label}</span>
        {overflowing && (
          <span className="shrink-0 text-caption text-text-3">{localize('com_workbench_sidebar.customize_in_more')}</span>
        )}
      </label>
      <Switch id={id} size="small" checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

interface SidebarCustomizeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * 管理侧边栏: the module area's entries (the modules, 广场) — drag to order them, switch one
 * off to hide it. The nav shows the first rows that fit; the rest, and the hidden ones,
 * sit under 更多. The dialog edits a DRAFT: 保存 applies it, 取消 / × / the mask drop it.
 */
export function SidebarCustomizeDialog({ open, onOpenChange }: SidebarCustomizeDialogProps) {
  const localize = useLocalize();
  const savedEntries = useSidebarEntries();
  const prefs = useSidebarPrefs();
  const { links } = useWorkbenchNavLinks();
  const [draft, setDraft] = useState<SidebarPrefs>(prefs);

  // Start every visit from what is saved.
  useEffect(() => {
    if (open) setDraft(prefs);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-sync on open only, not while editing
  }, [open]);

  const entries = orderSidebarEntries(savedEntries, draft.order);
  const { shown } = splitSidebarEntries(entries, draft, links.some((link) => link.section === 'home'));

  const handleMove = (from: number, to: number) => {
    const ids = entries.map((entry) => entry.id);
    const [moved] = ids.splice(from, 1);
    ids.splice(to, 0, moved);
    setDraft((prev) => ({ ...prev, order: ids }));
  };
  const handleVisibleChange = (entry: SidebarEntry, visible: boolean) => {
    setDraft((prev) => {
      const rest = prev.hidden.filter((id) => id !== entry.id);
      return { ...prev, hidden: visible ? rest : [...rest, entry.id] };
    });
  };
  const handleSave = () => {
    saveSidebarPrefs(draft);
    onOpenChange(false);
  };

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
          {entries.map((entry, index) => {
            const checked = !draft.hidden.includes(entry.id);
            return (
              <EntryRow
                key={entry.id}
                entry={entry}
                index={index}
                count={entries.length}
                checked={checked}
                overflowing={checked && !shown.includes(entry)}
                onCheckedChange={(next) => handleVisibleChange(entry, next)}
                onMove={handleMove}
              />
            );
          })}
        </div>
        {/* 恢复默认 resets the draft, so it too waits for 保存. Primary action rightmost. */}
        <DialogFooter className="items-center gap-2 sm:justify-between sm:space-x-0">
          <Button
            color="default"
            variant="text"
            disabled={isDefaultSidebarPrefs(draft)}
            onClick={() => setDraft(DEFAULT_SIDEBAR_PREFS)}
          >
            {localize('com_workbench_sidebar.customize_reset')}
          </Button>
          <div className="flex items-center gap-2">
            <Button color="default" variant="outlined" onClick={() => onOpenChange(false)}>
              {localize('com_ui_cancel')}
            </Button>
            <Button disabled={isSameSidebarPrefs(draft, prefs)} onClick={handleSave}>
              {localize('com_ui_save')}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
