import * as Dialog from '@radix-ui/react-dialog';
import { Button, SearchInput, TreeNavigation, TreeNavigationList, TreeNavigationNode } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MoveFolderTree } from './MoveFolderTree';
import type { MoveDestinationItem, MoveDestinationServices, MoveSpaceGroups, MoveTarget } from './moveTypes';
import { serviceIdentity } from './serviceIdentity';
import { useMoveResource } from './useMoveResource';

export interface MoveToDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentSpaceId: string;
  currentSpaceName?: string;
  services: MoveDestinationServices;
  onError: (error: unknown) => void;
  /** The host owns precheck, execution, feedback and retry after the picker closes. */
  onConfirm: (targetSpaceId: string, targetFolderId: string | null, crossSpace: boolean, targetFolderName?: string) => Promise<void> | void;
}

const categoryLabels = {
  department: 'department_spaces',
  created: 'created_by_me',
  joined: 'joined_by_me',
  available: 'available_spaces',
} as const;
type Category = keyof MoveSpaceGroups;

function fileGlyph(name: string) {
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  if (['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'].includes(extension)) return Outlined.FileAudio;
  if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(extension)) return Outlined.FileVideo;
  if (['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'].includes(extension)) return Outlined.FileImage;
  return Outlined.File;
}

function DestinationContents({ services, selection, onSelect, onError }: {
  services: MoveDestinationServices;
  selection: MoveTarget | null;
  onSelect: (selection: MoveTarget) => void;
  onError: (error: unknown) => void;
}) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.move' });
  const spaceId = selection?.spaceId;
  const folderId = selection?.folderId ?? null;
  const load = useCallback((signal: AbortSignal) => spaceId
    ? services.listChildren(spaceId, folderId, signal)
    : Promise.resolve<MoveDestinationItem[]>([]), [services, spaceId, folderId]);
  const resource = useMoveResource(load, onError);
  const folders = resource.data?.filter((item) => item.type === 'folder') ?? [];
  const files = resource.data?.filter((item) => item.type === 'file') ?? [];
  return (
    <div className="scrollbar-os min-h-0 min-w-0 flex-1 overflow-y-auto p-2 max-[768px]:hidden">
      {resource.loading ? (
        <div role="status" className="flex h-full items-center justify-center text-text-3">
          <Outlined.Loading aria-label={t('loading')} className="size-5 animate-spin" />
        </div>
      ) : resource.error ? (
        <div className="flex h-full flex-col items-center justify-center text-caption text-text-3">
          <span>{t('load_failed')}</span><Button variant="text" onClick={resource.retry}>{t('retry')}</Button>
        </div>
      ) : !folders.length && !files.length ? (
        <div className="flex h-full items-center justify-center text-caption text-text-3">{t('empty_folder')}</div>
      ) : <>
        {folders.map((folder) => (
          <button key={`folder:${folder.id}`} type="button"
            onClick={() => { if (spaceId) onSelect({ spaceId, folderId: folder.id, folderName: folder.name }); }}
            className="flex h-7 w-full items-center rounded-md px-1 text-left text-caption hover:bg-fill-1">
            <span className="flex size-5 shrink-0 items-center justify-center"><Outlined.FolderClose aria-hidden className="size-3.5 text-text-1" /></span>
            <span className="ml-0.5 min-w-0 flex-1 truncate text-text-1">{folder.name}</span>
            <Outlined.Right aria-hidden className="size-3.5 shrink-0 text-text-4" />
          </button>
        ))}
        {files.map((file) => {
          const Glyph = fileGlyph(file.name);
          return <div key={`file:${file.id}`} aria-disabled="true" className="flex h-7 w-full cursor-default items-center px-1 text-caption text-text-3">
            <span className="flex size-5 shrink-0 items-center justify-center"><Glyph aria-hidden className="size-3.5" /></span>
            <span className="ml-0.5 min-w-0 flex-1 truncate">{file.name}</span>
          </div>;
        })}
      </>}
    </div>
  );
}

