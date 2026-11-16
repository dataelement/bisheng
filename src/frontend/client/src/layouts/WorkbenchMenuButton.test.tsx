import { fireEvent, render, screen } from "@testing-library/react";
import { WorkbenchMenuButton } from "./WorkbenchMenuButton";

let mockChannel = "web";
let mockHostHeader = false;
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({
    channel: mockChannel,
    capabilities: { hasHostChatHeader: mockHostHeader },
  }),
}));

beforeEach(() => {
  mockChannel = "web";
  mockHostHeader = false;
});

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

it("removes the mobile module row when the app owns the header", () => {
  mockHostHeader = true;
  const view = render(
    <header>
      <div className="h-11">
        <WorkbenchMenuButton aria-label="Open sidebar">Menu</WorkbenchMenuButton>
        <h1>订阅</h1>
      </div>
    </header>,
  );
  expect(screen.queryByRole("button", { name: "Open sidebar" })).toBeNull();
  expect(view.container.querySelector("header")?.hidden).toBe(true);
});
