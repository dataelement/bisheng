import { fireEvent, render, screen } from "@testing-library/react";
import type { ButtonHTMLAttributes } from "react";
import { PermissionDraftEditor } from "./PermissionDraftEditor";
import type { PermissionDraftRow } from "./usePermissionDraft";

jest.mock("@bisheng/ui", () => ({
  Button: ({ children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}), { virtual: true });

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

const pending: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 7,
  subjectName: "Ada",
  relation: "viewer",
  modelId: "viewer",
  authorizationStatus: "pending",
  approvalInstanceId: 1201,
};

const capabilities = {
  canChangeRelation: true,
  canRemove: true,
  relationModels: [
    { id: "viewer", name: "Viewer", relation: "viewer" as const },
    { id: "editor", name: "Editor", relation: "editor" as const },
  ],
};

describe("PermissionDraftEditor", () => {
  it("renders pending rows as read-only", () => {
    const onChange = jest.fn();
    render(
      <PermissionDraftEditor
        value={[pending]}
        onChange={onChange}
        capabilities={capabilities}
      />,
    );

    expect(screen.getByText("com_invite.pending")).not.toBeNull();
    expect(screen.queryByText("com_permission.remove")).toBeNull();
    const trigger = screen.getByRole("combobox");
    expect((trigger as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
  });
});
