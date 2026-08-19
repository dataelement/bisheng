/** @jest-environment node */

import type { ApprovalTaskDetail } from "~/api/approval";
import { useLocalize } from "~/hooks";

import { buildResourceUserInviteBusinessRows } from "./ResourceUserInviteBusinessContent";

const localize = ((key: string) => key) as ReturnType<typeof useLocalize>;

describe("resource user invite business content", () => {
  it("projects user-facing fields without exposing internal ids or model variables", () => {
    const detail = {
      scenario_code: "resource_user_invite_confirmation",
      business_name: "Space 111",
      detail_snapshot: {
        resource_type: "knowledge_space",
        resource_id: "81",
        resource_name: "Space 111",
        target_user_id: 18,
        target_user_name: "alice",
        relation: "manager",
        model_id: "manager",
        role_name: "Manage",
      },
    } as ApprovalTaskDetail;

    expect(buildResourceUserInviteBusinessRows(detail, localize)).toEqual([
      { label: "com_approval_invite_field_resource_type", value: "com_approval_invite_resource_type_knowledge_space" },
      { label: "com_approval_invite_field_resource_name", value: "Space 111" },
      { label: "com_approval_invite_field_target_user", value: "alice" },
      { label: "com_approval_invite_field_permission", value: "Manage" },
    ]);
  });

  it("does not claim business content belonging to another scenario", () => {
    const detail = { scenario_code: "menu_access_request" } as ApprovalTaskDetail;
    expect(buildResourceUserInviteBusinessRows(detail, localize)).toBeNull();
  });
});
