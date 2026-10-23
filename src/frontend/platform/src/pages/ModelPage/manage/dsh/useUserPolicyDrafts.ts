import { useCallback, useEffect, useRef, useState } from 'react'
import {
    getDshOperation,
    isDshRequestRejected,
    isDshSeatLimitReached,
    saveDshPolicy,
} from '@/controllers/API/dsh'
import type { DshModelUserPermission, DshOperation } from '@/types/dsh'
import { createDshOperationId } from '@/util/dshOperationId'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import type { PolicyDraft } from './SubjectPolicyControls'

type Entry = {
    saved: DshModelUserPermission
    draft: PolicyDraft
    operationId: string | null
    operationVersion: number
}
type Entries = Record<number, Entry>
export const userDraftOf = (item: DshModelUserPermission): PolicyDraft => ({
    enabled: item.direct_enabled,
    limit: String(item.direct_enabled ? item.direct_monthly_token_limit : 0),
})
export const validUserDraft = (draft: PolicyDraft) =>
    /^\d*$/.test(draft.limit) && Number.isSafeInteger(Number(draft.limit))
const dirty = (entry: Entry) =>
    !validUserDraft(entry.draft) || entry.draft.enabled !== entry.saved.direct_enabled ||
    Number(entry.draft.limit) !== Number(userDraftOf(entry.saved).limit)

// Keep transport waits bounded while retaining the original operation identity.
export async function withinSaveDeadline<T>(work: Promise<T>): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        return await Promise.race([
            work,
            new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new Error('DSH save response pending')), 10000)
            }),
        ])
    } finally {
        clearTimeout(timer)
    }
}

export async function resolveOperation(operationId: string, tenantId: number): Promise<DshOperation> {
    const abort = new AbortController()
    try {
        return await withinSaveDeadline(
            (async () => {
                while (!abort.signal.aborted) {
                    const result = await getDshOperation(operationId, String(tenantId), abort.signal)
                    if (result.status === 'SUCCEEDED' || result.status === 'FAILED') return result
                    await new Promise<void>((resolve) => {
                        const done = () => {
                            clearTimeout(timer)
                            abort.signal.removeEventListener('abort', done)
                            resolve()
                        }
                        const timer = setTimeout(done, 1000)
                        abort.signal.addEventListener('abort', done, { once: true })
                    })
                }
                throw new Error('DSH operation query expired')
            })(),
        )
    } finally {
        abort.abort()
    }
}

