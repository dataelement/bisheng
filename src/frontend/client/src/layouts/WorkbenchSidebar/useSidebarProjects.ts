import { useLocalize } from '~/hooks';
import { isDemoDataEnabled } from '~/mock/demo/ids';
import { useChatProjects } from '~/hooks/useChatProjects';

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
  /** Demo rows are read-only and are never uploaded or offered as move targets. */
  readonly: boolean;
}

/**
 * Both project navigation and move menus consume the same authenticated cache.
 * DEV-only samples remain visibly read-only.
 */
export function useSidebarProjects(): SidebarProject[] {
  const localize = useLocalize();
  const { data } = useChatProjects();
  const ownProjects = [...(data?.projects ?? [])].sort((a, b) => (Date.parse(b.created_at ?? '') || 0) - (Date.parse(a.created_at ?? '') || 0));
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
