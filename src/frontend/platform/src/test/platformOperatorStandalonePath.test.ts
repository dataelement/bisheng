import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import {
    isPlatformOperatorStandalonePath,
    isStandalonePath,
    resolveNoAdminConsoleAction,
} from "@/routes/standalone"

const here = dirname(fileURLToPath(import.meta.url))
const userContextSource = readFileSync(
    resolve(here, "../contexts/userContext.tsx"),
    "utf8",
)

describe("isPlatformOperatorStandalonePath", () => {
    it("allows the three iframe standalone pages and dashboard editor subpath", () => {
        expect(isPlatformOperatorStandalonePath("/standalone/dashboard")).toBe(true)
        expect(isPlatformOperatorStandalonePath("/standalone/dashboard/abc")).toBe(true)
        expect(isPlatformOperatorStandalonePath("/standalone/knowledge-tag-library")).toBe(true)
        expect(isPlatformOperatorStandalonePath("/standalone/content-security")).toBe(true)
        expect(
            isPlatformOperatorStandalonePath("/platform/standalone/dashboard", "/platform"),
        ).toBe(true)
        expect(isPlatformOperatorStandalonePath("/standalone/dashboard/")).toBe(true)
    })

    it("rejects approval/sys/log standalone, shelled admin pages, and substring traps", () => {
        expect(isPlatformOperatorStandalonePath("/standalone/approval")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/standalone/sys")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/standalone/log")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/standalone/log/chatlog/1/2/3")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/sys")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/dashboard")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/log")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/admin")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/standalone")).toBe(false)
        expect(isPlatformOperatorStandalonePath("/standalone/dashboard-evil")).toBe(false)
        expect(isStandalonePath("/standalone/approval")).toBe(true)
        expect(isStandalonePath("/dashboard")).toBe(false)
    })
})

describe("resolveNoAdminConsoleAction", () => {
    it("stays on whitelist standalone, 403s other standalone, kicks shelled admin", () => {
        expect(resolveNoAdminConsoleAction("/standalone/dashboard")).toBe("allow-standalone")
        expect(resolveNoAdminConsoleAction("/standalone/content-security")).toBe("allow-standalone")
        expect(resolveNoAdminConsoleAction("/standalone/approval")).toBe("standalone-403")
        expect(resolveNoAdminConsoleAction("/standalone/sys")).toBe("standalone-403")
        expect(resolveNoAdminConsoleAction("/dashboard")).toBe("kick")
        expect(resolveNoAdminConsoleAction("/sys")).toBe("kick")
        expect(resolveNoAdminConsoleAction("/admin")).toBe("kick")
    })

    it("userContext skips the workspace kick using the resolver", () => {
        expect(userContextSource).toMatch(/resolveNoAdminConsoleAction\(/)
        expect(userContextSource).toMatch(/allow-standalone/)
        expect(userContextSource).toMatch(/standalone-403/)
    })
})
