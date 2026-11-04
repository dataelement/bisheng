import { act, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { useElementSize } from "./useElementSize";

it("observes content changes independent of the viewport and releases the observer", () => {
  let width = 820;
  let update = () => {};
  const disconnect = jest.fn();
  const previous = global.ResizeObserver;
  global.ResizeObserver = jest
    .fn()
    .mockImplementation((callback: () => void) => {
      update = callback;
      return { observe: jest.fn(), disconnect };
    });
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(() => ({ width, height: 600 }) as DOMRect);
  function Probe() {
    const ref = useRef<HTMLDivElement>(null);
    const size = useElementSize(ref);
    return (
      <div ref={ref}>
        <output>{size.width}</output>
      </div>
    );
  }
  const view = render(<Probe />);
  expect(screen.getByText("820")).toBeInTheDocument();
  act(() => {
    width = 390;
    update();
  });
  expect(screen.getByText("390")).toBeInTheDocument();
  view.unmount();
  expect(disconnect).toHaveBeenCalledTimes(1);
  global.ResizeObserver = previous;
});
