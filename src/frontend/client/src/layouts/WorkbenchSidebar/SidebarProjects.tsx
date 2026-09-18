import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { ActionMenuContent, ActionMenuItem } from '~/components/ActionMenu';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { useLocalize } from '~/hooks';
import { isDemoDataEnabled } from '~/mock/demo/ids';
import { cn } from '~/utils';
import { ProjectNameDialog } from './ProjectNameDialog';
import { createMockProject, deleteMockProject, renameMockProject, useMockProjects } from './projectsStore';

type SidebarProject = {
  id: string;
  name: string;
  /** Titles of the conversations filed under it — sample projects only, for now. */
  chats: string[];
  /** Sample rows are read-only: no rename / delete. */
  readonly: boolean;
};

// Sample projects of the DEV demo data layer (Figma 13139:111454), shown after the
// user's own so the section can be reviewed with content in it.
const DEMO_PROJECTS = [
  {
    id: 'demo-travel',
    nameKey: 'com_workbench_sidebar.demo.project_travel',
    chatKeys: [
      'com_workbench_sidebar.demo.chat_food',
      'com_workbench_sidebar.demo.chat_heritage',
      'com_workbench_sidebar.demo.chat_season',
      'com_workbench_sidebar.demo.chat_spots',
    ],
  },
  { id: 'demo-files', nameKey: 'com_workbench_sidebar.demo.project_files', chatKeys: [] },
];

const ROW = 'flex w-full items-center rounded-lg py-[5px] pr-2 text-left text-body text-text-1 transition-colors';
const ICON_BUTTON = 'flex size-5 shrink-0 items-center justify-center rounded text-text-2 transition-colors hover:bg-fill-3';

type NameDialogTarget = { mode: 'create' } | { mode: 'rename'; id: string; name: string };

/**
 * 项目 section of the workbench sidebar. MOCK: the backend has no project model yet, so
 * projects are created / renamed / deleted in localStorage (see projectsStore) and cannot
 * hold conversations yet — an open project shows the empty hint.
 */
export function SidebarProjects() {
  const localize = useLocalize();
  const ownProjects = useMockProjects();
  const [openIds, setOpenIds] = useState<string[]>([]);
  // The target outlives `open` so the dialog keeps its title while it animates out.
  const [nameDialog, setNameDialog] = useState<NameDialogTarget>({ mode: 'create' });
  const [nameDialogOpen, setNameDialogOpen] = useState(false);
  const openNameDialog = (target: NameDialogTarget) => {
    setNameDialog(target);
    setNameDialogOpen(true);
  };

  const projects: SidebarProject[] = [
    ...ownProjects.map((project) => ({ id: project.id, name: project.name, chats: [], readonly: false })),
    ...(isDemoDataEnabled()
      ? DEMO_PROJECTS.map((project) => ({
          id: project.id,
          name: localize(project.nameKey),
          chats: project.chatKeys.map((key) => localize(key)),
          readonly: true,
        }))
      : []),
  ];

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
            {open &&
              (project.chats.length > 0 ? (
                project.chats.map((chat) => (
                  <div key={chat} className={cn(ROW, 'cursor-default pl-8 hover:bg-fill-1')}>
                    <span className="min-w-0 flex-1 truncate">{chat}</span>
                  </div>
                ))
              ) : (
                <div className="w-full truncate py-[5px] pl-8 pr-2 text-caption text-text-3">
                  {localize('com_workbench_sidebar.project_empty')}
                </div>
              ))}
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
