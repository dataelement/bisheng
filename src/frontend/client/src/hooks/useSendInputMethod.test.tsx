import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { useSendInputMethod } from "./useSendInputMethod";

function Probe() {
  const input = useRef<HTMLInputElement>(null);
  const { onSendPointerDown, consumeTouchSend } = useSendInputMethod();
  return (
    <>
      <input ref={input} aria-label="Question" />
      <button
        onPointerDown={onSendPointerDown}
        onClick={(event) => {
          if (consumeTouchSend(event)) input.current?.blur();
        }}
      >
        Send
      </button>
    </>
  );
}

it.each(["mouse", "touch", "pen"])(
  "uses the actual %s send rather than width or device category",
  (pointerType) => {
    render(<Probe />);
    const input = screen.getByRole("textbox");
    input.focus();
    const button = screen.getByRole("button");
    const event = new Event("pointerdown", { bubbles: true });
    Object.defineProperty(event, "pointerType", { value: pointerType });
    fireEvent(button, event);
    fireEvent.click(button, { detail: 1 });
    if (pointerType === "touch") expect(input).not.toHaveFocus();
    else expect(input).toHaveFocus();
  },
);
it("does not treat keyboard activation as a previous touch send", () => {
  render(<Probe />);
  const input = screen.getByRole("textbox");
  input.focus();
  const button = screen.getByRole("button");
  const event = new Event("pointerdown", { bubbles: true });
  Object.defineProperty(event, "pointerType", { value: "touch" });
  fireEvent(button, event);
  fireEvent.click(button, { detail: 0 });
  expect(input).toHaveFocus();
});
