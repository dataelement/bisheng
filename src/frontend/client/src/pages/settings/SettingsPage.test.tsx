jest.mock('~/hooks/useVersionManagementEnabled', () => ({ usePersonalTokenEnabled: () => false }));
jest.mock('~/hooks/useDshDesktop', () => ({ useDshDesktop: () => ({ enabled: false }) }));
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import SettingsPage from "./SettingsPage";

const mockRefreshCount = jest.fn().mockResolvedValue(undefined);

jest.mock("recoil", () => ({
  ...jest.requireActual("recoil"),
  useSetRecoilState: () => jest.fn(),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => false,
}));

jest.mock("~/hooks/useNotificationCount", () => ({
  useNotificationCount: () => ({
    pendingApprovalCount: 0,
    refreshCount: mockRefreshCount,
    unreadCount: 0,
  }),
}));

jest.mock("~/components/approval/ApprovalPane", () => ({
  ApprovalPane: () => <div>approval-pane</div>,
}));

jest.mock("~/components/messageApproval/NotificationPane", () => ({
  NotificationPane: () => <div>notification-pane</div>,
}));

jest.mock("~/components/Settings/sections/GeneralSection", () => ({
  GeneralSection: () => <div>general-section</div>,
}));

jest.mock("./sections/AccountPane", () => ({
  AccountPane: () => <div>account-pane</div>,
}));
jest.mock("./sections/DesktopSettingsPane", () => ({
  DesktopSettingsPane: ({ section }: { section: string }) => <main data-testid="desktop-content">{section}</main>,
}));

afterEach(() => {
  delete window.dshChatPresentation;
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</div>;
}

describe("SettingsPage history", () => {
  it.each([false, true])('uses content-only settings only with the native bridge (native=%s)', native => {
    window.history.replaceState({}, '', '/workspace/settings/account?embed=dsh&dshSettings=1');
    if (native) window.dshChatPresentation = { reportLanding: jest.fn() };
    render(<MemoryRouter initialEntries={['/settings/account?embed=dsh&dshSettings=1']}>
      <Routes><Route path="settings/:section?" element={<SettingsPage />} /></Routes>
    </MemoryRouter>);
    if (native) {
      expect(screen.getByTestId('desktop-content').textContent).toBe('account');
      expect(screen.queryByRole('navigation')).toBeNull();
    } else {
      expect(screen.getByRole('navigation')).toBeTruthy();
      expect(screen.getByText('account-pane')).toBeTruthy();
      expect(screen.queryByTestId('desktop-content')).toBeNull();
    }
  });
  it("returns to the entry page after settings sidebar navigation", () => {
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/settings/account",
            state: {
              settingsOrigin: {
                historyIndex: null,
                path: "/knowledge/space/42?tab=files#recent",
              },
            },
          },
        ]}
      >
        <Routes>
          <Route path="settings/:section?" element={<SettingsPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "com_message_approval_notifications" }));
    expect(screen.getByText("notification-pane")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "com_ui_go_back" }));
    expect(screen.getByTestId("location").textContent).toContain(
      "/knowledge/space/42?tab=files#recent",
    );
  });
});
