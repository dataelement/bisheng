import { Dropdown, DropdownItem } from "@bisheng/ui";
import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useMemo, useState } from 'react';
import Convo from '~/components/Conversations/Convo';
import { useAuthContext, useLocalize } from '~/hooks';
import { useConversationsInfiniteQuery } from '~/hooks/queries/data-provider';
import type { TConversation } from '~/types/chat';
import { cn } from '~/utils';
import { ProjectNameDialog } from './ProjectNameDialog';
import { SIDEBAR_ICON_BUTTON_CLASS_NAME as ICON_BUTTON } from './sidebarIconButton';
import { createMockProject, deleteMockProject, renameMockProject, useMockProjectChats } from './projectsStore';
import { useSidebarProjects } from './useSidebarProjects';

const noop = () => undefined;

const ROW = 'flex w-full items-center rounded-lg py-[5px] pr-2 text-left text-body text-text-1 transition-colors';
const PROJECT_ACTION_BUTTON = cn(
  ICON_BUTTON,
  'opacity-0 focus-visible:opacity-100 group-hover/project:opacity-100 data-[state=open]:opacity-100 coarse-pointer:opacity-100',
);

type NameDialogTarget = { mode: 'create' } | { mode: 'rename'; id: string; name: string };

interface SidebarProjectsProps {
  /** Opens a blank draft whose first conversation is filed into this project. */
  onStartChat: (projectId: string) => void;
}

/**
 * 项目 section of the workbench sidebar. MOCK: the backend has no project model yet, so
 * projects — and which conversations were moved into them — live in localStorage
 * (see projectsStore); a conversation filed here leaves the flat 对话 list below.
 */
export function SidebarProjects({ onStartChat }: SidebarProjectsProps) {
  const localize = useLocalize();
  const { isAuthenticated } = useAuthContext();
  const projects = useSidebarProjects();
  const projectChats = useMockProjectChats();

  // Same query (and cache entry) as the 对话 list below: this only reads the pages it
  // already loaded, so a moved conversation renders from the data that is in hand.
  const { data } = useConversationsInfiniteQuery(
    { pageNumber: '1', isArchived: false },
    { enabled: isAuthenticated },
  );
  const conversationsByProject = useMemo(() => {
    const grouped = new Map<string, TConversation[]>();
    for (const convo of data?.pages.flatMap((page) => page.conversations) ?? []) {
      const projectId = convo == null ? undefined : projectChats[convo.conversationId ?? ''];
      if (projectId == null || convo == null) continue;
      const list = grouped.get(projectId);
      if (list) list.push(convo);
      else grouped.set(projectId, [convo]);
    }
    return grouped;
  }, [data, projectChats]);
  const [openIds, setOpenIds] = useState<string[]>([]);
  // The target outlives `open` so the dialog keeps its title while it animates out.
  const [nameDialog, setNameDialog] = useState<NameDialogTarget>({ mode: 'create' });
  const [nameDialogOpen, setNameDialogOpen] = useState(false);
  const openNameDialog = (target: NameDialogTarget) => {
    setNameDialog(target);
    setNameDialogOpen(true);
  };

  const handleToggle = (id: string) => {
    setOpenIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handleNameSubmit = (name: string) => {
    if (nameDialog.mode === 'rename') {
      renameMockProject(nameDialog.id, name);
      return;
    }
    // A new project opens at once, so the user sees where its conversations will go.
    const project = createMockProject(name);
    setOpenIds((prev) => [...prev, project.id]);
  };

  return (
    <section className="flex w-full shrink-0 flex-col gap-1 pb-4">
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
        const conversations = conversationsByProject.get(project.id) ?? [];
        return (
          <div key={project.id} className="flex w-full flex-col">
            <div className={cn(ROW, 'group/project relative pl-2 hover:bg-fill-1 has-[[data-state=open]]:bg-fill-1', open && 'mb-1')}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => handleToggle(project.id)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
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
                          onSelect={() => deleteMockProject(project.id)}
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
                          setOpenIds((prev) => (prev.includes(project.id) ? prev : [...prev, project.id]));
                          onStartChat(project.id);
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
                {/* Real rows retain conversation navigation, rename, and menu actions. */}
                {conversations.map((convo) => (
                  <div key={convo.conversationId}>
                    <Convo
                      compact
                      className="pl-8"
                      isLatestConvo={false}
                      conversation={convo}
                      retainView={noop}
                      toggleNav={noop}
                    />
                  </div>
                ))}
                {project.demoChats.map((chat) => (
                  <div key={chat} className={cn(ROW, 'cursor-default pl-8 hover:bg-fill-1')}>
                    <span className="min-w-0 flex-1 truncate">{chat}</span>
                  </div>
                ))}
                {conversations.length === 0 && project.demoChats.length === 0 && (
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
        open={nameDialogOpen}
        onOpenChange={setNameDialogOpen}
        initialName={nameDialog.mode === 'rename' ? nameDialog.name : undefined}
        onSubmit={handleNameSubmit}
      />
    </section>
  );
}
