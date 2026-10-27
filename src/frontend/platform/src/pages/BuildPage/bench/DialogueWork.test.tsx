import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import DialogueWork from "./DialogueWork";
vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("react-i18next", () => ({
    useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }),
}));
vi.mock("@/pages/ModelPage/manage/ScopeBar", () => ({
    ScopeBar: ({ onScopeChange }: { onScopeChange: () => void }) => (
        <button onClick={onScopeChange}>Change scope</button>
    ),
}));
vi.mock("./index", () => ({ default: ({ scopeVersion }: { scopeVersion: number }) => <div>Home {scopeVersion}</div> }));
vi.mock("./KnowledgeSpace", () => ({
    default: ({ scopeVersion }: { scopeVersion: number }) => <div>Knowledge {scopeVersion}</div>,
}));
vi.mock("./Subscribe", () => ({
    default: ({ scopeVersion }: { scopeVersion: number }) => <div>Subscribe {scopeVersion}</div>,
}));
vi.mock("./AppCenter", () => ({
    AppCenter: ({ scopeVersion }: { scopeVersion: number }) => <div>Apps {scopeVersion}</div>,
}));
it("switches all four workbench panels and refreshes the current scope without mounting inactive panels", async () => {
    const user = userEvent.setup();
    render(<DialogueWork />);
    expect(screen.getByText("Home 0")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.knowledgeSpace" }));
    expect(screen.getByText("Knowledge 0")).toBeInTheDocument();
    expect(screen.queryByText("Home 0")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Change scope" }));
    expect(screen.getByText("Knowledge 1")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.subscribe" }));
    expect(screen.getByText("Subscribe 1")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.appCenter" }));
    expect(screen.getByText("Apps 1")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.home" }));
    expect(screen.getByText("Home 1")).toBeInTheDocument();
});
