import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";

import { ActionMenuContent, ActionMenuItem } from "./ActionMenu";
import { DropdownMenu, DropdownMenuTrigger } from "./ui/DropdownMenu";

/**
 * Closing a menu used to leave a brand-coloured focus ring on the "..." button:
 * Radix returns focus to the trigger, and the browser paints the ring even when
 * the user only ever clicked. The ring belongs to the keyboard, so the focus
 * return is kept there and dropped for the pointer.
 */
function Menu() {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button type="button">more</button>
            </DropdownMenuTrigger>
            <ActionMenuContent>
                <ActionMenuItem label="rename" />
            </ActionMenuContent>
        </DropdownMenu>
    );
}

describe("action menu focus return", () => {
    it("does not send focus back to the trigger after a pointer interaction", () => {
        render(<Menu />);
        const trigger = screen.getByRole("button", { name: "more" });

        fireEvent.pointerDown(window);
        fireEvent.pointerDown(trigger);
        fireEvent.click(trigger);
        fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

        expect(trigger).not.toHaveFocus();
    });

    it("sends focus back to the trigger after a keyboard interaction", () => {
        render(<Menu />);
        const trigger = screen.getByRole("button", { name: "more" });

        trigger.focus();
        fireEvent.keyDown(trigger, { key: "Enter" });
        fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

        expect(trigger).toHaveFocus();
    });
});
