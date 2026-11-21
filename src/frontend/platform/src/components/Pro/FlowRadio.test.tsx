import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { FlowRadio } from "./FlowRadio";

afterEach(cleanup);

function ControlledFlowRadio({
  initialLimit = 0,
  onChange,
}: {
  initialLimit?: number;
  onChange: (value: number) => void;
}) {
  const [limit, setLimit] = useState(initialLimit);
  return (
    <FlowRadio
      limit={limit}
      onChange={(value) => {
        setLimit(value);
        onChange(value);
      }}
    />
  );
}

it("restores external limits without emitting changes", () => {
  const onChange = vi.fn();
  const view = render(<FlowRadio limit={37} onChange={onChange} />);
  expect(screen.getByRole("radio", { name: "system.limit" })).toBeChecked();
  expect(screen.getByRole("spinbutton")).toHaveValue("37");

  view.rerender(<FlowRadio limit={0} onChange={onChange} />);
  expect(screen.getByRole("radio", { name: "system.unlimited" })).toBeChecked();
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();

  view.rerender(<FlowRadio limit={82} onChange={onChange} />);
  expect(screen.getByRole("spinbutton")).toHaveValue("82");
  expect(onChange).not.toHaveBeenCalled();
});

it("uses 0 for unlimited and starts each limited selection at 10", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<ControlledFlowRadio onChange={onChange} />);

  await user.click(screen.getByText("system.limit"));
  expect(onChange).toHaveBeenLastCalledWith(10);
  const input = screen.getByRole("spinbutton", { name: "system.maximum" });
  fireEvent.change(input, { target: { value: "42" } });
  expect(onChange).toHaveBeenLastCalledWith(42);

  await user.click(screen.getByText("system.unlimited"));
  expect(onChange).toHaveBeenLastCalledWith(0);
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();

  await user.click(screen.getByText("system.limit"));
  expect(screen.getByRole("spinbutton")).toHaveValue("10");
  expect(onChange.mock.calls.map(([value]) => value)).toEqual([10, 42, 0, 10]);
});

it("retains empty and invalid drafts without changing mode or emitting an invalid limit", () => {
  const onChange = vi.fn();
  render(<ControlledFlowRadio initialLimit={10} onChange={onChange} />);
  const input = screen.getByRole("spinbutton") as HTMLInputElement;

  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  expect(input).toHaveValue("");
  expect(input.validity.valid).toBe(false);
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("sharedUi.required")).toBeInTheDocument();

  for (const [draft, error] of [
    ["0", "sharedUi.minimum"],
    ["10000", "sharedUi.maximum"],
    ["1.5", "sharedUi.integer"],
  ]) {
    fireEvent.change(input, { target: { value: draft } });
    fireEvent.blur(input);
    expect(input).toHaveValue(draft);
    expect(input.validity.valid).toBe(false);
    expect(screen.getByText(error)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "system.limit" })).toBeChecked();
  }
  expect(onChange).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "24" } });
  expect(input.validity.valid).toBe(true);
  expect(input).not.toHaveAttribute("aria-invalid");
  expect(screen.queryByText("sharedUi.integer")).not.toBeInTheDocument();
  expect(onChange).toHaveBeenCalledExactlyOnceWith(24);
});

it("blocks native form submission for invalid drafts and allows the corrected value", async () => {
  const user = userEvent.setup();
  const submit = vi.fn();
  const onChange = vi.fn();
  render(
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <ControlledFlowRadio initialLimit={10} onChange={onChange} />
      <button type="submit">Save</button>
    </form>
  );
  const input = screen.getByRole("spinbutton");

  fireEvent.change(input, { target: { value: "10000" } });
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(submit).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "" } });
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(submit).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "31" } });
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith(31);
  expect(submit).toHaveBeenCalledOnce();
});

it("steps whole numbers within the limited bounds", () => {
  const onChange = vi.fn();
  render(<ControlledFlowRadio initialLimit={9998} onChange={onChange} />);
  const input = screen.getByRole("spinbutton");

  fireEvent.keyDown(input, { key: "ArrowUp" });
  expect(input).toHaveValue("9999");
  fireEvent.keyDown(input, { key: "ArrowUp" });
  expect(onChange).toHaveBeenCalledExactlyOnceWith(9999);

  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.keyDown(input, { key: "ArrowUp" });
  expect(input).toHaveValue("1");
  expect(onChange).toHaveBeenLastCalledWith(1);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(input).toHaveValue("1");
  expect(onChange).toHaveBeenCalledTimes(2);
});
