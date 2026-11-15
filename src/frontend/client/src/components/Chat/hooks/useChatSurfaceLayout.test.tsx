import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { useChatSurfaceLayout } from "./useChatSurfaceLayout";

it("measures the combined content region and preserves its composer through internal resizing", () => {
  let width = 1200;
  let resize = () => {};
  global.ResizeObserver = jest
    .fn()
    .mockImplementation((callback: () => void) => {
      resize = callback;
      return { observe: jest.fn(), disconnect: jest.fn() };
    });
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(() => ({ width, height: 600 }) as DOMRect);
  function Surface() {
    const ref = useRef<HTMLDivElement>(null);
    const layout = useChatSurfaceLayout(ref);
    const [draft, setDraft] = useState("");
    return (
      <div ref={ref}>
        <output>{layout.isCompactLayout ? "overlay" : "dock"}</output>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </div>
    );
  }
  render(<Surface />);
  expect(screen.getByText("dock")).toBeInTheDocument();
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "Keep draft" } });
  act(() => {
    width = 700;
    resize();
  });
  expect(screen.getByText("overlay")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toBe(input);
  expect(input).toHaveValue("Keep draft");
  act(() => {
    width = 1100;
    resize();
  });
  expect(screen.getByText("dock")).toBeInTheDocument();
});
