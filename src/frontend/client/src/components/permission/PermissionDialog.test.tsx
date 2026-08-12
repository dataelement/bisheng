import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  applyResourcePermissionModeDraft,
  createResourcePermissionModeDraft,
  getResourcePermissionContext,
} from "~/api/permission";
import type { ResourcePermissionContext } from "~/api/permission";
import { ModeHeader } from "./ModeHeader";
import { PermissionDialog } from "./PermissionDialog";

jest.mock("~/hooks/AuthContext", () => ({
  // Not the creator of anything in these fixtures: the top-tier guard reads the
  // viewer from the roster, and none of them carry a CREATOR row.
  useAuthContext: () => ({ user: { id: "auth-user" } }),
}));

jest.mock("~/api/permission", () => ({
  applyResourcePermissionModeDraft: jest.fn(),
  createResourcePermissionModeDraft: jest.fn(),
  getResourcePermissionContext: jest.fn(),
  getMyResourcePermissions: jest.fn(),
  getResourcePermissionGrants: jest.fn(),
  getGrantablePermissionModels: jest.fn(),
  mutateResourceGrants: jest.fn(),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("./PermissionListTab", () => ({
  PermissionListTab: ({
    context,
  }: {
    context: ResourcePermissionContext;
  }) => <div>roster:{context.mode}</div>,
}));

jest.mock("./PermissionGrantTab", () => ({
  PermissionGrantTab: ({
    onSuccess,
    legacyAddLayout,
  }: {
    onSuccess: (result: {
      resource_version: number;
      items: [];
    }) => void;
    legacyAddLayout?: boolean;
  }) => (
    <div data-layout={legacyAddLayout ? "legacy-add" : "default"}>
      grant editor
      <button
        type="button"
        onClick={() => onSuccess({ resource_version: 8, items: [] })}
      >
        save grants
      </button>
    </div>
  ),
}));

const mockedGetContext = getResourcePermissionContext as jest.MockedFunction<
  typeof getResourcePermissionContext
>;
const mockedCreateDraft =
  createResourcePermissionModeDraft as jest.MockedFunction<
    typeof createResourcePermissionModeDraft
  >;
const mockedApplyDraft =
  applyResourcePermissionModeDraft as jest.MockedFunction<
    typeof applyResourcePermissionModeDraft
  >;

const context: ResourcePermissionContext = {
  mode: "CUSTOM",
  parent_type: "folder",
  parent_id: "parent-1",
  resource_version: 7,
  catalog_release_id: 11,
  projection_state: "FINALIZED",
  can_manage_permission: true,
};

describe("F048 Client PermissionDialog", () => {
  beforeEach(() => {
    mockedGetContext.mockResolvedValue(context);
    mockedCreateDraft.mockResolvedValue({
      draft_id: "mode-draft-1",
      target_mode: "INHERIT",
      impact_checksum: "impact-1",
      affected_assignees: 3,
      expires_at: "2099-01-01T00:00:00Z",
    });
    mockedApplyDraft.mockResolvedValue({
      applied: true,
      mode: "INHERIT",
      resource_version: 8,
    });
  });

  it("opens without parking focus on the close button", async () => {
    // Radix focuses the first focusable child on open, which here is the X, so
    // every open showed a focus ring sitting on the close button.
    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Policy.pdf"
      />,
    );

    await screen.findByText("roster:CUSTOM");

    const closeButtons = screen
      .getAllByRole("button")
      .filter((node) => node.textContent?.includes("Close"));
    for (const button of closeButtons) {
      expect(button).not.toHaveFocus();
    }
  });

  it("keeps the legacy subject tabs and opens add permission in a separate dialog", async () => {
    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Policy.pdf"
      />,
    );

    expect(await screen.findByText("roster:CUSTOM")).toBeInTheDocument();
    expect(mockedGetContext).toHaveBeenCalledWith(
      "knowledge_file",
      "file-1",
    );
    expect(
      screen.getByRole("tab", { name: "f048_permission.subject.user" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", {
        name: "f048_permission.subject.department",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", {
        name: "f048_permission.subject.user_group",
      }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "com_permission.tab_grant" }),
    );
    expect(await screen.findByText("grant editor")).toBeInTheDocument();
    expect(screen.getByText("grant editor")).toHaveAttribute(
      "data-layout",
      "legacy-add",
    );
    expect(
      screen.getByRole("button", {
        name: "f048_permission.subject.user",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "f048_permission.subject.department",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "f048_permission.subject.user_group",
      }),
    ).toBeInTheDocument();
  });

  it("closes the add dialog after a successful grant mutation", async () => {
    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Policy.pdf"
      />,
    );

    await userEvent.click(
      await screen.findByRole("button", {
        name: "com_permission.tab_grant",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "save grants" }));

    expect(screen.queryByText("grant editor")).not.toBeInTheDocument();
    expect(await screen.findByText("roster:CUSTOM")).toBeInTheDocument();
  });

  it("keeps inherited roster read-only and hides the grant editor", async () => {
    mockedGetContext.mockResolvedValueOnce({
      ...context,
      mode: "INHERIT",
    });

    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="knowledge_file"
        resourceId="file-1"
        resourceName="Policy.pdf"
      />,
    );

    expect(await screen.findByText("roster:INHERIT")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "com_permission.tab_grant",
      }),
    ).not.toBeInTheDocument();
  });

  it("does not show the permission mode control without a parent", async () => {
    mockedGetContext.mockResolvedValueOnce({
      ...context,
      parent_type: null,
      parent_id: null,
    });

    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="knowledge_space"
        resourceId="space-1"
        resourceName="Space"
      />,
    );

    expect(await screen.findByText("roster:CUSTOM")).toBeInTheDocument();
    expect(screen.queryByTestId("permission-mode-switch")).toBeNull();
  });
});

