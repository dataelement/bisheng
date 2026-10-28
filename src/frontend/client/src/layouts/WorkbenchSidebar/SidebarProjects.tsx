import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useMemo, useState } from 'react';
import { ActionMenuContent, ActionMenuItem } from '~/components/ActionMenu';
import Convo from '~/components/Conversations/Convo';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { useAuthContext, useLocalize } from '~/hooks';
import { useConversationsInfiniteQuery } from '~/hooks/queries/data-provider';
import type { TConversation } from '~/types/chat';
import { cn } from '~/utils';
import { ProjectNameDialog } from './ProjectNameDialog';
import { createMockProject, deleteMockProject, renameMockProject, useMockProjectChats } from './projectsStore';
import { useSidebarProjects } from './useSidebarProjects';

const noop = () => undefined;

const ROW = 'flex w-full items-center rounded-lg py-[5px] pr-2 text-left text-body text-text-1 transition-colors';
const ICON_BUTTON = 'flex size-5 shrink-0 items-center justify-center rounded text-text-2 transition-colors hover:bg-fill-3';

type NameDialogTarget = { mode: 'create' } | { mode: 'rename'; id: string; name: string };

/**
 * 项目 section of the workbench sidebar. MOCK: the backend has no project model yet, so
 * projects — and which conversations were moved into them — live in localStorage
 * (see projectsStore); a conversation filed here leaves the flat 对话 list below.
 */
export function SidebarProjects() {
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
            <div className={cn(ROW, 'group/project relative pl-2 hover:bg-fill-1 has-[[data-state=open]]:bg-fill-1')}>
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
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      aria-label={localize('com_workbench_sidebar.more')}
                      className={cn(
                        ICON_BUTTON,
                        'opacity-0 focus-visible:opacity-100 group-hover/project:opacity-100 data-[state=open]:opacity-100',
                      )}
                    >
                      <Outlined.More className="size-4" />
                    </button>
                  </DropdownMenuTrigger>
                  <ActionMenuContent>
                    <ActionMenuItem
                      icon={<Outlined.Edit />}
                      label={localize('com_ui_rename')}
                      onSelect={() => openNameDialog({ mode: 'rename', id: project.id, name: project.name })}
                    />
                    <ActionMenuItem
                      danger
                      icon={<Outlined.Delete />}
                      label={localize('com_ui_delete')}
                      onSelect={() => deleteMockProject(project.id)}
                    />
                  </ActionMenuContent>
                </DropdownMenu>
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
