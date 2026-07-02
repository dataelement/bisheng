import { useCallback, useEffect, useMemo, type Dispatch, type SetStateAction } from "react";
import { useQuery } from "@tanstack/react-query";
import {
    getCreateSpaceOptionsApi,
    getSpacesByLevelApi,
    SpaceLevel,
    SpaceRole,
    SpaceSortType,
    type KnowledgeSpace,
} from "~/api/knowledge";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../../hooks/useKnowledgeSpacePermissions";
import { GROUP_ICON_SRC } from "../constants";
import type { SpaceGroup } from "../types";

interface UsePortalSpacesParams {
    activeSpace: KnowledgeSpace | null;
    setActiveSpace: Dispatch<SetStateAction<KnowledgeSpace | null>>;
    preferredSpaceId?: string;
}

function findDefaultPersonalSpace(spaces: KnowledgeSpace[]): KnowledgeSpace | null {
    return spaces.find((space) => space.isFavorite) ?? spaces[0] ?? null;
}

export function usePortalSpaces({ activeSpace, setActiveSpace, preferredSpaceId }: UsePortalSpacesParams) {
    const personalSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.PERSONAL],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.PERSONAL, { order_by: SpaceSortType.UPDATE_TIME }),
        placeholderData: (prev) => prev,
    });

    const silentGroupQueriesEnabled = personalSpacesQuery.isFetched || personalSpacesQuery.isError;
    const publicSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.PUBLIC],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.PUBLIC, { order_by: SpaceSortType.UPDATE_TIME }),
        enabled: silentGroupQueriesEnabled,
        placeholderData: (prev) => prev,
    });
    const departmentSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.DEPARTMENT],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.DEPARTMENT, { order_by: SpaceSortType.UPDATE_TIME }),
        enabled: silentGroupQueriesEnabled,
        placeholderData: (prev) => prev,
    });
    const teamSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.TEAM],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.TEAM, { order_by: SpaceSortType.UPDATE_TIME }),
        enabled: silentGroupQueriesEnabled,
        placeholderData: (prev) => prev,
    });

    const {
        data: createOptions,
        isLoading: createOptionsLoading,
    } = useQuery({
        queryKey: ["knowledgeSpaces", "createOptions"],
        queryFn: getCreateSpaceOptionsApi,
    });

    const groups = useMemo<SpaceGroup[]>(() => {
        return [
            {
                key: "public",
                title: "公共知识库",
                level: SpaceLevel.PUBLIC,
                iconSrc: GROUP_ICON_SRC.public,
                spaces: publicSpacesQuery.data ?? [],
                loading: !silentGroupQueriesEnabled || publicSpacesQuery.isLoading,
            },
            {
                key: "department",
                title: "部门知识库",
                level: SpaceLevel.DEPARTMENT,
                iconSrc: GROUP_ICON_SRC.department,
                spaces: departmentSpacesQuery.data ?? [],
                loading: !silentGroupQueriesEnabled || departmentSpacesQuery.isLoading,
            },
            {
                key: "team",
                title: "团队知识库",
                level: SpaceLevel.TEAM,
                iconSrc: GROUP_ICON_SRC.team,
                spaces: teamSpacesQuery.data ?? [],
                loading: !silentGroupQueriesEnabled || teamSpacesQuery.isLoading,
            },
            {
                key: "personal",
                title: "个人知识库",
                level: SpaceLevel.PERSONAL,
                iconSrc: GROUP_ICON_SRC.personal,
                spaces: personalSpacesQuery.data ?? [],
                loading: personalSpacesQuery.isLoading,
            },
        ];
    }, [
        departmentSpacesQuery.data,
        departmentSpacesQuery.isLoading,
        personalSpacesQuery.data,
        personalSpacesQuery.isLoading,
        publicSpacesQuery.data,
        publicSpacesQuery.isLoading,
        silentGroupQueriesEnabled,
        teamSpacesQuery.data,
        teamSpacesQuery.isLoading,
    ]);

    const createPermissionByLevel = useMemo<Record<SpaceLevel, boolean>>(() => ({
        [SpaceLevel.PUBLIC]: Boolean(createOptions?.canCreatePublic),
        [SpaceLevel.DEPARTMENT]: Boolean(createOptions?.canCreateDepartment),
        [SpaceLevel.TEAM]: Boolean(createOptions?.canCreateTeam),
        [SpaceLevel.PERSONAL]: Boolean(createOptions?.canCreatePersonal),
    }), [createOptions]);

    const selectableSpaces = useMemo(
        () => groups.flatMap((group) => group.spaces),
        [groups],
    );
    const defaultPersonalSpace = useMemo(
        () => findDefaultPersonalSpace(personalSpacesQuery.data ?? []),
        [personalSpacesQuery.data],
    );
    const preferredSpace = useMemo(
        () => preferredSpaceId
            ? selectableSpaces.find((space) => String(space.id) === String(preferredSpaceId)) ?? null
            : null,
        [preferredSpaceId, selectableSpaces],
    );
    const preferredSpacePending = Boolean(
        preferredSpaceId
        && !preferredSpace
        && (
            personalSpacesQuery.isLoading
            || personalSpacesQuery.isFetching
            || !silentGroupQueriesEnabled
            || publicSpacesQuery.isLoading
            || publicSpacesQuery.isFetching
            || departmentSpacesQuery.isLoading
            || departmentSpacesQuery.isFetching
            || teamSpacesQuery.isLoading
            || teamSpacesQuery.isFetching
        ),
    );
    const spaceIds = useMemo(
        () => selectableSpaces.map((space) => space.id),
        [selectableSpaces],
    );
    const fullAccessSpaceIds = useMemo(
        () => selectableSpaces
            .filter((space) => space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN)
            .map((space) => space.id),
        [selectableSpaces],
    );
    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions(
        spaceIds,
        { fullAccessSpaceIds },
    );
    const activeGroup = useMemo(
        () => groups.find((group) => group.spaces.some((space) => space.id === activeSpace?.id)),
        [activeSpace?.id, groups],
    );

    const getSpacePermissions = useCallback((space: KnowledgeSpace) => {
        const hasFullAccess = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
        const hasPermission = (permissionId: "edit_space" | "delete_space" | "manage_space_relation") => (
            hasFullAccess || hasKnowledgeSpacePermission(spaceActionPermissions, space.id, permissionId)
        );
        const canManageMembers = space.spaceLevel === SpaceLevel.PERSONAL
            ? false
            : hasPermission("manage_space_relation");
        return {
            canEditSpace: hasPermission("edit_space"),
            canDeleteSpace: hasPermission("delete_space"),
            canManageMembers,
        };
    }, [spaceActionPermissions]);

    useEffect(() => {
        if (preferredSpace) {
            if (String(activeSpace?.id) !== String(preferredSpace.id)) {
                setActiveSpace(preferredSpace);
            }
            return;
        }
        if (preferredSpacePending) return;
        if (activeSpace && selectableSpaces.some((space) => space.id === activeSpace.id)) return;
        if (personalSpacesQuery.isLoading) return;
        setActiveSpace(defaultPersonalSpace ?? selectableSpaces[0] ?? null);
    }, [
        activeSpace,
        defaultPersonalSpace,
        personalSpacesQuery.isLoading,
        preferredSpace,
        preferredSpacePending,
        selectableSpaces,
        setActiveSpace,
    ]);

    return {
        groups,
        createOptionsLoading,
        createPermissionByLevel,
        selectableSpaces,
        spaceLoading: personalSpacesQuery.isLoading || preferredSpacePending,
        activeGroup,
        getSpacePermissions,
    };
}
