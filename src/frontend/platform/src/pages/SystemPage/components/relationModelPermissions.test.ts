import { describe, expect, it } from "vitest"

import { filterAvailablePermissionIds } from "./relationModelPermissions"

describe("filterAvailablePermissionIds", () => {
  it("removes permissions that no longer exist in the backend template", () => {
    const sections = [
      {
        columns: [
          {
            items: [{ id: "view_resource" }, { id: "manage_resource" }],
          },
        ],
      },
    ]

    expect(
      filterAvailablePermissionIds(
        ["view_resource", "retired_permission", "manage_resource"],
        sections,
      ),
    ).toEqual(["view_resource", "manage_resource"])
  })
})
