import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AccountPane } from "./AccountPane";

const mockLogout = jest.fn();

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({ user: { username: "Alice" }, logout: mockLogout }),
}));
jest.mock("~/components/Settings/sections/AccountSection", () => ({
  AccountSection: () => <div>account-info</div>,
}));
jest.mock("~/components/ui/Button", () => ({
  Button: ({ children, onClick }: { children: React.ReactNode; onClick: () => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
}));
jest.mock("bisheng-icons", () => ({ Outlined: { LogOut: () => null } }));

it("shows account information and sign-out without a client shortcut", () => {
  render(<MemoryRouter><AccountPane /></MemoryRouter>);
  expect(screen.getByText("account-info")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "dsh_title" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "com_nav_log_out" }));
  expect(mockLogout).toHaveBeenCalledTimes(1);
});
