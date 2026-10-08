import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AccountPane } from "./AccountPane";

let mockEnabled = true;

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({ user: { username: "Alice" }, logout: jest.fn() }),
}));
jest.mock("~/hooks/useDshDesktop", () => ({
  useDshDesktop: () => {
    const [open, setOpen] = jest.requireActual("react").useState(false);
    return { enabled: mockEnabled, open: open && mockEnabled, setOpen,
      downloadUrl: null, launchUrl: "dsh://open" };
  },
}));
jest.mock("~/components/Settings/sections/AccountSection", () => ({
  AccountSection: () => <div>account-info</div>,
}));
jest.mock("~/components/dsh/DshDesktopDialog", () => ({
  DshDesktopDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <div role="dialog"><button onClick={() => onOpenChange(false)}>close-client</button></div>
  ),
}));
jest.mock("~/components/ui/Button", () => ({
  Button: ({ children, onClick }: { children: React.ReactNode; onClick: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));
jest.mock("bisheng-icons", () => ({ Outlined: { LogOut: () => null } }));

it("opens and closes the client dialog from account information", () => {
  mockEnabled = true;
  render(<MemoryRouter><AccountPane /></MemoryRouter>);
  expect(screen.getByText("account-info")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "dsh_title" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "close-client" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("hides the client entry when enterprise access is disabled", () => {
  mockEnabled = false;
  render(<MemoryRouter><AccountPane /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "dsh_title" })).toBeNull();
  expect(screen.getByRole("button", { name: "com_nav_log_out" })).toBeInTheDocument();
});
