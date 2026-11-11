import { Dropdown, DropdownItem } from "@bisheng/ui";
import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { ProjectNameDialog } from './ProjectNameDialog';
import { SIDEBAR_ICON_BUTTON_CLASS_NAME as ICON_BUTTON } from './sidebarIconButton';
import { useChatProjectActions, useProjectIdentity } from '~/hooks/useChatProjects';
import { ProjectConversations } from './ProjectConversations';
import { ProjectSyncStatus } from './ProjectSyncStatus';
import { useSidebarProjects } from './useSidebarProjects';

const ROW = 'flex w-full items-center rounded-lg py-[5px] pr-2 text-left text-body text-text-1 transition-colors coarse-pointer:min-h-11 coarse-pointer:py-0';
const PROJECT_ACTION_BUTTON = cn(
  ICON_BUTTON,
  'opacity-0 focus-visible:opacity-100 group-hover/project:opacity-100 group-has-[[data-menu-open]]/project:opacity-100 data-[state=open]:opacity-100 coarse-pointer:opacity-100',
);

type NameDialogTarget = { mode: 'create' } | { mode: 'rename'; id: string; name: string };

interface SidebarProjectsProps {
  openIds: string[];
  onOpenIdsChange: Dispatch<SetStateAction<string[]>>;
  onNavigate: () => void;
  onStartChat: (projectId: string) => void;
}

/** Projects and their paged conversations come from the authenticated server. */
export function SidebarProjects({ openIds, onOpenIdsChange, onNavigate, onStartChat }: SidebarProjectsProps) {
  const localize = useLocalize();
  const projects = useSidebarProjects();
  const actions = useChatProjectActions();
  const identity = useProjectIdentity();
  const [dialogIdentity, setDialogIdentity] = useState(identity);
  const [actionFailed, setActionFailed] = useState(false);
  // The target outlives `open` so the dialog keeps its title while it animates out.
  const [nameDialog, setNameDialog] = useState<NameDialogTarget>({ mode: 'create' });
  const [nameDialogOpen, setNameDialogOpen] = useState(false);
  const openNameDialog = (target: NameDialogTarget) => {
    setDialogIdentity(identity);
    setNameDialog(target);
    setNameDialogOpen(true);
  };

  const handleToggle = (id: string) => {
    onOpenIdsChange((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handleNameSubmit = async (name: string, draftProjectId: string) => {
    if (nameDialog.mode === 'rename') {
      await actions.mutateAsync({ operation: { operation: 'rename', project_id: nameDialog.id, name } });
      return;
    }
    // A new project opens at once, so the user sees where its conversations will go.
    const result = await actions.mutateAsync({ operation: { operation: 'create', project_id: draftProjectId, name } });
    const id = result.outcome.project_id;
    if (id) onOpenIdsChange((prev) => [...prev, id]);
  };

  return (
    <section className="flex w-full shrink-0 flex-col gap-1 pb-4">
      <ProjectSyncStatus />
      {actionFailed && <p role="alert" className="px-2 text-caption text-danger">{localize('project_sync.save_failed')}</p>}
      <div className="flex w-full shrink-0 items-center justify-between px-2 py-[5px]">
        <span className="truncate text-caption text-text-3">{localize('com_workbench_sidebar.projects')}</span>
        <Tooltip content={localize('com_workbench_sidebar.project_new')}>
          <button
            type="button"
            aria-label={localize('com_workbench_sidebar.project_new')}
            onClick={() => openNameDialog({ mode: 'create' })}
            className={ICON_BUTTON}
          >
            <Outlined.Plus className="size-4" />
          </button>
        </Tooltip>
      </div>

      {projects.length === 0 && (
        <button
          type="button"
          onClick={() => openNameDialog({ mode: 'create' })}
          className={cn(ROW, 'gap-2 pl-2 text-text-3 hover:bg-fill-1')}
        >
          <Outlined.Plus className="size-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate">{localize('com_workbench_sidebar.project_new')}</span>
        </button>
      )}

      {projects.map((project) => {
        const open = openIds.includes(project.id);
        return (
          <div key={project.id} className="flex w-full flex-col">
            <div className={cn(ROW, 'group/project relative pl-2 hover:bg-fill-1 has-[[data-state=open]]:bg-fill-1', open && 'mb-1')}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => handleToggle(project.id)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left coarse-pointer:min-h-11"
              >
                {open ? (
                  <Outlined.FolderOpen className="size-4 shrink-0" />
                ) : (
                  <Outlined.FolderClose className="size-4 shrink-0" />
                )}
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
              </button>
              {!project.readonly && (
                <div className="flex shrink-0 items-center gap-1">
                  <Tooltip content={localize('com_workbench_sidebar.more')}>
                    <span className="inline-flex shrink-0">
                      <Dropdown align="end" menu={<>
                        <DropdownItem
                          icon={<Outlined.Edit />}
                          onSelect={() => openNameDialog({ mode: 'rename', id: project.id, name: project.name })}
                        >{localize('com_ui_rename')}</DropdownItem>
                        <DropdownItem
                          danger
                          icon={<Outlined.Delete />}
                          onSelect={() => {
                            setActionFailed(false);
                            void actions.mutateAsync({ operation: { operation: 'delete', project_id: project.id } }).catch(() => setActionFailed(true));
                          }}
                        >{localize('com_ui_delete')}</DropdownItem>
                      </>}>
                        <button
                          type="button"
                          aria-label={localize('com_workbench_sidebar.more')}
                          className={PROJECT_ACTION_BUTTON}
                        >
                          <Outlined.More className="size-4" />
                        </button>
                      </Dropdown>
                    </span>
                  </Tooltip>
                  <Tooltip content={localize('com_nav_start_new_chat')}>
                    <span className="inline-flex shrink-0">
                      <button
                        type="button"
                        aria-label={`${localize('com_nav_start_new_chat')} · ${project.name}`}
                        className={PROJECT_ACTION_BUTTON}
                        onClick={() => {
                          onOpenIdsChange((prev) => prev.includes(project.id) ? prev : [...prev, project.id]);
                          onStartChat(project.id);
                          onNavigate();
                        }}
                      >
                        <Outlined.MessagePlus className="size-4" />
                      </button>
                    </span>
                  </Tooltip>
                </div>
              )}
            </div>
            {open && (
              <>
                {!project.readonly && <ProjectConversations projectId={project.id} onNavigate={onNavigate} />}
                {project.demoChats.map((chat) => (
                  <div key={chat} className={cn(ROW, 'cursor-default pl-8 hover:bg-fill-1')}>
                    <span className="min-w-0 flex-1 truncate">{chat}</span>
                  </div>
                ))}
                {project.readonly && project.demoChats.length === 0 && (
                  <div className="w-full truncate py-[5px] pl-8 pr-2 text-caption text-text-3">
                    {localize('com_workbench_sidebar.project_empty')}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}

      <ProjectNameDialog
        open={nameDialogOpen && dialogIdentity === identity}
        onOpenChange={setNameDialogOpen}
        initialName={nameDialog.mode === 'rename' ? nameDialog.name : undefined}
        onSubmit={handleNameSubmit}
      />
    </section>
  );
}