function MoveToContent({ services, currentSpaceId, onOpenChange, onConfirm, onError }: MoveToDialogProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.move' });
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<MoveTarget | null>(null);
  const [expandedSpaces, setExpandedSpaces] = useState<Set<string>>(() => new Set());
  const [visitedSpaces, setVisitedSpaces] = useState<Set<string>>(() => new Set());
  const [collapsedCategories, setCollapsedCategories] = useState<Set<Category>>(() => new Set());
  const loadSpaces = useCallback((signal: AbortSignal) => services.listSpaces(signal), [services]);
  const catalog = useMoveResource(loadSpaces, onError);
  const groups = catalog.data;

  useEffect(() => {
    if (!groups) return;
    const spaces = [...groups.department, ...groups.created, ...groups.joined, ...groups.available ?? []];
    if (selection && spaces.some((space) => space.id === selection.spaceId)) return;
    const initial = spaces.find((space) => space.id === currentSpaceId) ?? spaces[0];
    setSelection(initial ? { spaceId: initial.id, folderId: null } : null);
    if (initial) {
      setExpandedSpaces((previous) => new Set(previous).add(initial.id));
      setVisitedSpaces((previous) => new Set(previous).add(initial.id));
    }
  }, [groups, currentSpaceId, selection]);

  const categories = (Object.keys(categoryLabels) as Category[]).map((key) => ({
    key,
    spaces: groups?.[key]?.filter((space) => space.name.toLowerCase().includes(search.trim().toLowerCase())) ?? [],
  })).filter((category) => category.spaces.length);
  const toggleSpace = (id: string) => {
    setExpandedSpaces((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) next.add(id);
      return next;
    });
    setVisitedSpaces((previous) => new Set(previous).add(id));
  };
  const handleConfirm = () => {
    if (!selection) return;
    // Release the modal before the host opens precheck confirmations or toasts.
    onOpenChange(false);
    void Promise.resolve(onConfirm(selection.spaceId, selection.folderId,
      selection.spaceId !== currentSpaceId, selection.folderName)).catch(() => {
      // Execution errors are surfaced by the host move controller.
    });
  };

  return (
    <Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-modal bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
    <Dialog.Content aria-describedby={undefined} onOpenAutoFocus={(event) => event.preventDefault()}
      className="fixed left-1/2 top-1/2 z-modal flex w-[calc(100vw-32px)] max-w-3xl -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-lg border border-border-base bg-bg-page p-5 text-text-1 shadow-lg outline-none duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:gap-3 max-[768px]:rounded-none max-[768px]:p-4">
      <Dialog.Title className="text-h4 font-semibold leading-none tracking-tight">{t('title')}</Dialog.Title>
      <Dialog.Close aria-label={t('close')} className="absolute right-4 top-4 rounded-sm text-text-2 opacity-70 transition-opacity hover:opacity-100">
        <Outlined.Close aria-hidden className="size-4" />
      </Dialog.Close>
      <div className="flex h-[420px] overflow-hidden rounded-lg border border-border-base max-[768px]:h-auto max-[768px]:min-h-0 max-[768px]:flex-1 max-[768px]:rounded-none max-[768px]:border-0">
        <div className="flex w-72 shrink-0 flex-col border-r border-border-base max-[768px]:w-full max-[768px]:border-r-0">
          <div className="p-3 max-[768px]:px-0 max-[768px]:pt-0">
            <SearchInput aria-label={t('search_placeholder')} placeholder={t('search_placeholder')}
              clearLabel={t('clear_search')} value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          {catalog.loading ? <div role="status" className="flex flex-1 items-center justify-center text-caption text-text-3">{t('loading')}</div>
            : catalog.error ? <div className="flex flex-1 flex-col items-center justify-center text-caption text-text-3">
              {t('load_failed')}<Button variant="text" onClick={catalog.retry}>{t('retry')}</Button>
            </div>
              : !categories.length ? <div className="flex flex-1 items-center justify-center px-3 text-center text-caption text-text-3">{t('no_spaces')}</div>
                : <TreeNavigation aria-label={t('title')} className="scrollbar-os min-h-0 flex-1 px-2 pb-2 max-[768px]:rounded-md max-[768px]:border max-[768px]:border-border-base max-[768px]:p-2">
                  {categories.map(({ key, spaces }) => {
                    const collapsed = collapsedCategories.has(key);
                    return <section key={key} className="mb-2 last:mb-0">
                      <button type="button" aria-expanded={!collapsed} className="group/cat flex w-full select-none items-center gap-1 px-2 py-1 text-left"
                        onClick={() => setCollapsedCategories((previous) => {
                          const next = new Set(previous);
                          if (!next.delete(key)) next.add(key);
                          return next;
                        })}>
                        <span className="whitespace-nowrap text-caption font-medium text-text-3 group-hover/cat:text-text-2">{t(categoryLabels[key])}</span>
                        <Outlined.Down aria-hidden className={`size-3.5 text-text-3 transition-all duration-150 ${collapsed ? '-rotate-90 opacity-100' : 'opacity-0 group-hover/cat:opacity-100'}`} />
                      </button>
                      {!collapsed && <TreeNavigationList>{spaces.map((space) => {
                        const selected = selection?.spaceId === space.id;
                        const expanded = expandedSpaces.has(space.id);
                        const Icon = key === 'department' ? Outlined.City : Outlined.Notebook;
                        return <TreeNavigationNode key={space.id} name={space.name} icon={<Icon />}
                          marker={space.id === currentSpaceId ? <span className="text-text-3">{t('current_space_tag')}</span> : undefined}
                          current={selected && selection.folderId === null && 'location'}
                          onSelect={() => setSelection({ spaceId: space.id, folderId: null })}
                          disclosure={{ expanded, label: t(expanded ? 'collapse' : 'expand', { name: space.name }), onToggle: () => toggleSpace(space.id) }}>
                          {visitedSpaces.has(space.id) && <MoveFolderTree spaceId={space.id} services={services} selection={selection} onError={onError}
                            onSelect={(folder) => setSelection({ spaceId: space.id, folderId: folder.id, folderName: folder.name })} />}
                        </TreeNavigationNode>;
                      })}</TreeNavigationList>}
                    </section>;
                  })}
                </TreeNavigation>}
        </div>
        <DestinationContents services={services} selection={selection} onSelect={setSelection} onError={onError} />
      </div>
      <div className="flex shrink-0 flex-row justify-end gap-2">
        <Button color="default" variant="outlined" className="max-[768px]:flex-1" onClick={() => onOpenChange(false)}>{t('cancel')}</Button>
        <Button className="max-[768px]:flex-1" onClick={handleConfirm} disabled={!selection || catalog.loading || catalog.error}>{t('move_here')}</Button>
      </div>
    </Dialog.Content>
    </Dialog.Portal>
  );
}

/** One picker implementation for both SPAs, reset whenever its scope or open session changes. */
export function MoveToDialog(props: MoveToDialogProps) {
  return <Dialog.Root open={props.open} onOpenChange={props.onOpenChange}>
    {props.open && <MoveToContent key={`${serviceIdentity(props.services)}:${props.currentSpaceId}`} {...props} />}
  </Dialog.Root>;
}
