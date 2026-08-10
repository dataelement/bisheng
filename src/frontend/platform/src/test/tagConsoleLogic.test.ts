/**
 * F079 T017: pure logic behind the tag console.
 *
 * Deliberately imports no components — the local jsdom setup needs a compiled
 * `canvas` native module, and without it the whole vitest run dies before any
 * assertion. These functions carry the rules that are easy to get wrong, so
 * keeping them component-free keeps them runnable everywhere.
 */

import { describe, expect, it } from "vitest"

import {
    buildSearchParams,
    buildTagFileDetailUrl,
    canBatch,
    EMPTY_FILTERS,
    INITIAL_SELECTION,
    reviewRequestStatus,
    selectLibrary,
    selectReviewEntry,
    type TagConsoleFilterState,
} from "@/pages/BuildPage/bench/standalone/tagConsole/tagConsoleTypes"

describe("left panel selection", () => {
    it("selecting a library toggles it and stays in library mode", () => {
        const first = selectLibrary(INITIAL_SELECTION, 10)
        expect(first).toEqual({ mode: "library", selectedLibraryIds: [10] })

        const second = selectLibrary(first, 20)
        expect(second.selectedLibraryIds).toEqual([10, 20])

        const deselected = selectLibrary(second, 10)
        expect(deselected.selectedLibraryIds).toEqual([20])
    })

    it("the pending entry clears library selection", () => {
        const withLibraries = selectLibrary(selectLibrary(INITIAL_SELECTION, 10), 20)

        const review = selectReviewEntry()

        expect(review).toEqual({ mode: "review", selectedLibraryIds: [] })
        expect(withLibraries.selectedLibraryIds).toEqual([10, 20])
    })

    it("picking a library while in review mode returns to library mode", () => {
        const back = selectLibrary(selectReviewEntry(), 10)

        expect(back.mode).toBe("library")
        expect(back.selectedLibraryIds).toEqual([10])
    })
})

describe("buildSearchParams", () => {
    it("omits blank filters so the backend never receives empty strings", () => {
        const params = buildSearchParams(EMPTY_FILTERS, 1, 20)

        expect(params).toEqual({ page: 1, page_size: 20 })
    })

    it("keeps a one-sided date range", () => {
        const filters: TagConsoleFilterState = { ...EMPTY_FILTERS, createTimeStart: "2026-08-01" }

        const params = buildSearchParams(filters, 2, 50)

        expect(params.create_time_start).toBe("2026-08-01")
        expect(params.create_time_end).toBeUndefined()
        expect(params).toMatchObject({ page: 2, page_size: 50 })
    })

    it("trims the tag name and converts user ids to numbers", () => {
        const filters: TagConsoleFilterState = {
            ...EMPTY_FILTERS,
            tagName: "  结垢  ",
            submitter: { id: "101", name: "张三" },
            reviewer: { id: "103", name: "李四" },
        }

        const params = buildSearchParams(filters, 1, 20)

        expect(params.tag_name).toBe("结垢")
        expect(params.submitter_id).toBe(101)
        expect(params.reviewer_id).toBe(103)
    })
})

describe("buildTagFileDetailUrl", () => {
    const file = { file_id: 88, file_name: "热轧水处理.docx", knowledge_id: 12, parent_id: 3 }

    it("carries space, file, name and parent folder", () => {
        const url = buildTagFileDetailUrl(file)

        expect(url).toContain("/knowledge-portal?")
        expect(url).toContain("spaceId=12")
        expect(url).toContain("fileId=88")
        expect(url).toContain("folderId=3")
        expect(decodeURIComponent(url as string)).toContain("fileName=热轧水处理.docx")
    })

    it("omits folderId at the space root", () => {
        const url = buildTagFileDetailUrl({ ...file, parent_id: null })

        expect(url).not.toContain("folderId")
    })

    it("returns null when a required part is missing, so the caller can render plain text", () => {
        expect(buildTagFileDetailUrl({ ...file, file_id: 0 })).toBeNull()
        expect(buildTagFileDetailUrl({ ...file, knowledge_id: 0 })).toBeNull()
        expect(buildTagFileDetailUrl({ ...file, file_name: "   " })).toBeNull()
    })
})

describe("canBatch", () => {
    const pending = { name: "结垢", resource_type: "ai_auto_tag", status: "pending" } as any
    const rejected = { name: "翘曲", resource_type: "ai_auto_tag", status: "rejected" } as any

    it("needs a selection", () => {
        expect(canBatch("delete", [])).toBe(false)
        expect(canBatch("approve", [])).toBe(false)
    })

    it("library-mode actions do not care about review status", () => {
        expect(canBatch("delete", [pending])).toBe(true)
        expect(canBatch("move", [pending])).toBe(true)
    })

    it("rejected entries are read-only, so approve and reject are blocked", () => {
        expect(canBatch("approve", [pending])).toBe(true)
        expect(canBatch("reject", [pending])).toBe(true)
        expect(canBatch("approve", [pending, rejected])).toBe(false)
        expect(canBatch("reject", [rejected])).toBe(false)
    })

    it("approved entries are read-only too", () => {
        const approved = { name: "剥落", resource_type: "manual_tag", status: "approved" } as any
        expect(canBatch("approve", [approved])).toBe(false)
        expect(canBatch("reject", [approved])).toBe(false)
    })
})

describe("reviewRequestStatus", () => {
    it("pins the pending tab to pending, whatever the status field holds", () => {
        expect(reviewRequestStatus("pending", "")).toBe("pending")
        expect(reviewRequestStatus("pending", "rejected")).toBe("pending")
    })

    it("asks for both outcomes when the reviewed tab has no status picked", () => {
        expect(reviewRequestStatus("reviewed", "")).toBe("reviewed")
    })

    it("narrows the reviewed tab to one outcome", () => {
        expect(reviewRequestStatus("reviewed", "approved")).toBe("approved")
        expect(reviewRequestStatus("reviewed", "rejected")).toBe("rejected")
    })
})
