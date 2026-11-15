import { fireEvent, render, screen } from "@testing-library/react";
import { WorkbenchMenuButton } from "./WorkbenchMenuButton";

let mockChannel = "web";
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({ channel: mockChannel }),
}));

it("preserves the existing Web menu action and hides it in both desktop widths", () => {
  const onClick = jest.fn();
  const ui = render(
    <WorkbenchMenuButton onClick={onClick} aria-label="Open menu">
      Menu
    </WorkbenchMenuButton>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
  expect(onClick).toHaveBeenCalledTimes(1);
  mockChannel = "desktop";
  ui.rerender(
    <WorkbenchMenuButton onClick={onClick}>Menu</WorkbenchMenuButton>,
  );
  expect(screen.queryByRole("button")).toBeNull();
});
