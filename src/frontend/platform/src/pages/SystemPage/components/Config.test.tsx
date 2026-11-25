import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useContext } from "react";
import type { Ace } from "ace-builds";
import "ace-builds/src-noconflict/ace";
import "ace-builds/src-noconflict/mode-yaml";
import "ace-builds/src-noconflict/theme-twilight";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { notification } from "@bisheng/ui";
import { locationContext } from "@/contexts/locationContext";
import Config from "./Config";

const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/API/user", () => ({ getSysConfigApi: mocks.get, setSysConfigApi: mocks.save }));
vi.mock("@/controllers/request", () => ({ showApiError: mocks.error }));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({ reloadConfig: () => undefined }),
}));
vi.mock("react-ace", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-ace")>();
  return {
    // Keep the real editor and its prop reconciliation; isolate only the YAML worker.
    default: (props: import("react-ace").IAceEditorProps) =>
      <actual.default {...props} setOptions={{ ...props.setOptions, useWorker: false }} />,
  };
});

function Fixture({ reloadConfig }: { reloadConfig: () => void }) {
  const context = useContext(locationContext);
  return <locationContext.Provider value={{ ...context, reloadConfig }}><Config /></locationContext.Provider>;
}
function editor(): Ace.Editor {
  const element = document.getElementById("CodeEditor") as HTMLElement & { env: { editor: Ace.Editor } };
  return element.env.editor;
}
async function mount() {
  const reloadConfig = vi.fn();
  const view = render(<Fixture reloadConfig={reloadConfig} />);
  await waitFor(() => expect(editor().getValue()).toBe("enabled: true\n"));
  return { ...view, reloadConfig, refresh: () => view.rerender(<Fixture reloadConfig={reloadConfig} />) };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue("enabled: true\n");
  mocks.save.mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("preserves unsaved edits when the surrounding page rerenders after returning focus", async () => {
  const view = await mount();
  const draft = "enabled: false\n# unsaved draft\n";
  act(() => editor().setValue(draft, -1));
  act(() => { window.dispatchEvent(new Event("focus")); view.refresh(); });
  expect(editor().getValue()).toBe(draft);
  expect(mocks.get).toHaveBeenCalledTimes(1);
  expect(mocks.save).not.toHaveBeenCalled();
});

it("saves the submitted draft while preserving edits made before the response arrives", async () => {
  let finish!: () => void;
  mocks.save.mockReturnValue(new Promise<void>((resolve) => { finish = resolve; }));
  const view = await mount();
  act(() => editor().setValue("enabled: false\n", -1));
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  expect(mocks.save).toHaveBeenCalledWith({ data: "enabled: false\n" });
  const later = "enabled: false\n# later edit\n";
  act(() => editor().setValue(later, -1));
  await act(async () => finish());
  view.refresh();
  expect(editor().getValue()).toBe(later);
  expect(view.reloadConfig).toHaveBeenCalledTimes(1);
});

it("keeps the unsaved draft after a failed save and another render", async () => {
  const error = new Error("save failed");
  mocks.save.mockRejectedValue(error);
  const view = await mount();
  const draft = "enabled: false\n";
  act(() => editor().setValue(draft, -1));
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  view.refresh();
  expect(editor().getValue()).toBe(draft);
  expect(view.reloadConfig).not.toHaveBeenCalled();
});

it("continues to reject YAML validation errors before saving", async () => {
  const notice = vi.spyOn(notification, "open");
  await mount();
  act(() => editor().session.setAnnotations([{ row: 0, column: 0, type: "error", text: "Invalid YAML" }]));
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  expect(mocks.save).not.toHaveBeenCalled();
  expect(notice).toHaveBeenCalledWith(expect.objectContaining({ type: "error", description: "Invalid YAML" }));
});
