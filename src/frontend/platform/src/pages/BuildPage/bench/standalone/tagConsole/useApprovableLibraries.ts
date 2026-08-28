import {
    getKnowledgeSpaceTagLibrariesApi,
    type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { useEffect, useState } from "react"

/**
 * Libraries a pending tag can be approved into.
 *
 * Approval no longer requires the target library to already be bound to the
 * source knowledge space — the backend binds in-scope sources on success.
 * Offer every public library in the tenant.
 */
export function useApprovableLibraries(_spaceIds?: number[]) {
    const [libraries, setLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([])
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: 500 })
            .then((res) => {
                if (cancelled) return
                setLibraries(res?.data || [])
            })
            .catch(() => {
                if (!cancelled) setLibraries([])
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })
        return () => {
            cancelled = true
        }
    }, [])

    return { libraries, loading }
}

/** Libraries present in every space's list, keeping the first list's order. */
export function intersectLibraries(
    perSpace: KnowledgeSpaceTagLibraryListItem[][],
): KnowledgeSpaceTagLibraryListItem[] {
    if (!perSpace.length) return []
    const [first, ...rest] = perSpace
    return (first || []).filter((library) =>
        rest.every((others) => (others || []).some((other) => other.id === library.id)),
    )
}

/** Distinct knowledge bases the given rows were proposed from. */
export function distinctSourceSpaceIds(rows: { source_files?: { knowledge_id: number }[] }[]): number[] {
    const seen: number[] = []
    for (const row of rows || []) {
        for (const file of row.source_files || []) {
            if (file.knowledge_id && !seen.includes(file.knowledge_id)) seen.push(file.knowledge_id)
        }
    }
    return seen.sort((a, b) => a - b)
}
