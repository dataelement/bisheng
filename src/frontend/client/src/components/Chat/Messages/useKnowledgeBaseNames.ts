import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { getSpaceInfoApi } from "~/api/knowledge";
import { useGetOrgToolList } from "~/hooks/queries/data-provider";

/**
 * Names for knowledge base ids nobody has named yet (they returned no chunk and
 * are not in the user's current selection), looked up by id:
 *  - document knowledge bases from the organisation list, one cached request;
 *  - knowledge spaces from /knowledge/space/{id}/info, one cached request per id.
 * Both kinds share one id space, so an id the organisation list does not know
 * is tried as a space. A lookup that fails (no access, deleted) just leaves the
 * id unnamed, as before.
 */
export function useKnowledgeBaseNames(ids: string[], enabled: boolean): Record<string, string> {
    const idsKey = ids.join(",");
    const active = enabled && ids.length > 0;

    const { data: orgList } = useGetOrgToolList(
        { page: 1, page_size: 200, action: "use" },
        { enabled: active },
    );

    const orgNames = useMemo(() => {
        const map: Record<string, string> = {};
        for (const kb of (orgList as { id?: string | number; name?: string }[] | undefined) ?? []) {
            if (kb?.id !== undefined && kb?.name) map[String(kb.id)] = kb.name;
        }
        return map;
    }, [orgList]);

    // Only ids the organisation list does not name are tried as spaces. Wait for
    // the list first so a document knowledge base never triggers a space lookup.
    const spaceIds = useMemo(
        () => (active && orgList ? ids.filter((id) => !orgNames[id]) : []),
        // eslint-disable-next-line react-hooks/exhaustive-deps -- idsKey stands for ids
        [active, orgList, orgNames, idsKey],
    );
    const spaceResults = useQueries({
        queries: spaceIds.map((id) => ({
            queryKey: ["KnowledgeBaseName", "space", id],
            queryFn: async () => (await getSpaceInfoApi(id)).name as string,
            staleTime: Infinity,
            retry: false,
            refetchOnWindowFocus: false,
        })),
    });

    return useMemo(() => {
        const names = { ...orgNames };
        spaceIds.forEach((id, i) => {
            const name = spaceResults[i]?.data;
            if (name) names[id] = name;
        });
        return names;
        // eslint-disable-next-line react-hooks/exhaustive-deps -- spaceResults changes identity each render
    }, [orgNames, spaceIds, spaceResults.map((r) => r.data ?? "").join("|")]);
}
