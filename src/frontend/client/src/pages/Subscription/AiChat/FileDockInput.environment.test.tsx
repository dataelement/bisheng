import { fireEvent, render, screen } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { FileDockInput } from "./FileDockInput";

jest.mock("~/hooks", () => ({ usePrefersMobileLayout: () => true }));
jest.mock("~/hooks/queries/data-provider", () => ({
  useGetWorkbenchModelsQuery: () => ({ data: {} }),
}));
jest.mock("~/components/ui", () => ({
  TextareaAutosize: jest
    .requireActual("react")
    .forwardRef(
      (
        props: ComponentProps<"textarea"> & { onHeightChange?: unknown },
        ref: React.Ref<HTMLTextAreaElement>,
      ) => {
        const native = { ...props };
        delete native.onHeightChange;
        return <textarea {...native} ref={ref} />;
      },
    ),
}));
jest.mock("~/components/Chat/AiModelSelect", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("~/components/Voice/SpeechToText", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("~/components/svg", () => ({ SendIcon: () => null }));
jest.mock("~/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
}));
const mockSend = jest.fn();
function Input() {
  const [value, setValue] = useState("Question");
  return (
    <FileDockInput
      value={value}
      onChange={setValue}
      onSend={mockSend}
      model={{ value: 1, onChange: () => {} }}
      disabled={false}
      isStreaming={false}
      placeholder="Question"
      variant="box"
    />
  );
}
it.each(["mouse", "touch"])(
  "only dismisses focus for a real %s send in a narrow layout",
  (pointerType) => {
    render(<Input />);
    const input = screen.getByRole("textbox");
    input.focus();
    const send = screen.getByRole("button", { name: "Send message" });
    const pointer = new Event("pointerdown", { bubbles: true });
    Object.defineProperty(pointer, "pointerType", { value: pointerType });
    fireEvent(send, pointer);
    fireEvent.click(send, { detail: 1 });
    expect(mockSend).toHaveBeenCalledWith("Question");
    if (pointerType === "touch") expect(input).not.toHaveFocus();
    else expect(input).toHaveFocus();
  },
);
it("keeps keyboard focus when Enter sends from a narrow desktop pane", () => {
  render(<Input />);
  const input = screen.getByRole("textbox");
  input.focus();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(mockSend).toHaveBeenCalledWith("Question");
  expect(input).toHaveFocus();
});
