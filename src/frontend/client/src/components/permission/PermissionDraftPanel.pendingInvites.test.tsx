import { render, screen } from "@testing-library/react";
import type { PendingInviteItem } from "~/api/permission";
import { PermissionDraftPanel } from "./PermissionDraftPanel";

/**
 * Somebody added to a knowledge space owes their own confirmation before they
 * hold anything, so no permission row exists for them yet. This panel only
 * rendered permission rows, so a person added and saved simply vanished and
 * the save looked like it had failed. The label is the one the permission
 * dialog already uses; the two surfaces must not invent separate wording.
 */

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("./PermissionDraftEditor", () => ({
  PermissionDraftEditor: () => <div>editor</div>,
}));

const INVITE: PendingInviteItem = {
  subject_type: "user",
  subject_id: 150035,
  subject_name: "wangxinlei08",
  authorization_status: "pending",
  business_request_id: 14,
  approval_status: "pending",
  execution_state: "awaiting_approval",
  retryable: false,
};

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof PermissionDraftPanel>> = {},
) {
  return render(
    <PermissionDraftPanel
      value={[]}
      onChange={jest.fn()}
      capabilities={{} as never}
      activeSubjectType="user"
      onActiveSubjectTypeChange={jest.fn()}
      onAddAuthorization={jest.fn()}
      pendingInvites={[INVITE]}
      {...overrides}
    />,
  );
}

describe("F045 pending invites on the space settings panel", () => {
  it("shows a person who still owes a confirmation", () => {
    renderPanel();

    expect(screen.getByText("wangxinlei08")).toBeInTheDocument();
    expect(
      screen.getByText("f048_permission.roster.invite_pending"),
    ).toBeInTheDocument();
  });

  it("does not fall back to the empty state while an invite is outstanding", () => {
    renderPanel();

    expect(
      screen.queryByText("com_unified_permission.authorization_empty"),
    ).not.toBeInTheDocument();
  });

  it("marks an invitation whose grant failed", () => {
    renderPanel({
      pendingInvites: [{ ...INVITE, execution_state: "failed" }],
    });

    expect(
      screen.getByText("f048_permission.roster.invite_failed"),
    ).toBeInTheDocument();
  });

  it("keeps invitations off the department and group tabs", () => {
    renderPanel({ activeSubjectType: "department" });

    expect(screen.queryByText("wangxinlei08")).not.toBeInTheDocument();
  });

  it("still shows the empty state when nobody is pending", () => {
    renderPanel({ pendingInvites: [] });

    expect(
      screen.getByText("com_unified_permission.authorization_empty"),
    ).toBeInTheDocument();
  });
});