export function useUserPolicyDrafts(
    modelId: number | undefined,
    onReload: (item: DshModelUserPermission) => Promise<DshModelUserPermission>,
) {
    const entriesRef = useRef<Entries>({})
    const [entries, setEntries] = useState<Entries>({})
    const generation = useRef(0)
    const busy = useRef(false)
    const update = useCallback((next: Entries) => {
        entriesRef.current = next
        setEntries(next)
    }, [])

    useEffect(() => {
        generation.current += 1
        busy.current = false
        update({})
        return () => {
            generation.current += 1
        }
    }, [modelId, update])

    const remember = useCallback(
        (items: DshModelUserPermission[]) => {
            const next = { ...entriesRef.current }
            for (const item of items) {
                const existing = next[item.user_id]
                if (existing && (dirty(existing) || existing.operationId)) continue
                next[item.user_id] = {
                    saved: item,
                    draft: userDraftOf(item),
                    operationId: item.direct_pending_operation_id,
                    operationVersion: item.direct_version,
                }
            }
            update(next)
        },
        [update],
    )

    function change(item: DshModelUserPermission, patch: Partial<PolicyDraft>) {
        if (busy.current) return
        const previous = entriesRef.current[item.user_id] ?? {
            saved: item,
            draft: userDraftOf(item),
            operationId: item.direct_pending_operation_id,
            operationVersion: item.direct_version,
        }
        if (previous.operationId) return
        const draft = { ...previous.draft, ...patch }
        update({
            ...entriesRef.current,
            [item.user_id]: { ...previous, draft },
        })
    }

    async function save(tenantId: number): Promise<boolean> {
        if (modelId === undefined || busy.current) return false
        const candidates = Object.values(entriesRef.current).filter(
            (entry) => dirty(entry) || entry.operationId,
        )
        if (candidates.some((entry) => !validUserDraft(entry.draft))) return false
        const currentGeneration = generation.current
        busy.current = true
        const setEntry = (entry: Entry) => {
            if (generation.current === currentGeneration) {
                update({ ...entriesRef.current, [entry.saved.user_id]: entry })
            }
        }
        const saveEntry = async (candidate: Entry): Promise<boolean> => {
            if (generation.current !== currentGeneration) return false
            let entry = { ...candidate }
            let result: DshOperation
            if (!entry.operationId) {
                entry = {
                    ...entry,
                    operationId: createDshOperationId(),
                    operationVersion: entry.saved.direct_version + 1,
                }
                setEntry(entry)
                try {
                    result = await withinSaveDeadline(
                        saveDshPolicy(String(entry.saved.user_id), modelId, String(tenantId), {
                            operation_id: entry.operationId!,
                            expected_version: entry.saved.direct_version,
                            enabled: entry.draft.enabled,
                            monthly_token_limit: Number(entry.draft.limit),
                        }),
                    )
                } catch (failure) {
                    if (isDshRequestRejected(failure) || isDshSeatLimitReached(failure)) {
                        setEntry({ ...entry, operationId: null })
                        throw failure
                    }
                    if (getDshRequestErrorKey(failure)) throw failure
                    return false
                }
            } else {
                try {
                    result = await resolveOperation(entry.operationId, tenantId)
                } catch (failure) {
                    if (getDshRequestErrorKey(failure)) throw failure
                    return false
                }
            }
            if (result.status !== 'SUCCEEDED' && result.status !== 'FAILED') {
                try {
                    result = await resolveOperation(entry.operationId!, tenantId)
                } catch (failure) {
                    if (getDshRequestErrorKey(failure)) throw failure
                    return false
                }
            }
            if (generation.current !== currentGeneration) return false
            if (result.status === 'FAILED') {
                setEntry({ ...entry, operationId: null })
                throw Object.assign(new Error('DSH policy save failed'), { code: result.result_code })
            }
            try {
                const saved = await withinSaveDeadline(onReload(entry.saved))
                if (saved.direct_pending_operation_id) return false
                if (saved.direct_version < entry.operationVersion) return false
                setEntry({
                    saved,
                    draft: userDraftOf(saved),
                    operationId: null,
                    operationVersion: saved.direct_version,
                })
            } catch (failure) {
                if (getDshRequestErrorKey(failure)) throw failure
                return false
            }
            return true
        }
        try {
            let next = 0
            let complete = true
            const failures: unknown[] = []
            // Independent users progress concurrently; keep server load bounded.
            await Promise.all(
                Array.from({ length: Math.min(3, candidates.length) }, async () => {
                    while (next < candidates.length && generation.current === currentGeneration) {
                        const candidate = candidates[next++]
                        try {
                            if (!(await saveEntry(candidate))) complete = false
                        } catch (failure) {
                            complete = false
                            failures.push(failure)
                        }
                    }
                }),
            )
            if (failures.length) throw failures[0]
            return complete && generation.current === currentGeneration
        } finally {
            if (generation.current === currentGeneration) busy.current = false
        }
    }

    async function refresh() {
        for (const entry of Object.values(entriesRef.current)) {
            if (!dirty(entry) || entry.operationId) continue
            const saved = await withinSaveDeadline(onReload(entry.saved))
            update({
                ...entriesRef.current,
                [saved.user_id]: { ...entry, saved, operationId: saved.direct_pending_operation_id },
            })
        }
    }

    return {
        entries,
        remember,
        change,
        save,
        refresh,
        hasChanges: Object.values(entries).some(dirty),
        hasPending: Object.values(entries).some((entry) => Boolean(entry.operationId)),
        valid: Object.values(entries).every((entry) => validUserDraft(entry.draft)),
    }
}
