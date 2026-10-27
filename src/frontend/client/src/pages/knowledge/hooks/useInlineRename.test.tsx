import { Dropdown, DropdownItem } from "@bisheng/ui";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useInlineRename } from "./useInlineRename";

const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

interface HarnessProps {
  fileName: string;
  onRename: (newName: string) => void | Promise<void>;
  onValidateName?: (newName: string) => string | null;
  viaMenu?: boolean;
  isFolder?: boolean;
}

/** Mirrors how FileRow / FileCard wire the hook to their rename input. */
function Harness({ fileName, onRename, onValidateName, viaMenu = false, isFolder = false }: HarnessProps) {
  const {
    isRenaming,
    renameValue,
    setRenameValue,
    inputRef,
    handleRenameSubmit,
    handleKeyDown,
    startRenaming,
    startRenamingFromMenu,
    handleMenuCloseAutoFocus,
  } = useInlineRename({
    fileName,
    isFolder,
    isCreating: false,
    onRename,
    onValidateName,
  });

  return (
    <div>
      {viaMenu ? (
        <Dropdown
          menu={<>
            <DropdownItem onSelect={startRenamingFromMenu}>rename</DropdownItem>
            <DropdownItem>other action</DropdownItem>
          </>}
          onCloseAutoFocus={handleMenuCloseAutoFocus}
        >
          <button type="button">more</button>
        </Dropdown>
      ) : (
        <button type="button" onClick={startRenaming}>rename</button>
      )}
      {isRenaming && (
        <input
          ref={inputRef}
          data-testid="rename-input"
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          onBlur={handleRenameSubmit}
          onKeyDown={handleKeyDown}
        />
      )}
    </div>
  );
}

function startRenaming(name = "a.pdf") {
  const onRename = jest.fn();
  render(<Harness fileName={name} onRename={onRename} />);
  fireEvent.click(screen.getByText("rename"));
  return { onRename, input: screen.getByTestId("rename-input") };
}

/** A click anywhere outside the field, as the browser delivers it. */
function pointerDownOutside() {
  fireEvent(document.body, new Event("pointerdown", { bubbles: true }));
}

describe("useInlineRename", () => {
  it("commits on a click outside the input", () => {
    const { onRename, input } = startRenaming();

    fireEvent.change(input, { target: { value: "renamed.pdf" } });
    pointerDownOutside();

    expect(onRename).toHaveBeenCalledWith("renamed.pdf");
    expect(screen.queryByTestId("rename-input")).toBeNull();
  });

  it("commits once when the outside click also blurs the input", () => {
    const { onRename, input } = startRenaming();

    fireEvent.change(input, { target: { value: "renamed.pdf" } });
    pointerDownOutside();
    fireEvent.blur(input);

    expect(onRename).toHaveBeenCalledTimes(1);
  });

  it("closes without renaming when the name is unchanged", () => {
    const { onRename } = startRenaming();

    pointerDownOutside();

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByTestId("rename-input")).toBeNull();
  });

  it("keeps the field open and toasts when validation rejects the name", () => {
    const onRename = jest.fn();
    render(
      <Harness
        fileName="a.pdf"
        onRename={onRename}
        onValidateName={() => "com_knowledge.name_duplicate_file"}
      />,
    );
    fireEvent.click(screen.getByText("rename"));
    fireEvent.change(screen.getByTestId("rename-input"), {
      target: { value: "taken.pdf" },
    });

    pointerDownOutside();

    expect(onRename).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalled();
    expect(screen.queryByTestId("rename-input")).not.toBeNull();
  });
});

describe("rename from the shared dropdown", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => {
    cleanup();
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it.each([
    { fileName: "report.pdf", isFolder: false, selectionEnd: 6 },
    { fileName: "project.notes", isFolder: true, selectionEnd: 13 },
  ])("keeps $fileName editable after the menu closes", ({ fileName, isFolder, selectionEnd }) => {
    const onRename = jest.fn();
    render(<Harness fileName={fileName} isFolder={isFolder} onRename={onRename} viaMenu />);

    fireEvent.keyDown(screen.getByRole("button", { name: "more" }), { key: "ArrowDown" });
    act(() => jest.runOnlyPendingTimers());
    fireEvent.click(screen.getByRole("menuitem", { name: "rename" }));
    act(() => jest.runOnlyPendingTimers());

    const input = screen.getByRole<HTMLInputElement>("textbox");
    expect(input).toHaveFocus();
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(selectionEnd);
    expect(onRename).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "updated" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith("updated");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("waits for the menu exit animation before opening the editor", () => {
    const getComputedStyle = window.getComputedStyle.bind(window);
    jest.spyOn(window, "getComputedStyle").mockImplementation((element, pseudoElement) => {
      const style = getComputedStyle(element, pseudoElement);
      if (element.getAttribute("role") !== "menu") return style;
      return new Proxy(style, {
        get(target, property) {
          if (property === "animationName") {
            return element.getAttribute("data-state") === "open" ? "menu-in" : "menu-out";
          }
          return Reflect.get(target, property);
        },
      });
    });
    const onRename = jest.fn();
    render(<Harness fileName="report.pdf" onRename={onRename} viaMenu />);
    fireEvent.keyDown(screen.getByRole("button", { name: "more" }), { key: "ArrowDown" });
    act(() => jest.runOnlyPendingTimers());
    const menu = screen.getByRole("menu");
    fireEvent.click(screen.getByRole("menuitem", { name: "rename" }));
    act(() => jest.advanceTimersByTime(200));

    expect(menu).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    const end = new Event("animationend", { bubbles: true });
    Object.defineProperty(end, "animationName", { value: "menu-out" });
    fireEvent(menu, end);
    act(() => jest.runOnlyPendingTimers());
    act(() => jest.runOnlyPendingTimers());

    expect(menu).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(onRename).not.toHaveBeenCalled();
  });

  it("restores the trigger focus for actions that do not rename", () => {
    render(<Harness fileName="report.pdf" onRename={jest.fn()} viaMenu />);
    const trigger = screen.getByRole("button", { name: "more" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    act(() => jest.runOnlyPendingTimers());
    fireEvent.click(screen.getByRole("menuitem", { name: "other action" }));
    act(() => jest.runOnlyPendingTimers());

    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

it('keeps the edited name after a rejected save and permits retry', async () => {
  const onRename = jest.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(undefined);
  render(<Harness fileName="a.pdf" onRename={onRename} />);
  fireEvent.click(screen.getByText('rename'));
  fireEvent.change(screen.getByTestId('rename-input'), { target: { value: 'draft.pdf' } });
  pointerDownOutside();
  await waitFor(() => expect(onRename).toHaveBeenCalledTimes(1));
  expect(screen.getByTestId('rename-input')).toHaveValue('draft.pdf');
  await act(async () => {});
  pointerDownOutside();
  await waitFor(() => expect(screen.queryByTestId('rename-input')).toBeNull());
  expect(onRename).toHaveBeenLastCalledWith('draft.pdf');
});
