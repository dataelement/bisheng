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
    sourceLibraryNames,
    selectLibrary,
    selectReviewEntry,
    selectBlacklistEntry,
    type TagConsoleFilterState,
} from "@/pages/BuildPage/bench/standalone/tagConsole/tagConsoleTypes"
import {
    distinctSourceSpaceIds,
    intersectLibraries,
} from "@/pages/BuildPage/bench/standalone/tagConsole/useApprovableLibraries"
import {
    isViolationFile,
    sensitiveViolationMessage,
    sensitiveViolationWords,
} from "@/util/sensitiveViolation"

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

    it("the blacklist entry clears library selection", () => {
        const withLibraries = selectLibrary(selectLibrary(INITIAL_SELECTION, 10), 20)

        const blacklist = selectBlacklistEntry()

        expect(blacklist).toEqual({ mode: "blacklist", selectedLibraryIds: [] })
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

    it("sends the source knowledge base as an id", () => {
        const filters: TagConsoleFilterState = {
            ...EMPTY_FILTERS,
            sourceKnowledge: { id: "109", name: "gzx0187的知识库" },
        }

        expect(buildSearchParams(filters, 1, 20).source_knowledge_id).toBe(109)
    })

    it("omits the source knowledge base when nothing is picked", () => {
        expect(buildSearchParams(EMPTY_FILTERS, 1, 20).source_knowledge_id).toBeUndefined()
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

describe("sourceLibraryNames", () => {
    const file = (knowledge_name: string | null, file_id = 1) =>
        ({ file_id, file_name: "a.docx", knowledge_id: 9, knowledge_name }) as any

    it("lists each knowledge base once, in order", () => {
        expect(sourceLibraryNames([file("热轧库"), file("冷轧库", 2), file("热轧库", 3)])).toEqual([
            "热轧库",
            "冷轧库",
        ])
    })

    it("drops files whose knowledge base is missing or blank", () => {
        expect(sourceLibraryNames([file(null), file("   ", 2), file("热轧库", 3)])).toEqual(["热轧库"])
    })

    it("survives a row with no source files", () => {
        expect(sourceLibraryNames([])).toEqual([])
        expect(sourceLibraryNames(undefined as any)).toEqual([])
    })
})

describe("approvable libraries", () => {
    const lib = (id: number, name = `lib${id}`) => ({ id, name }) as any

    it("keeps only libraries every source knowledge base is bound to", () => {
        const shared = intersectLibraries([
            [lib(1), lib(2), lib(3)],
            [lib(2), lib(3)],
            [lib(3), lib(9)],
        ])

        expect(shared.map((l) => l.id)).toEqual([3])
    })

    it("a single source keeps its whole list, in order", () => {
        expect(intersectLibraries([[lib(5), lib(1)]]).map((l) => l.id)).toEqual([5, 1])
    })

    it("no overlap means the batch has to be split, not an error", () => {
        expect(intersectLibraries([[lib(1)], [lib(2)]])).toEqual([])
        expect(intersectLibraries([])).toEqual([])
    })

    it("collects the distinct source knowledge bases of a selection", () => {
        const row = (...ids: number[]) => ({ source_files: ids.map((knowledge_id) => ({ knowledge_id })) })

        expect(distinctSourceSpaceIds([row(9, 3), row(3), row(1)])).toEqual([1, 3, 9])
        expect(distinctSourceSpaceIds([{ source_files: [] }, {}])).toEqual([])
    })
})

describe("sensitive violation", () => {
    // The real strings come from the knowledge namespace; a stub keeps this test
    // about the logic rather than about translation wiring.
    const t = (key: string) =>
        ({
            sensitiveViolationMessage: "GENERIC",
            sensitiveViolationMessagePrefix: "PREFIX",
            sensitiveViolationMessageSuffix: "SUFFIX",
        })[key] ?? key

    it("recognises only the content-safety status", () => {
        expect(isViolationFile({ status: 7 })).toBe(true)
        expect(isViolationFile({ status: 2 })).toBe(false)
        expect(isViolationFile({})).toBe(false)
    })

    it("pulls the hit words out, deduplicated", () => {
        const remark = JSON.stringify({ reason: "sensitive_check", hits: [{ word: "赌博" }, { word: "赌博" }, { word: "毒品" }] })
        expect(sensitiveViolationWords(remark)).toEqual(["赌博", "毒品"])
        expect(sensitiveViolationMessage(remark, t)).toBe("PREFIX{赌博,毒品}SUFFIX")
    })

    it("never renders a key when the knowledge namespace is missing", () => {
        // How i18next behaves for a namespace the page never loaded: no
        // translation, so it returns defaultValue if given and the key if not.
        // Without a default this rendered "sensitiveViolationMessagePrefix{21}
        // sensitiveViolationMessageSuffix" at the user.
        const missingNs = (key: string, options?: Record<string, any>) => options?.defaultValue ?? key
        const remark = JSON.stringify({ reason: "sensitive_check", hits: [{ word: "21" }] })

        const message = sensitiveViolationMessage(remark, missingNs)

        expect(message).not.toContain("sensitiveViolationMessage")
        expect(message).toContain("21")
        expect(sensitiveViolationMessage(null, missingNs)).not.toContain("sensitiveViolationMessage")
    })

    it("falls back to the generic sentence when there are no words to show", () => {
        expect(sensitiveViolationMessage(null, t)).toBe("GENERIC")
        expect(sensitiveViolationMessage("解析超时", t)).toBe("GENERIC")
        expect(sensitiveViolationMessage("{not json", t)).toBe("GENERIC")
        expect(sensitiveViolationMessage(JSON.stringify({ reason: "other" }), t)).toBe("GENERIC")
    })
})
