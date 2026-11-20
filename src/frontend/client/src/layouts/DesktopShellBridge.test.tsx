import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { QueryKeys } from "~/types/chat";
import { DesktopShellBridge } from "./DesktopShellBridge";
let mockEntries = [
  {
    id: "knowledge",
    path: "/knowledge",
    to: "/knowledge",
    label: "Knowledge",
    active: true,
    icon: null,
  },
];
jest.mock("~/hooks/useVersionManagementEnabled", () => ({
  usePersonalTokenEnabled: () => true,
}));
const mockReport = jest.fn();
let mockChannel: "desktop" | "web" = "desktop";
const mockBranding = {
  welcomeMessage: "Team workspace",
  assistantIcon: { enabled: true, image: "https://files.example/logo.svg" },
};
jest.mock("~/hooks/queries/data-provider", () => ({
  useGetBsConfig: () => ({ data: mockBranding }),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => () => "Default welcome" }));
jest.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: "/knowledge", search: "" }),
}));
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({
    channel: mockChannel,
    capabilities: { hasNativePresentation: mockChannel === "desktop" },
  }),
}));
jest.mock("~/hooks/useChatProjects", () => ({ useDesktopProjectRefresh: () => {} }));
jest.mock("~/hooks/useProjectMigration", () => ({ useProjectMigration: () => {} }));
jest.mock("~/components/Chat/useDesktopNavigation", () => ({
  useDesktopNavigation: () => {},
}));
jest.mock("~/components/Chat/useDesktopAppearance", () => ({
  useDesktopAppearance: () => {},
}));
jest.mock("./useDesktopLocale", () => ({ useDesktopLocale: () => {} }));
jest.mock("./useWorkbenchNavLinks", () => ({
  useWorkbenchNavLinks: () => ({
    links: [{ section: "home", label: "Welcome" }],
  }),
}));
jest.mock("./WorkbenchSidebar/useSidebarEntries", () => ({
  useSidebarEntries: () => mockEntries,
  splitSidebarEntries: (entries: unknown[]) => ({ shown: entries.slice(0, 3) }),
}));
afterEach(() => {
  delete window.dshChatPresentation;
  mockChannel = "desktop";
});

function renderBridge(children?: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const content = () => (
    <QueryClientProvider client={client}><DesktopShellBridge />{children}</QueryClientProvider>
  );
  return { ...render(content()), content, client };
}

it("publishes only available entries and replaces them after grants change", () => {
  window.dshChatPresentation = {
    reportLanding: jest.fn(),
    reportNavigation: mockReport,
  };
  const view = renderBridge();
  expect(mockReport).toHaveBeenLastCalledWith({
    settings: { aiAccess: true },
    branding: mockBranding,
    homeLabel: "Welcome",
    path: "/knowledge",
    entries: [
      {
        id: "knowledge",
        path: "/knowledge",
        label: "Knowledge",
        active: true,
        primary: true,
      },
    ],
  });
  mockEntries = [];
  view.rerender(view.content());
  expect(mockReport).toHaveBeenLastCalledWith({
    settings: { aiAccess: true },
    branding: mockBranding,
    homeLabel: "Welcome",
    path: "/knowledge",
    entries: [],
  });
});

it("refreshes the signed-in profile in place when the Desktop host reports a change", async () => {
  const listeners = new Set<() => void>();
  window.dshChatPresentation = {
    onProfileChanged(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
  const readProfile = jest.fn().mockResolvedValueOnce("Kinyoo").mockResolvedValueOnce("admin");
  function Profile() {
    const { data } = useQuery([QueryKeys.user], readProfile, { staleTime: Infinity });
    return <output>{data}</output>;
  }
  const view = renderBridge(<Profile />);
  expect(await screen.findByText("Kinyoo")).toBeInTheDocument();
  expect(listeners.size).toBe(1);

  act(() => { listeners.forEach(listener => listener()); });
  expect(await screen.findByText("admin")).toBeInTheDocument();
  expect(readProfile).toHaveBeenCalledTimes(2);

  view.unmount();
  expect(listeners.size).toBe(0);
});

it("does not subscribe to the host profile signal on ordinary Web pages", () => {
  mockChannel = "web";
  const subscribe = jest.fn();
  window.dshChatPresentation = { onProfileChanged: subscribe };
  renderBridge();
  expect(subscribe).not.toHaveBeenCalled();
});
