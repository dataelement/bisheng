import { useContext, useState, type ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import MenuPermissionPlaceholder from "./MenuPermissionPlaceholder";
import { userContext } from "@/contexts/userContext";
import { applyMenuAccessApi } from "@/controllers/API/approval";
import { FormInput } from "./BuildPage/bench/FormInput";

vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("@/controllers/API/approval", () => ({ applyMenuAccessApi: vi.fn() }));
vi.mock("@/controllers/request", async (importOriginal) => ({ ...await importOriginal<typeof import('@/controllers/request')>() }));
vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({ useToast: () => ({ toast: vi.fn() }) }))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
});
interface FixtureProps {
    children: ReactNode;
    approval?: boolean;
}
function Fixture({ children, approval = true }: FixtureProps) {
    const user = useContext(userContext);
    return (
        <MemoryRouter initialEntries={["/menu-pending?menu=build"]}>
            <userContext.Provider value={{ ...user, user: { menu_approval_mode_admin: approval } }}>
                {children}
            </userContext.Provider>
        </MemoryRouter>
    );
}
beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(applyMenuAccessApi).mockResolvedValue({});
});
it("keeps approval disabled for a non-approval role", () => {
    render(
        <Fixture approval={false}>
            <MenuPermissionPlaceholder />
        </Fixture>,
        { wrapper: undefined },
    );
    expect(screen.queryByRole("button")).toBeNull();
});
it("trims the request reason, submits once and prevents a second application", async () => {
    const user = userEvent.setup();
    render(
        <Fixture>
            <MenuPermissionPlaceholder />
        </Fixture>,
        { wrapper: undefined },
    );
    await user.click(screen.getByRole("button", { name: "approvalPage.menuApply" }));
    await user.type(screen.getByRole("textbox"), "  Please enable this menu  ");
    await user.click(screen.getByRole("button", { name: "approvalPage.save" }));
    await waitFor(() =>
        expect(applyMenuAccessApi).toHaveBeenCalledWith({
            menu_key: "build",
            menu_name: "menu.skills",
            reason: "Please enable this menu",
        }),
    );
    expect(screen.getByRole("button", { name: "approvalPage.menuApplied" })).toBeDisabled();
});
it("clears an unsaved reason when the request dialog is cancelled", async () => {
    const user = userEvent.setup();
    render(
        <Fixture>
            <MenuPermissionPlaceholder />
        </Fixture>,
        { wrapper: undefined },
    );
    await user.click(screen.getByRole("button", { name: "approvalPage.menuApply" }));
    await user.type(screen.getByRole("textbox"), "Draft");
    await user.click(screen.getByRole("button", { name: "approvalPage.cancel" }));
    await user.click(screen.getByRole("button", { name: "approvalPage.menuApply" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(applyMenuAccessApi).not.toHaveBeenCalled();
});
it("shows a soft limit while keeping the accessible form label", async () => {
    function Field() { const [value,setValue]=useState(''); return <FormInput label="Field" value={value} error="" maxLength={5} onChange={setValue} />; }
    render(<Field />);
    const field = screen.getByRole('textbox', {name:'Field'});
    expect(field).not.toHaveAttribute('maxlength');
    await userEvent.type(field,'abcdef');
    expect(field).toHaveValue('abcdef');
    expect(field).toHaveAttribute('aria-invalid','true');
});
