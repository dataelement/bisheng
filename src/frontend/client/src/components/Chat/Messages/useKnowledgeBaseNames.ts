import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getDepartmentSpacesApi, getJoinedSpacesApi, getMineSpacesApi } from "~/api/knowledge";
import { useGetOrgToolList } from "~/hooks/queries/data-provider";

type Named = { id?: string | number; name?: string };

const LOOKUP_STALE_MS = 5 * 60 * 1000;

/**
 * Names for knowledge base ids nobody has named yet (they returned no chunk and
 * are not in the user's current selection), taken from the lists the chat
 * knowledge picker already uses:
 *  - document knowledge bases from the organisation list;
 *  - knowledge spaces from mine + joined + department, merged.
 * Both kinds share one id space. The lists only hold what the user may use, so
 * an id they cannot see (no access, deleted) stays unnamed and its chip is
 * skipped. Two list requests serve every id, instead of one request per id.
 *
 * `enabled` is false on the share view; nothing is requested while every id is
 * already named. The lookup is cosmetic, so it never retries and a failing list
 * leaves the other lists usable.
 */
export function useKnowledgeBaseNames(ids: string[], enabled: boolean): Record<string, string> {
    const active = enabled && ids.length > 0;

    // Cached for a few minutes: every deep-thinking group mounts this hook, and
    // without a stale time each mount would refetch the whole list.
    const { data: orgList } = useGetOrgToolList(
        { page: 1, page_size: 200, action: "use" },
        { enabled: active, staleTime: LOOKUP_STALE_MS, refetchOnMount: false },
    );
    const orgNames = useMemo(() => toNameMap(orgList as Named[] | undefined), [orgList]);

    // Spaces are only needed for ids the organisation list does not name; wait
    // for the list so a document knowledge base never triggers the space calls.
    const needSpaces = active && !!orgList && ids.some((id) => !orgNames[id]);
    const { data: spaceNames } = useQuery({
        queryKey: ["KnowledgeBaseNames", "spaces"],
        queryFn: async () => {
            const lists = await Promise.allSettled([
                getMineSpacesApi(),
                getJoinedSpacesApi(),
                getDepartmentSpacesApi(),
            ]);
            return toNameMap(
                lists.flatMap((l) => (l.status === "fulfilled" ? (l.value as Named[]) : [])),
            );
        },
        enabled: needSpaces,
        staleTime: LOOKUP_STALE_MS,
        retry: false,
        refetchOnWindowFocus: false,
    });

    // `events` is a new array on every render (groupEventsForDisplay), so the ids
    // arrive with a new identity each time. Key on their content to keep the
    // returned map stable and avoid a render loop. The separator cannot occur in an id.
    const idsKey = ids.join("\u0000");
    return useMemo(() => {
        const names: Record<string, string> = {};
        for (const id of ids) {
            const name = orgNames[id] || spaceNames?.[id];
            if (name) names[id] = name;
        }
        return names;
        // eslint-disable-next-line react-hooks/exhaustive-deps -- idsKey stands for ids
    }, [idsKey, orgNames, spaceNames]);
}

function toNameMap(items: Named[] | undefined): Record<string, string> {
    const map: Record<string, string> = {};
    for (const item of items ?? []) {
        if (item?.id !== undefined && item?.name) map[String(item.id)] = item.name;
    }
    return map;
}
