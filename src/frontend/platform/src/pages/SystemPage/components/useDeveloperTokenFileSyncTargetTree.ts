import {
  DeveloperTokenFileSyncTargetFolderOption,
  getDeveloperTokenFileSyncTargetChildrenApi,
} from "@/controllers/API/developerToken"
import { useCallback, useEffect, useRef, useState } from "react"

interface FolderBranch {
  items: DeveloperTokenFileSyncTargetFolderOption[]
  loading: boolean
  error: boolean
  expanded: boolean
  hasMore: boolean
  nextCursor: string | null
}

interface TargetTreeScope {
  tenantId: number
  userId: number
}

const PAGE_SIZE = 50

function branchKey(knowledgeId: number, parentId?: number): string {
  return `${knowledgeId}:${parentId ?? 0}`
}

export default function useDeveloperTokenFileSyncTargetTree({
  tenantId,
  userId,
}: TargetTreeScope) {
  const [branches, setBranches] = useState<Record<string, FolderBranch>>({})
  const generationRef = useRef(0)
  const controllersRef = useRef(new Map<string, AbortController>())

  useEffect(() => {
    generationRef.current += 1
    controllersRef.current.forEach((controller) => controller.abort())
    controllersRef.current.clear()
    setBranches({})
  }, [tenantId, userId])

  useEffect(() => () => {
    controllersRef.current.forEach((controller) => controller.abort())
  }, [])

  const loadBranch = useCallback(async (
    knowledgeId: number,
    parentId?: number,
    cursor?: string,
  ) => {
    const key = branchKey(knowledgeId, parentId)
    const generation = generationRef.current
    controllersRef.current.get(key)?.abort()
    const controller = new AbortController()
    controllersRef.current.set(key, controller)
    setBranches((current) => ({
      ...current,
      [key]: {
        items: cursor ? current[key]?.items || [] : [],
        loading: true,
        error: false,
        expanded: true,
        hasMore: current[key]?.hasMore || false,
        nextCursor: current[key]?.nextCursor || null,
      },
    }))
    try {
      const page = await getDeveloperTokenFileSyncTargetChildrenApi({
        tenant_id: tenantId,
        user_id: userId,
        knowledge_id: knowledgeId,
        parent_id: parentId,
        cursor,
        page_size: PAGE_SIZE,
        signal: controller.signal,
      })
      if (controller.signal.aborted || generation !== generationRef.current) return
      setBranches((current) => ({
        ...current,
        [key]: {
          items: cursor
            ? mergeFolders(current[key]?.items || [], page.data)
            : page.data,
          loading: false,
          error: false,
          expanded: true,
          hasMore: page.has_more,
          nextCursor: page.next_cursor,
        },
      }))
    } catch {
      if (controller.signal.aborted || generation !== generationRef.current) return
      setBranches((current) => ({
        ...current,
        [key]: {
          items: current[key]?.items || [],
          loading: false,
          error: true,
          expanded: true,
          hasMore: false,
          nextCursor: null,
        },
      }))
    } finally {
      if (controllersRef.current.get(key) === controller) {
        controllersRef.current.delete(key)
      }
    }
  }, [tenantId, userId])

  const toggleBranch = useCallback((knowledgeId: number, parentId?: number) => {
    const key = branchKey(knowledgeId, parentId)
    const branch = branches[key]
    if (!branch) {
      void loadBranch(knowledgeId, parentId)
      return
    }
    setBranches((current) => ({
      ...current,
      [key]: { ...current[key], expanded: !current[key].expanded },
    }))
  }, [branches, loadBranch])

  const loadMore = useCallback((knowledgeId: number, parentId?: number) => {
    const branch = branches[branchKey(knowledgeId, parentId)]
    if (!branch?.nextCursor || branch.loading) return
    void loadBranch(knowledgeId, parentId, branch.nextCursor)
  }, [branches, loadBranch])

  return {
    branches,
    getBranch: (knowledgeId: number, parentId?: number) => branches[branchKey(knowledgeId, parentId)],
    toggleBranch,
    loadMore,
  }
}

function mergeFolders(
  current: DeveloperTokenFileSyncTargetFolderOption[],
  incoming: DeveloperTokenFileSyncTargetFolderOption[],
): DeveloperTokenFileSyncTargetFolderOption[] {
  const merged = new Map(current.map((item) => [item.id, item]))
  incoming.forEach((item) => merged.set(item.id, item))
  return Array.from(merged.values())
}
