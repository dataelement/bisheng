import { render, screen } from "@testing-library/react";
import { SpaceProcessingStatus } from "./SpaceProcessingStatus";

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));

it.each([[3, "rebuilding"], [4, "rebuild_failed"]])("shows the space state %s without task controls", (state, key) => {
  render(<SpaceProcessingStatus state={Number(state)} />);
  expect(screen.getByRole("status")).toHaveTextContent(`com_knowledge.processing_jobs.${key}`);
  expect(screen.queryByRole("button")).toBeNull();
});

it.each([undefined, null, 1, 2])("does not show a task entry or stale state for %s", (state) => {
  const { container } = render(<SpaceProcessingStatus state={state} />);
  expect(container).toBeEmptyDOMElement();
});
