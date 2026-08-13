import {
    getKnowledgeSpaceTagLibrariesByKnowledgeApi,
    type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { useEffect, useState } from "react"

/**
 * Libraries a set of pending tags can legally be approved into.
 *
 * Approving writes the tag into a library, and the backend refuses when that
 * library is not bound to the knowledge base the tag came from — the tag would
 * land somewhere its own knowledge base cannot draw from. The console spans
 * every knowledge base, so offering all libraries meant a batch could pick one
 * valid for none of the selection and fail on every row with
 * "该标签库未关联此知识空间".
 *
 * Only libraries bound to *every* selected tag's source is offered, since one
 * library is chosen for the whole batch. An empty result is meaningful, not an
 * error: the selection has no library in common and has to be split up.
 */
export function useApprovableLibraries(spaceIds: number[]) {
    const [libraries, setLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([])
    const [loading, setLoading] = useState(false)
    // Joined so the effect compares by value — a fresh array each render would
    // otherwise refetch forever.
    const key = spaceIds.join(",")

    useEffect(() => {
        const ids = key ? key.split(",").map(Number) : []
        if (!ids.length) {
            setLibraries([])
            return
        }
        let cancelled = false
        setLoading(true)
        Promise.all(ids.map((id) => getKnowledgeSpaceTagLibrariesByKnowledgeApi(id).catch(() => [])))
            .then((perSpace) => {
                if (cancelled) return
                setLibraries(intersectLibraries(perSpace))
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })
        return () => {
            cancelled = true
        }
    }, [key])

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
