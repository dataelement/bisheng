import { StrictMode } from "react";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import WebLinkImportDialog from "@/pages/KnowledgePage/components/WebLinkImportDialog";
const mocks = vi.hoisted(() => ({ import: vi.fn(), confirm: vi.fn() }));
vi.mock("@/controllers/API", () => ({ importKnowledgeWebLinkApi: mocks.import }));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: mocks.confirm }));
const change = vi.fn(),
  imported = vi.fn();
function mount() {
  const view = (scopeKey: string, parentId: number) => (
    <WebLinkImportDialog
      knowledgeId="7"
      parentId={parentId}
      scopeKey={scopeKey}
      open
      onOpenChange={change}
      onImported={imported}
    />
  );
  const result = render(view("scope-a", 9));
  return { ...result, move: () => result.rerender(view("scope-b", 10)) };
}
function submit() {
  fireEvent.change(screen.getByLabelText("webLinkUrl"), {
    target: { value: "https://example.com/page" },
  });
  fireEvent.change(screen.getByLabelText("webLinkTitle"), { target: { value: "Report" } });
  fireEvent.click(screen.getByRole("button", { name: "import" }));
}
beforeEach(() => {
  vi.resetAllMocks();
  change.mockClear();
  imported.mockClear();
  mocks.import.mockResolvedValue({ id: 81, status: 5 });
});
afterEach(cleanup);
it("imports into the actual folder and refreshes only after fulfillment", async () => {
  mount();
  submit();
  await waitFor(() => expect(imported).toHaveBeenCalledOnce());
  expect(mocks.import).toHaveBeenCalledWith(
    "7",
    { url: "https://example.com/page", title: "Report.html", parent_id: 9 },
    expect.any(AbortSignal),
  );
  expect(change).toHaveBeenCalledWith(false);
});
it("aborts an old opening and cannot close or refresh a new folder with its late response", async () => {
  let resolve!: (value: { id: number }) => void;
  mocks.import.mockReturnValue(
    new Promise((yes) => {
      resolve = yes;
    }),
  );
  const view = mount();
  submit();
  await waitFor(() => expect(mocks.import).toHaveBeenCalledOnce());
  const signal = mocks.import.mock.calls[0][2] as AbortSignal;
  view.move();
  expect(signal.aborted).toBe(true);
  await act(async () => resolve({ id: 81 }));
  expect(imported).not.toHaveBeenCalled();
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByLabelText("webLinkUrl")).toHaveValue("");
});
it("keeps overwrite failure open and retires its confirmation when the scope changes", async () => {
  mocks.import
    .mockRejectedValueOnce({ status_code: 18023 })
    .mockRejectedValueOnce({ status_code: 10999 });
  const view = mount();
  submit();
  await waitFor(() => expect(mocks.confirm).toHaveBeenCalledOnce());
  const confirmation = mocks.confirm.mock.calls[0][0] as {
    onOk: (close: () => void) => Promise<void>;
    signal: AbortSignal;
  };
  const close = vi.fn();
  await act(async () => confirmation.onOk(close));
  expect(close).not.toHaveBeenCalled();
  expect(imported).not.toHaveBeenCalled();
  expect(change).not.toHaveBeenCalled();
  expect(mocks.import.mock.calls[1][1]).toEqual({
    url: "https://example.com/page",
    title: "Report.html",
    parent_id: 9,
    overwrite: true,
  });
  view.move();
  expect(confirmation.signal.aborted).toBe(true);
  await act(async () => confirmation.onOk(close));
  expect(mocks.import).toHaveBeenCalledTimes(2);
});

it("keeps the new opening usable after StrictMode effect replay", async () => {
  render(
    <StrictMode>
      <WebLinkImportDialog
        knowledgeId="7"
        parentId={9}
        scopeKey="scope"
        open
        onOpenChange={change}
        onImported={imported}
      />
    </StrictMode>,
  );
  submit();
  await waitFor(() => expect(imported).toHaveBeenCalledOnce());
});
