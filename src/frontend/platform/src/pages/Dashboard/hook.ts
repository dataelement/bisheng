
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { publishDashboard } from "@/controllers/API/dashboard";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { userContext } from "@/contexts/userContext";
import { useEditorDashboardStore } from "@/store/dashboardStore";
import { useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "react-query";

export const DashboardsQueryKey = "DashboardsQueryKey"
export const DashboardQueryKey = "DashboardQueryKey"
export const enum DashboardStatus {
    Draft = "draft",
    Published = "published",
}

export type DashboardPermissionMap = Record<string, string[]>

const dashboardPermissionRequests = new Map<string, Promise<string[]>>()

function getDashboardPermissionActions(
    userId: string,
    resourceId: string,
): Promise<string[]> {
    const key = JSON.stringify([userId, resourceId])
    const inFlight = dashboardPermissionRequests.get(key)
    if (inFlight) return inFlight

    const request = getMyResourcePermissionsApi("dashboard", resourceId)
        .then((summary) => Array.from(new Set(summary.actions)))
        .finally(() => {
            dashboardPermissionRequests.delete(key)
        })
    dashboardPermissionRequests.set(key, request)
    return request
}

/**
 * Resolve what the current user may do on each dashboard.
 *
 * A resource is visible exactly when its `my-permissions` request succeeded:
 * the endpoint checks visibility at its entrance and errors out otherwise. The
 * returned `actions` never carry "visible" — it is a relation in the permission
 * model, not one of the twelve business actions — so presence in the map, not
 * the action list, is the visibility signal.
 *
 * `privileged` short-circuits admins. The backend already waves them through on
 * identity alone, but that same shortcut means they hold no grant rows, so their
 * action list comes back empty and everything would read as forbidden.
 */
export function useDashboardPermissions(resourceIds: string[]): {
    permissions: DashboardPermissionMap
    loading: boolean
    privileged: boolean
} {
    const normalizedIds = useMemo(
        () => Array.from(new Set(resourceIds.map(String))).sort(),
        [resourceIds.join(",")],
    )
    const idsKey = normalizedIds.join(",")
    const { user } = useContext(userContext)
    const userId = user?.user_id == null ? "" : String(user.user_id)
    const privileged = user?.role === "admin"
    const [permissions, setPermissions] = useState<DashboardPermissionMap>({})
    // Starts true whenever a request is coming: the effect below cannot run
    // before the first render, and a consumer that reads an empty map while
    // `loading` is false concludes "forbidden" from an answer that has not been
    // asked for yet — which is how the editor bounced people to /404 on boards
    // they were allowed to edit.
    const [loading, setLoading] = useState(() => !privileged && normalizedIds.length > 0)

    useEffect(() => {
        if (privileged || !normalizedIds.length) {
            setPermissions({})
            setLoading(false)
            return
        }

        let cancelled = false
        setPermissions({})
        setLoading(true)
        void Promise.allSettled(
            normalizedIds.map(async (resourceId) => {
                const actions = await getDashboardPermissionActions(
                    userId,
                    resourceId,
                )
                return [resourceId, actions] as const
            }),
        ).then((results) => {
            if (cancelled) return
            const next: DashboardPermissionMap = {}
            for (const result of results) {
                if (result.status !== "fulfilled") continue
                const [resourceId, actions] = result.value
                next[resourceId] = actions
            }
            setPermissions(next)
            setLoading(false)
        })

        return () => {
            cancelled = true
        }
    }, [idsKey, userId, privileged])

    return { permissions, loading, privileged }
}

/**
 * Lazily resolve what the current user may do on a single dashboard.
 *
 * The dashboard list already decides visibility on the server, so the list no
 * longer front-loads a `my-permissions` request per row. This hook fetches the
 * per-resource action list on demand — call `ensureLoaded` the moment the user
 * reaches for an action (e.g. opens the item menu or double-clicks to rename).
 *
 * `privileged` short-circuits admins: the backend waves them through on identity
 * alone, so they hold no grant rows and their action list would read empty.
 * In-flight requests are de-duplicated across callers by `getDashboardPermission
 * Actions`, so hovering then opening the same item issues at most one request.
 */
export function useLazyDashboardPermission(resourceId: string): {
    actions: string[]
    loaded: boolean
    loading: boolean
    privileged: boolean
    ensureLoaded: () => void
} {
    const { user } = useContext(userContext)
    const userId = user?.user_id == null ? "" : String(user.user_id)
    const privileged = user?.role === "admin"
    const [actions, setActions] = useState<string[]>([])
    const [loaded, setLoaded] = useState(false)
    const [loading, setLoading] = useState(false)

    // A fresh dashboard id invalidates any previously resolved actions.
    useEffect(() => {
        setActions([])
        setLoaded(false)
        setLoading(false)
    }, [resourceId, userId])

    const ensureLoaded = useCallback(() => {
        if (privileged || loaded || loading || !resourceId) return
        setLoading(true)
        getDashboardPermissionActions(userId, String(resourceId))
            .then((resolved) => setActions(resolved))
            // A rejected my-permissions request means "no extra actions"; the
            // row is already visible because the server returned it.
            .catch(() => setActions([]))
            .finally(() => {
                setLoaded(true)
                setLoading(false)
            })
    }, [privileged, loaded, loading, userId, resourceId])

    return { actions, loaded, loading, privileged, ensureLoaded }
}

export const usePublishDashboard = () => {
    const queryClient = useQueryClient();
    const { toast } = useToast();
    const { t } = useTranslation("dashboard")

    const mutation = useMutation({
        mutationFn: ({ id, published }: { id: string; published: boolean }) =>
            publishDashboard(
                id,
                published ? DashboardStatus.Draft : DashboardStatus.Published
            ),
        onSuccess: (_, variables) => {
            const newStatus = variables.published ? DashboardStatus.Draft : DashboardStatus.Published
            queryClient.setQueryData([DashboardQueryKey, variables.id], (old: any) => {
                old.status = newStatus // Reduce render
                return old
            })
            queryClient.setQueryData([DashboardsQueryKey], (old: any) => {
                return old.map(el => el.id === variables.id ? {
                    ...el,
                    status: newStatus
                } : el);
            });
            toast({
                description: variables.published ? t('unpublishSuccess') : t('publishSuccess'),
                variant: "success"
            });
        },
        onError: (error) => {
            console.error("Publish Error:", error);
            toast({
                description: t('operationFailed'),
                variant: "error",
            });
        },
    });

    // publish function
    const handlePublish = (id: string, published: boolean) => {
        mutation.mutate({ id, published });
    };

    return {
        publish: handlePublish,
        publishAsync: (id: string, published: boolean) =>
            mutation.mutateAsync({ id, published }),
        isPublishing: mutation.isLoading,
        mutation,
    };
};

export const useEditorShortcuts = () => {
    const { undo, redo, history } = useEditorDashboardStore();

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            const isCtrlOrCmd = event.ctrlKey || event.metaKey;

            // Undo: Ctrl + Z
            if (isCtrlOrCmd && !event.shiftKey && event.key.toLowerCase() === 'z') {
                event.preventDefault();
                if (history.past.length > 0) undo();
            }

            // Redo: Ctrl + Shift + Z or Ctrl + Y
            if (
                (isCtrlOrCmd && event.shiftKey && event.key.toLowerCase() === 'z') ||
                (isCtrlOrCmd && event.key.toLowerCase() === 'y')
            ) {
                event.preventDefault();
                if (history.future.length > 0) redo();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [undo, redo, history.past.length, history.future.length]);
};
