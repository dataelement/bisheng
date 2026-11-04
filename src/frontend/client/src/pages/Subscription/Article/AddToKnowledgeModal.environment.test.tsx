import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AddToKnowledgeModal } from "./AddToKnowledgeModal";

let mockWidth = 390;
const mockToast = jest.fn();
const mockLocalize = (key: string) => key;
const mockSpaces = jest.fn(async () => [
  { id: "space", name: "Available space" },
]);
jest.mock("~/hooks", () => ({
  useLocalize: () => mockLocalize,
  useScrollRevealRef: () => () => {},
}));
jest.mock("~/hooks/useMediaQuery", () => ({
  __esModule: true,
  default: () => mockWidth < 576,
}));
jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: mockToast }),
}));
jest.mock("~/api/knowledge", () => ({
  getManagedSpacesApi: () => mockSpaces(),
  getMineSpacesApi: () => mockSpaces(),
  getSpaceChildrenApi: async () => [],
  FileType: { FOLDER: "folder" },
}));
jest.mock("~/components/illustrations", () => ({
  EmptyStateIllustration: () => null,
}));
jest.mock("~/components/icons/channels", () => ({
  ChannelNotebookOneIcon: () => null,
}));
jest.mock("@bisheng/ui", () => ({
  SearchInput: (props: { clearLabel?: string }) => {
    const native = { ...props };
    delete native.clearLabel;
    return <input {...native} aria-label="Search spaces" />;
  },
}));
jest.mock("~/components/ui/Button", () => ({
  Button: (props: {
    children: ReactNode;
    loading?: boolean;
    color?: string;
    size?: string;
    variant?: string;
  }) => {
    const native = { ...props };
    delete native.loading;
    delete native.color;
    delete native.size;
    delete native.variant;
    return <button {...native}>{props.children}</button>;
  },
}));

it.each(["article", "channel_sync"] as const)(
  "uses the same phone tier for the %s shell and body, and restores scroll on close",
  async (mode) => {
    mockWidth = 575;
    const changed = jest.fn();
    const view = render(
      <AddToKnowledgeModal
        open
        onOpenChange={changed}
        mode={mode}
        dataSourceApi={mockSpaces}
      />,
    );
    await screen.findByText("Available space");
    const dialog = screen.getByRole("dialog");
    expect(dialog.style.width).toBe("100vw");
    expect(dialog.querySelector(".min-h-0.flex-1")).not.toBeNull();
    expect(document.body).toHaveAttribute("data-scroll-locked");
    mockWidth = 576;
    view.rerender(
      <AddToKnowledgeModal
        open
        onOpenChange={changed}
        mode={mode}
        dataSourceApi={mockSpaces}
      />,
    );
    expect(screen.getByRole("dialog").style.width).toBe("");
    expect(screen.getByRole("dialog").className).toContain("max-w-[92vw]");
    fireEvent.click(screen.getByRole("button", { name: "com_ui_close" }));
    expect(changed).toHaveBeenCalledWith(false);
    view.rerender(
      <AddToKnowledgeModal
        open={false}
        onOpenChange={changed}
        mode={mode}
        dataSourceApi={mockSpaces}
      />,
    );
    await waitFor(() =>
      expect(document.body).not.toHaveAttribute("data-scroll-locked"),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  },
);
