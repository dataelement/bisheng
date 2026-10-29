import { describe, expect, it } from "vitest"

import { canSeeAbnormalFiles } from "@/pages/LogPage/abnormalUpload/access"

describe("abnormal files tab access", () => {
    it("shows the tab to platform operators and super admins only", () => {
        expect(canSeeAbnormalFiles({ role: "平台管理员" })).toBe(true)
        expect(canSeeAbnormalFiles({ role: "系统管理员" })).toBe(true)
        expect(canSeeAbnormalFiles({ role: "admin" })).toBe(true)
        expect(canSeeAbnormalFiles({ role: "内部员工", is_global_super: true })).toBe(true)
        expect(canSeeAbnormalFiles({ role: "管理员" })).toBe(false)
        expect(canSeeAbnormalFiles({ role: "内部员工" })).toBe(false)
        expect(canSeeAbnormalFiles(null)).toBe(false)
    })
})
