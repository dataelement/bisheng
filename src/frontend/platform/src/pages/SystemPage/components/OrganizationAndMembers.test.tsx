import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import OrganizationAndMembers from "./OrganizationAndMembers";

const departments = vi.hoisted(() => {
  let finish: (module: Record<string, unknown>) => void = () => undefined;
  const module = new Promise<Record<string, unknown>>((resolve) => {
    finish = resolve;
  });
  return { module, finish: (value: Record<string, unknown>) => finish(value) };
});

vi.mock("./Departments", () => departments.module);

afterEach(cleanup);

it("shows the loading state until the department page finishes loading", async () => {
  render(<OrganizationAndMembers />);

  expect(screen.getByRole("status", { name: "loading" })).toHaveAttribute(
    "aria-busy",
    "true"
  );

  await act(async () => {
    departments.finish({ default: () => <div>Department page loaded</div> });
  });

  expect(await screen.findByText("Department page loaded")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
