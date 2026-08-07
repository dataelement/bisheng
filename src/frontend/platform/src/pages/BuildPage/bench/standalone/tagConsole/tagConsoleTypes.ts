import type {
    TagConsoleFilterParams,
    TagConsoleItem,
    TagConsoleReviewItem,
    TagConsoleReviewStatus,
    TagConsoleSourceFile,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { getWorkspaceClientUrl } from "@/utils/workspaceUrl"

/** Which table the right panel is showing. */
export type TagConsoleMode = "library" | "review"

/** Draft state of the filter bar, before it is turned into request params. */
export interface TagConsoleFilterState {
    tagName: string
    resourceType: string
    submitterId: string
    reviewerId: string
    createTimeStart: string
    createTimeEnd: string
    reviewTimeStart: string
    reviewTimeEnd: string
    /** Review mode only; empty string means "both". */
    status: TagConsoleReviewStatus | ""
}

export const EMPTY_FILTERS: TagConsoleFilterState = {
    tagName: "",
    resourceType: "",
    submitterId: "",
    reviewerId: "",
    createTimeStart: "",
    createTimeEnd: "",
    reviewTimeStart: "",
    reviewTimeEnd: "",
    status: "",
}

export const RESOURCE_TYPES = ["system_tag", "manual_tag", "ai_auto_tag"] as const

export interface TagConsoleSelection {
    mode: TagConsoleMode
    selectedLibraryIds: number[]
}

export const INITIAL_SELECTION: TagConsoleSelection = { mode: "library", selectedLibraryIds: [] }

/**
 * Click a tag library: toggles it, and always lands in library mode.
 *
 * Libraries and the pending-review entry are alternative data sources rather
 * than filters that stack, so picking a library leaves review mode.
 */
export function selectLibrary(state: TagConsoleSelection, libraryId: number): TagConsoleSelection {
    const selected = state.selectedLibraryIds.includes(libraryId)
        ? state.selectedLibraryIds.filter((id) => id !== libraryId)
        : [...state.selectedLibraryIds, libraryId]
    return { mode: "library", selectedLibraryIds: selected }
}

/** Click the fixed "pending review" entry: enters review mode, clears libraries. */
export function selectReviewEntry(): TagConsoleSelection {
    return { mode: "review", selectedLibraryIds: [] }
}

/** Drop empty values so the backend does not receive `""` as a real filter. */
export function buildSearchParams(
    filters: TagConsoleFilterState,
    page: number,
    pageSize: number,
): TagConsoleFilterParams {
    const params: TagConsoleFilterParams = { page, page_size: pageSize }
    if (filters.tagName.trim()) params.tag_name = filters.tagName.trim()
    if (filters.resourceType) params.resource_type = filters.resourceType
    if (filters.submitterId) params.submitter_id = Number(filters.submitterId)
    if (filters.reviewerId) params.reviewer_id = Number(filters.reviewerId)
    if (filters.createTimeStart) params.create_time_start = filters.createTimeStart
    if (filters.createTimeEnd) params.create_time_end = filters.createTimeEnd
    if (filters.reviewTimeStart) params.review_time_start = filters.reviewTimeStart
    if (filters.reviewTimeEnd) params.review_time_end = filters.reviewTimeEnd
    return params
}

/**
 * Portal deep link for a source file, opened in a new tab.
 *
 * Same shape the workbench pending-review section builds, including the parent
 * folder so the portal opens the containing folder before previewing. Opening in
 * a new tab also keeps the preview out of the iframe when this page is embedded.
 * Returns null when any required part is missing, so the caller can fall back to
 * plain text instead of rendering a broken link.
 */
export function buildTagFileDetailUrl(resource: TagConsoleSourceFile): string | null {
    const fileId = resource?.file_id
    const spaceId = resource?.knowledge_id
    const fileName = resource?.file_name?.trim()
    if (!fileId || !spaceId || !fileName) return null

    const params = new URLSearchParams()
    params.set("spaceId", String(spaceId))
    params.set("fileId", String(fileId))
    params.set("fileName", fileName)
    const folderId = resource.parent_id
    if (folderId !== undefined && folderId !== null && String(folderId) !== "") {
        params.set("folderId", String(folderId))
    }
    return getWorkspaceClientUrl(`/knowledge-portal?${params.toString()}`)
}

export type BatchAction = "delete" | "move" | "approve" | "reject"

/**
 * Whether a batch action applies to the current selection.
 *
 * Rejected entries are read-only this release, so they take part in neither
 * approve nor reject.
 */
export function canBatch(action: BatchAction, selected: (TagConsoleItem | TagConsoleReviewItem)[]): boolean {
    if (!selected.length) return false
    if (action === "delete" || action === "move") return true
    return selected.every((row) => (row as TagConsoleReviewItem).status === "pending")
}

/** Tag rows carry a review status only in review mode. */
export function isRejected(row: TagConsoleItem | TagConsoleReviewItem): boolean {
    return (row as TagConsoleReviewItem).status === "rejected"
}

export function formatDateTime(value?: string | null): string {
    if (!value) return "-"
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return "-"
    const pad = (num: number) => String(num).padStart(2, "0")
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
