import { useLocalize } from '~/hooks';
import { isDemoDataEnabled } from '~/mock/demo/ids';
import { useMockProjects } from './projectsStore';

// Sample projects of the DEV demo data layer (Figma 13139:111454), listed after the
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

export interface SidebarProject {
  id: string;
  name: string;
  /** Titles of the conversations the sample data files under it — demo rows only. */
  demoChats: string[];
  /** Sample rows are read-only: no rename / delete. They still take moved conversations,
   *  so the 移入项目 menu has somewhere to put one before the user makes a project. */
  readonly: boolean;
}

/**
 * The 项目 folders the sidebar shows and the ⋯ menu offers as move targets, in one place
 * so the two never disagree. MOCK: own projects come from localStorage (projectsStore),
 * the rest are the DEV sample rows.
 */
export function useSidebarProjects(): SidebarProject[] {
  const localize = useLocalize();
  const ownProjects = useMockProjects();
  return [
    ...ownProjects.map((project) => ({
      id: project.id,
      name: project.name,
      demoChats: [],
      readonly: false,
    })),
    ...(isDemoDataEnabled()
      ? DEMO_PROJECTS.map((project) => ({
          id: project.id,
          name: localize(project.nameKey),
          demoChats: project.chatKeys.map((key) => localize(key)),
          readonly: true,
        }))
      : []),
  ];
}
