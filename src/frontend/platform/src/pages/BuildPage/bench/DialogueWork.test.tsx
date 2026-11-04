import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import DialogueWork from "./DialogueWork";
vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: {} }) }));
vi.mock("react-i18next", () => ({
    useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }),
}));
vi.mock("./index", () => ({ default: ({ scopeVersion = 0 }: { scopeVersion?: number }) => <div>Home {scopeVersion}</div> }));
vi.mock("./KnowledgeSpace", () => ({
    default: ({ scopeVersion = 0 }: { scopeVersion?: number }) => <div>Knowledge {scopeVersion}</div>,
}));
vi.mock("./Subscribe", () => ({
    default: ({ scopeVersion = 0 }: { scopeVersion?: number }) => <div>Subscribe {scopeVersion}</div>,
}));
vi.mock("./AppCenter", () => ({
    AppCenter: ({ scopeVersion = 0 }: { scopeVersion?: number }) => <div>Apps {scopeVersion}</div>,
}));
it("switches panels without a second page-specific tenant selector", async () => {
    const user = userEvent.setup();
    render(<DialogueWork />);
    expect(screen.getByText("Home 0")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.knowledgeSpace" }));
    expect(screen.getByText("Knowledge 0")).toBeInTheDocument();
    expect(screen.queryByText("Home 0")).toBeNull();
    expect(screen.queryByRole("button", { name: "Change scope" })).toBeNull();
    await user.click(screen.getByRole("tab", { name: "bench.subscribe" }));
    expect(screen.getByText("Subscribe 0")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.appCenter" }));
    expect(screen.getByText("Apps 0")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "bench.home" }));
    expect(screen.getByText("Home 0")).toBeInTheDocument();
});
