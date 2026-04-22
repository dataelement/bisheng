import { RelationSelect } from "@/components/bs-comp/permission/RelationSelect";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { fireEvent, render, screen } from "@/test/test-utils";
import { beforeAll, describe, expect, it, vi } from "vitest";

beforeAll(() => {
  if (!window.PointerEvent) {
    Object.defineProperty(window, "PointerEvent", {
      configurable: true,
      value: MouseEvent,
    });
  }

  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn();
  }

  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false);
  }

  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = vi.fn();
  }

  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = vi.fn();
  }
});

describe("select layering", () => {
  it("keeps select content above dialog content", async () => {
    render(
      <Dialog open onOpenChange={() => {}}>
        <DialogContent>
          <DialogTitle>Permission dialog</DialogTitle>
          <DialogDescription>Permission dialog description</DialogDescription>
          <RelationSelect
            value="owner"
            onChange={() => {}}
            options={[
              { id: "owner", name: "Owner", relation: "owner" },
              { id: "viewer", name: "Viewer", relation: "viewer" },
            ]}
          />
        </DialogContent>
      </Dialog>,
    );

    const trigger = screen.getByRole("combobox");
    trigger.focus();
    fireEvent.keyDown(trigger, {
      key: "ArrowDown",
      code: "ArrowDown",
      keyCode: 40,
    });

    const listbox = await screen.findByRole("listbox");
    const dialog = document.querySelector('[role="dialog"]');

    expect(dialog).not.toBeNull();
    expect(dialog?.className).toContain("z-50");
    expect(listbox.className).toContain("z-[60]");
  });
});
