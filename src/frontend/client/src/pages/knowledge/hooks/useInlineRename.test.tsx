import { act, fireEvent, render, screen } from "@testing-library/react";
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
  onRename: (newName: string) => void;
  onValidateName?: (newName: string) => string | null;
  isCreating?: boolean;
}

/** Mirrors how FileRow / FileCard wire the hook to their rename input. */
function Harness({ fileName, onRename, onValidateName, isCreating = false }: HarnessProps) {
  const {
    isRenaming,
    renameValue,
    setRenameValue,
    inputRef,
    handleRenameSubmit,
    handleKeyDown,
    startRenaming,
  } = useInlineRename({
    fileName,
    isFolder: isCreating,
    isCreating,
    onRename,
    onValidateName,
  });

  return (
    <div>
      <button type="button" onClick={startRenaming}>
        rename
      </button>
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
  it("keeps a new folder editable when the closing menu restores focus to its trigger", () => {
    jest.useFakeTimers();
    try {
      const onRename = jest.fn();
      render(<Harness fileName="New folder" isCreating onRename={onRename} />);
      const input = screen.getByTestId("rename-input") as HTMLInputElement;

      // Radix restores focus in a task after the create placeholder mounts.
      act(() => {
        setTimeout(() => screen.getByText("rename").focus(), 0);
        jest.advanceTimersByTime(10);
      });

      expect(onRename).not.toHaveBeenCalled();
      expect(input).toHaveFocus();
      expect(input.selectionStart).toBe(0);
      expect(input.selectionEnd).toBe("New folder".length);

      fireEvent.change(input, { target: { value: "My folder" } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onRename).toHaveBeenCalledTimes(1);
      expect(onRename).toHaveBeenCalledWith("My folder");
    } finally {
      jest.useRealTimers();
    }
  });

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