describe("F048 Client ModeHeader", () => {
  it("creates a server impact draft and applies only after confirmation", async () => {
    const onApplied = jest.fn();
    render(
      <ModeHeader
        resourceType="knowledge_file"
        resourceId="file-1"
        context={context}
        onApplied={onApplied}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "f048_permission.mode.switch_to_inherit",
      }),
    );
    expect(
      await screen.findByText("f048_permission.mode.affected_assignees"),
    ).toBeInTheDocument();
    expect(mockedCreateDraft).toHaveBeenCalledWith(
      "knowledge_file",
      "file-1",
      {
        target_mode: "INHERIT",
        expected_resource_version: 7,
        expected_catalog_release_id: 11,
      },
    );

    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.mode.confirm" }),
    );
    await waitFor(() => expect(mockedApplyDraft).toHaveBeenCalledTimes(1));
    expect(mockedApplyDraft).toHaveBeenCalledWith(
      "knowledge_file",
      "file-1",
      "mode-draft-1",
      expect.objectContaining({
        expected_resource_version: 7,
        expected_catalog_release_id: 11,
        confirmed: true,
      }),
    );
    expect(onApplied).toHaveBeenCalled();
  });

  it("supports cancel and rejects an expired draft", async () => {
    mockedCreateDraft.mockResolvedValueOnce({
      draft_id: "expired",
      target_mode: "INHERIT",
      impact_checksum: "impact-expired",
      affected_assignees: 1,
      expires_at: "2000-01-01T00:00:00Z",
    });

    render(
      <ModeHeader
        resourceType="knowledge_file"
        resourceId="file-1"
        context={context}
        onApplied={jest.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "f048_permission.mode.switch_to_inherit",
      }),
    );

    expect(
      await screen.findByText("f048_permission.mode.expired"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "f048_permission.mode.confirm" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.mode.cancel" }),
    );
    expect(
      screen.queryByText("f048_permission.mode.expired"),
    ).not.toBeInTheDocument();
    expect(mockedApplyDraft).not.toHaveBeenCalled();
  });
});
