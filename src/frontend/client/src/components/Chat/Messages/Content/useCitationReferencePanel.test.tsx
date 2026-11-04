import { fireEvent, render, screen } from "@testing-library/react";
import { useCitationReferencePanel } from "./useCitationReferencePanel";

const mockViewportWidth = 1200;
jest.mock("~/hooks/useMediaQuery", () => ({
  __esModule: true,
  default: (query: string) => {
    const width = Number(query.match(/\d+/)?.[0]);
    return query.includes("min-width")
      ? mockViewportWidth >= width
      : mockViewportWidth <= width;
  },
}));
jest.mock("~/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
}));
jest.mock("./CitationReferencesDrawer", () => ({
  __esModule: true,
  default: ({
    open,
    onOpenChange,
  }: {
    open: boolean;
    onOpenChange: (value: boolean) => void;
  }) =>
    open ? (
      <section aria-label="References">
        <button onClick={() => onOpenChange(false)}>Close references</button>
      </section>
    ) : null,
}));
jest.mock("./CitationDocumentPreviewDrawer", () => ({
  __esModule: true,
  default: () => null,
}));
function Probe({ width }: { width: number }) {
  const panel = useCitationReferencePanel({
    hasMessages: true,
    contentWidth: width,
  });
  return (
    <>
      <button
        onClick={() =>
          panel.onOpenCitationPanel({
            messageId: "1",
            content: "Reference",
            referenceItems: [],
          } as never)
        }
      >
        Open references
      </button>
      {panel.citationPanelElement}
    </>
  );
}
it("undocks for narrow content inside a wide viewport and retains close controls", () => {
  const view = render(<Probe width={1200} />);
  fireEvent.click(screen.getByText("Open references"));
  const initial = screen.getByRole("region", { name: "References" });
  expect(view.container.contains(initial)).toBe(true);
  view.rerender(<Probe width={700} />);
  expect(
    view.container.contains(screen.getByRole("region", { name: "References" })),
  ).toBe(false);
  fireEvent.click(screen.getByText("Close references"));
  expect(screen.queryByRole("region")).toBeNull();
  view.unmount();
  expect(document.querySelector("[data-citation-popover-surface]")).toBeNull();
});
