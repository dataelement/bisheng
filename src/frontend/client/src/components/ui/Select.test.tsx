import { fireEvent, render, screen } from "@testing-library/react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "./Dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./Select";

beforeAll(() => {
  if (!window.PointerEvent) {
    Object.defineProperty(window, "PointerEvent", {
      configurable: true,
      value: MouseEvent,
    });
  }

  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = jest.fn();
  }

  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = jest.fn(() => false);
  }

  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = jest.fn();
  }

  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = jest.fn();
  }
});

function renderDialogSelect() {
  render(
    <Dialog open onOpenChange={() => {}}>
      <DialogContent>
        <DialogTitle>Permission dialog</DialogTitle>
        <DialogDescription>Permission dialog description</DialogDescription>
        <Select value="owner" onValueChange={() => {}}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="owner">Owner</SelectItem>
            <SelectItem value="viewer">Viewer</SelectItem>
            <SelectItem value="editor">Editor</SelectItem>
            <SelectItem value="manager">Manager</SelectItem>
          </SelectContent>
        </Select>
      </DialogContent>
    </Dialog>,
  );
}

describe("Select", () => {
  it("renders above dialog content and is not constrained to trigger height", async () => {
    renderDialogSelect();

    const trigger = screen.getByRole("combobox");
    trigger.focus();
    fireEvent.keyDown(trigger, {
      key: "ArrowDown",
      code: "ArrowDown",
      keyCode: 40,
    });

    const listbox = await screen.findByRole("listbox");
    const viewport = document.querySelector("[data-radix-select-viewport]");

    expect(listbox.className).toContain("z-[120]");
    expect(viewport).not.toBeNull();
    expect(viewport?.className).not.toContain("h-[var(--radix-select-trigger-height)]");
  });
});
