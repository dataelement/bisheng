import { getDshModelUserPermissions } from '@/controllers/API/dsh'
import type { DshModelUserPermissionPage } from '@/types/dsh'
import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
    type ReactNode,
} from 'react'
import type { useUserPolicyDrafts } from './useUserPolicyDrafts'

type Page = DshModelUserPermissionPage
type Entry = { page: Page | null; pending?: Promise<Page>; abort?: AbortController }
type MembersScope = { modelId: number; refresh: number; pages: Map<string, Entry> }
const MembersContext = createContext<MembersScope | null>(null)

interface AccessMembersProviderProps {
    modelId: number
    refresh: number
    children: ReactNode
}

export function AccessMembersProvider({ modelId, refresh, children }: AccessMembersProviderProps) {
    // Keep pages and in-flight reads for this dialog only. Saving invalidates them.
    const scope = useMemo(() => ({ modelId, refresh, pages: new Map<string, Entry>() }), [modelId, refresh])
    useEffect(
        () => () => {
            scope.pages.forEach((entry) => entry.abort?.abort())
            scope.pages.clear()
        },
        [scope],
    )
    return <MembersContext.Provider value={scope}>{children}</MembersContext.Provider>
}

export function useAccessMembers(
    modelId: number,
    departmentId: number | undefined,
    keyword: string | undefined,
    remember: ReturnType<typeof useUserPolicyDrafts>['remember'],
) {
    const scope = useContext(MembersContext)
    if (!scope) throw new Error('AccessMembersProvider is required')
    const cache = scope.pages
    const key = JSON.stringify([modelId, departmentId, keyword || ''])
    const [result, setResult] = useState<{ cache: typeof cache; key: string; page: Page | null }>(() => ({
        cache,
        key,
        page: cache.get(key)?.page ?? null,
    }))
    const page = result.key === key ? result.page : (cache.get(key)?.page ?? null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(false)
    const [retry, setRetry] = useState(0)
    const generation = useRef(0)

    const load = useCallback(
        async (append: boolean, current: number) => {
            const entry = cache.get(key) ?? { page: null }
            cache.set(key, entry)
            setError(false)
            if (entry.page && !append && !entry.pending) {
                remember(entry.page.items)
                setResult({ cache, key, page: entry.page })
                setLoading(false)
                return
            }
            setLoading(true)
            if (!entry.pending) {
                const abort = new AbortController()
                entry.abort = abort
                entry.pending = getDshModelUserPermissions(
                    modelId,
                    {
                        limit: 50,
                        include_seats: true,
                        membership: 'DIRECT',
                        ...(departmentId === 0 ? { unassigned_only: true } : { department_id: departmentId }),
                        keyword: keyword || undefined,
                        cursor: append ? (entry.page?.next_cursor ?? undefined) : undefined,
                    },
                    abort.signal,
                )
                    .then((next) => {
                        if (abort.signal.aborted) throw new Error('Member read cancelled')
                        entry.page = {
                            ...next,
                            items: append ? [...(entry.page?.items ?? []), ...next.items] : next.items,
                        }
                        return entry.page
                    })
                    .finally(() => {
                        entry.pending = undefined
                    })
            }
            try {
                const next = await entry.pending
                if (generation.current !== current) return
                remember(next.items)
                setResult({ cache, key, page: next })
            } catch {
                if (generation.current === current) setError(true)
            } finally {
                if (generation.current === current) setLoading(false)
            }
        },
        [cache, key, modelId, departmentId, keyword, remember],
    )

    useEffect(() => {
        const current = ++generation.current
        setLoading(!cache.get(key)?.page || Boolean(cache.get(key)?.pending))
        setError(false)
        const timer = setTimeout(() => void load(false, current), keyword ? 250 : 0)
        // Collapsing preserves the request; closing the dialog cancels it in the provider.
        return () => {
            clearTimeout(timer)
            generation.current += 1
        }
    }, [cache, key, keyword, retry, load])

    return {
        page,
        loading,
        error,
        retry: () => {
            cache.delete(key)
            setRetry((value) => value + 1)
        },
        more: () => {
            if (!loading && page?.has_more) void load(true, generation.current)
        },
    }
}

export function useDelayedMemberLoading(loading: boolean) {
    const [visible, setVisible] = useState(false)
    const shownAt = useRef(0)
    useEffect(() => {
        const timer = loading
            ? setTimeout(() => {
                  shownAt.current = Date.now()
                  setVisible(true)
              }, 300)
            : setTimeout(() => setVisible(false), Math.max(0, 300 - (Date.now() - shownAt.current)))
        return () => clearTimeout(timer)
    }, [loading])
    return visible
}
