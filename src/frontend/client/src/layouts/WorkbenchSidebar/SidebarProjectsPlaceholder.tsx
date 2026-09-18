import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize } from '~/hooks';
import { SidebarSectionLabel } from './SidebarSectionLabel';

type DemoProject = {
  id: string;
  nameKey: string;
  chatKeys: string[];
};

// PLACEHOLDER: 项目 has no backend or data model yet. This renders the layout from
// Figma 13139:111454 with demo copy so the sidebar can be reviewed as a whole; rows
// only expand/collapse. Replace with real data once the feature exists.
const DEMO_PROJECTS: DemoProject[] = [
  {
    id: 'travel',
    nameKey: 'com_workbench_sidebar.demo.project_travel',
    chatKeys: [
      'com_workbench_sidebar.demo.chat_food',
      'com_workbench_sidebar.demo.chat_heritage',
      'com_workbench_sidebar.demo.chat_season',
      'com_workbench_sidebar.demo.chat_spots',
    ],
  },
  { id: 'files', nameKey: 'com_workbench_sidebar.demo.project_files', chatKeys: [] },
];

const ROW = 'flex w-full items-center rounded-lg py-[5px] pr-2 text-left text-body text-text-1 transition-colors hover:bg-fill-1';

export function SidebarProjectsPlaceholder() {
  const localize = useLocalize();
  const [openIds, setOpenIds] = useState<string[]>([DEMO_PROJECTS[0].id]);

  const handleToggle = (id: string) => {
    setOpenIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  return (
    <section className="flex w-full shrink-0 flex-col gap-1 pb-4">
      <SidebarSectionLabel>{localize('com_workbench_sidebar.projects')}</SidebarSectionLabel>
      {DEMO_PROJECTS.map((project) => {
        const open = openIds.includes(project.id);
        return (
          <div key={project.id} className="flex w-full flex-col">
            <button
              type="button"
              aria-expanded={open}
              onClick={() => handleToggle(project.id)}
              className={`${ROW} gap-2 pl-2`}
            >
              {open ? (
                <Outlined.FolderOpen className="size-4 shrink-0" />
              ) : (
                <Outlined.FolderClose className="size-4 shrink-0" />
              )}
              <span className="min-w-0 flex-1 truncate">{localize(project.nameKey)}</span>
            </button>
            {open &&
              project.chatKeys.map((chatKey) => (
                <div key={chatKey} className={`${ROW} cursor-default pl-8`}>
                  <span className="min-w-0 flex-1 truncate">{localize(chatKey)}</span>
                </div>
              ))}
          </div>
        );
      })}
    </section>
  );
}
