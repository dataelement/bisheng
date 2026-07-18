import { describe, expect, it, vi } from "vitest";

import { paginateAllUserGroupMembers } from "@/controllers/API/userGroups";
import { canDeleteUserGroup } from "@/pages/SystemPage/components/UserGroup";

describe("paginateAllUserGroupMembers", () => {
  it("loads every page until total is reached", async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        data: [
          { user_id: 1, user_name: "u1", is_group_admin: false },
          { user_id: 2, user_name: "u2", is_group_admin: false },
        ],
        total: 3,
      })
      .mockResolvedValueOnce({
        data: [
          { user_id: 3, user_name: "u3", is_group_admin: false },
        ],
        total: 3,
      });

    const rows = await paginateAllUserGroupMembers(fetchPage, {
      limit: 2,
    });

    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(rows.map((r) => r.user_id)).toEqual([1, 2, 3]);
  });

  it("stops when an empty page is returned", async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        data: [
          { user_id: 1, user_name: "u1", is_group_admin: false },
        ],
        total: 10,
      })
      .mockResolvedValueOnce({
        data: [],
        total: 10,
      });

    const rows = await paginateAllUserGroupMembers(fetchPage, {
      limit: 1,
    });

    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(rows.map((r) => r.user_id)).toEqual([1]);
  });
});

describe("canDeleteUserGroup", () => {
  it("allows user-group managers to delete groups they created", () => {
    expect(
      canDeleteUserGroup(
        { role: "user", can_manage_user_groups: true, user_id: 5 },
        { id: 1, group_name: "g", visibility: "public", create_user: 5 },
      ),
    ).toBe(true);
  });

  it("normalizes creator ids before comparing", () => {
    expect(
      canDeleteUserGroup(
        { role: "user", can_manage_user_groups: true, user_id: 5 },
        { id: 1, group_name: "g", visibility: "public", create_user: "5" },
      ),
    ).toBe(true);
  });

  it("does not allow scoped managers to delete groups created by others", () => {
    expect(
      canDeleteUserGroup(
        { role: "user", can_manage_user_groups: true, user_id: 5 },
        { id: 1, group_name: "g", visibility: "public", create_user: 6 },
      ),
    ).toBe(false);
  });
});
