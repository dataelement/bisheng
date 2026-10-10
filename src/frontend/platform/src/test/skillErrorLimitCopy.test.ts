import { describe, expect, it } from "vitest"

import { getSkillErrorMessage } from "@/components/LinSight/skill/skillErrors"
import type { SkillUploadLimit } from "@/controllers/API/linsight"

// Minimal i18next stand-in: renders the placeholders the way the real copy does and
// leaves an unfilled one visible, which is exactly the defect being guarded against.
function t(key: string, options?: Record<string, unknown>): string {
    const copy: Record<string, string> = {
        "skillManage.errors.tooLarge": "file exceeds {{size}}MB",
        "skillManage.errors.bundleTooLarge": "unpacked exceeds {{unpacked}}MB",
    }
    const template = copy[key] ?? key
    return template.replace(/\{\{(\w+)\}\}/g, (raw, name: string) =>
        options && name in options ? String(options[name]) : raw)
}

const LIMIT: SkillUploadLimit = {
    max_size_bytes: 20 * 1024 * 1024,
    max_size_mb: 20,
    max_unpacked_bytes: 300 * 1024 * 1024,
    max_unpacked_mb: 300,
}

describe("skill size-limit error copy", () => {
    it("quotes the live unpacked cap for 11059 instead of a fixed number", () => {
        expect(getSkillErrorMessage({ status_code: 11059 }, t, LIMIT)).toBe("unpacked exceeds 300MB")
    })

    it("quotes the live upload cap for a server-side 11052", () => {
        expect(getSkillErrorMessage({ status_code: 11052 }, t, LIMIT)).toBe("file exceeds 20MB")
    })

    it("still maps codes for callers that have no limit to pass", () => {
        expect(getSkillErrorMessage({ status_code: 11053 }, t)).toBe("skillManage.errors.notFound")
    })
})
