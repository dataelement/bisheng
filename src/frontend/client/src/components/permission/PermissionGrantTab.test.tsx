import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  getGrantablePermissionModels,
  mutateResourceGrants,
} from "~/api/permission";
import type {
  PermissionGrantAssignee,
  ResourcePermissionContext,
} from "~/api/permission";
import { PermissionGrantTab } from "./PermissionGrantTab";

jest.mock("~/hooks/AuthContext", () => ({
  // Not the creator of anything in these fixtures: the top-tier guard reads the
  // viewer from the roster, and none of them carry a CREATOR row.
  useAuthContext: () => ({ user: { id: "auth-user" } }),
}));

jest.mock("~/api/permission", () => ({
  getGrantablePermissionModels: jest.fn(),
  mutateResourceGrants: jest.fn(),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("./SubjectSearchUser", () => ({
  SubjectSearchUser: ({
    onChange,
    disabledIds,
    grantedLabels,
  }: {
    onChange: (subjects: Array<{ type: "user"; id: number; name: string }>) => void;
    disabledIds?: number[];
    grantedLabels?: Record<string, string>;
  }) => (
    <>
      <span data-testid="disabled-user-ids">{disabledIds?.join(",")}</span>
      <span data-testid="granted-user-labels">
        {Object.entries(grantedLabels ?? {})
          .map(([id, label]) => `${id}=${label}`)
          .join(",")}
      </span>
      <button
        type="button"
        onClick={() => onChange([{ type: "user", id: 99, name: "New User" }])}
      >
        select new user
      </button>
    </>
  ),
}));

jest.mock("./SubjectSearchDepartment", () => ({
  SubjectSearchDepartment: ({
    onChange,
  }: {
    onChange: (
      subjects: Array<{ type: "department"; id: number; name: string }>,
    ) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange([{ type: "department", id: 42, name: "Product" }])
      }
    >
      select department
    </button>
  ),
}));

jest.mock("./SubjectSearchUserGroup", () => ({
  SubjectSearchUserGroup: () => <div>group picker</div>,
}));

const mockedGetModels = getGrantablePermissionModels as jest.MockedFunction<
  typeof getGrantablePermissionModels
>;
const mockedMutate = mutateResourceGrants as jest.MockedFunction<
  typeof mutateResourceGrants
>;

const context: ResourcePermissionContext = {
  mode: "CUSTOM",
  parent_type: null,
  parent_id: null,
  resource_version: 7,
  catalog_release_id: 11,
  projection_state: "FINALIZED",
  can_manage_permission: true,
};

function existing(
  id: string,
  overrides: Partial<PermissionGrantAssignee> = {},
): PermissionGrantAssignee {
  return {
    assignee_id: id,
    assignee_version: 2,
    subject: { type: "user", id: String(id), name: `User ${id}` },
    model: { key: "viewer", name: "Viewer", level: 1, active: true },
    source: { type: "DIRECT", include_children: false },
    scope: "LOCAL",
    inherited_from: null,
    protected: false,
    editable: true,
    ...overrides,
  };
}

describe("F048 Client PermissionGrantTab", () => {
  beforeEach(() => {
    mockedGetModels.mockResolvedValue([
      { key: "viewer", name: "Viewer", level: 1, active: true },
      { key: "editor", name: "Editor", level: 2, active: true },
      { key: "inactive", name: "Inactive", level: 3, active: false },
    ]);
    mockedMutate.mockResolvedValue({ resource_version: 8, items: [] });
  });

  it("keeps the legacy add-dialog layout while submitting an F048 mutation", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        fixedSubjectType="user"
        legacyAddLayout
        showExistingAssignees={false}
        onSuccess={jest.fn()}
      />,
    );

    expect(
      await screen.findByTestId("legacy-permission-grant-layout"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select new user" }));
    fireEvent.change(
      screen.getByLabelText("f048_permission.grant.add_model"),
      { target: { value: "editor" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.grant.submit" }),
    );

    await waitFor(() => expect(mockedMutate).toHaveBeenCalledTimes(1));
    expect(mockedMutate).toHaveBeenCalledWith(
      "channel",
      "channel-1",
      expect.objectContaining({
        expected_resource_version: 7,
        expected_catalog_release_id: 11,
        changes: [
          {
            op: "ADD",
            model_key: "editor",
            subject: { type: "user", id: "99" },
          },
        ],
      }),
    );
  });

  it("submits exact ADD, MOVE, and REMOVE changes with IDs and versions", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        assignees={[existing("1"), existing("2")]}
        onSuccess={jest.fn()}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByLabelText("f048_permission.grant.model.1"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Inactive")).not.toBeInTheDocument();

    fireEvent.change(
      screen.getByLabelText("f048_permission.grant.model.1"),
      { target: { value: "editor" } },
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "f048_permission.grant.remove.2",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "select new user" }));
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.grant.add" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.grant.submit" }),
    );

    await waitFor(() => expect(mockedMutate).toHaveBeenCalledTimes(1));
    expect(mockedMutate).toHaveBeenCalledWith(
      "channel",
      "channel-1",
      expect.objectContaining({
        expected_resource_version: 7,
        expected_catalog_release_id: 11,
        changes: [
          {
            op: "MOVE",
            assignee_id: 1,
            expected_assignee_version: 2,
            target_model_key: "editor",
          },
          {
            op: "REMOVE",
            assignee_id: 2,
            expected_assignee_version: 2,
          },
          {
            op: "ADD",
            model_key: "viewer",
            subject: {
              type: "user",
              id: "99",
            },
          },
        ],
      }),
    );
    const payload = JSON.stringify(mockedMutate.mock.calls[0][2]);
    expect(payload).not.toMatch(/"source"|"protected"|"level"/);
  });

  it("locks inherited and protected rows", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        assignees={[
          existing("3", { protected: true, editable: false }),
          existing("4", { scope: "INHERITED", editable: false }),
        ]}
        onSuccess={jest.fn()}
      />,
    );

    expect(
      await screen.findByLabelText("f048_permission.grant.model.3"),
    ).toBeDisabled();
    expect(
      screen.getByLabelText("f048_permission.grant.model.4"),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "f048_permission.grant.remove.3",
      }),
    ).toBeDisabled();
  });

  it("allows one subject to hold different models without duplicating a model", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        assignees={[existing("99")]}
        onSuccess={jest.fn()}
      />,
    );

    await screen.findByLabelText("f048_permission.grant.model.99");
    expect(screen.getByTestId("disabled-user-ids")).toHaveTextContent("99");
    fireEvent.change(
      screen.getByLabelText("f048_permission.grant.add_model"),
      { target: { value: "editor" } },
    );
    expect(screen.getByTestId("disabled-user-ids")).toBeEmptyDOMElement();
    // Still selectable under another model, but the picker has to say the
    // subject already holds one — otherwise an existing grant looks untouched.
    expect(screen.getByTestId("granted-user-labels")).toHaveTextContent(
      "99=Viewer",
    );
  });

  it("does not label a subject whose only grant is inherited", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        assignees={[existing("77", { scope: "INHERITED" })]}
        onSuccess={jest.fn()}
      />,
    );

    await screen.findByTestId("granted-user-labels");
    expect(screen.getByTestId("granted-user-labels")).toBeEmptyDOMElement();
  });

  it("submits the canonical department userset relation", async () => {
    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        onSuccess={jest.fn()}
      />,
    );

    await screen.findByLabelText("f048_permission.grant.add_model");
    fireEvent.click(
      screen.getByRole("button", {
        name: "f048_permission.subject.department",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "select department" }),
    );
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.grant.add" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.grant.submit" }),
    );

    await waitFor(() => expect(mockedMutate).toHaveBeenCalledTimes(1));
    expect(mockedMutate.mock.calls[0][2]).toEqual(
      expect.objectContaining({
        changes: [
          {
            op: "ADD",
            model_key: "viewer",
            subject: {
              type: "department",
              id: "42",
              include_children: true,
              userset_relation: "subtree_member",
            },
          },
        ],
      }),
    );
  });

  it("fails closed on a version conflict", async () => {
    mockedMutate.mockRejectedValueOnce(new Error("version conflict"));

    render(
      <PermissionGrantTab
        resourceType="channel"
        resourceId="channel-1"
        context={context}
        assignees={[existing("1")]}
        onSuccess={jest.fn()}
      />,
    );
    await screen.findByLabelText("f048_permission.grant.model.1");
    fireEvent.change(
      screen.getByLabelText("f048_permission.grant.model.1"),
      { target: { value: "editor" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "f048_permission.grant.submit" }),
    );

    expect(
      await screen.findByText("f048_permission.grant.conflict"),
    ).toBeInTheDocument();
  });
});
