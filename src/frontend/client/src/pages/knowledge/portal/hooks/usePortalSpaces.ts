import { useCallback, useEffect, useMemo, type Dispatch, type SetStateAction } from "react";
import { useQuery } from "@tanstack/react-query";
import {
    getCreateSpaceOptionsApi,
    getGroupedSpacesApi,
    SpaceLevel,
    SpaceRole,
    SpaceSortType,
    type KnowledgeSpace,
} from "~/api/knowledge";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
} from "../../hooks/useKnowledgeSpacePermissions";
import { EMPTY_GROUPED_SPACES, GROUP_ICON_SRC } from "../constants";
import type { SpaceGroup } from "../types";

interface UsePortalSpacesParams {
    activeSpace: KnowledgeSpace | null;
    setActiveSpace: Dispatch<SetStateAction<KnowledgeSpace | null>>;
}

export function usePortalSpaces({ activeSpace, setActiveSpace }: UsePortalSpacesParams) {
    const {
        data: groupedSpaces = EMPTY_GROUPED_SPACES,
        isLoading: spaceLoading,
    } = useQuery({
        queryKey: ["knowledgeSpaces", "grouped"],
        queryFn: () => getGroupedSpacesApi({ order_by: SpaceSortType.UPDATE_TIME }),
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
            { key: "public", title: "公共知识库", level: SpaceLevel.PUBLIC, iconSrc: GROUP_ICON_SRC.public, spaces: groupedSpaces.publicSpaces },
            { key: "department", title: "部门知识库", level: SpaceLevel.DEPARTMENT, iconSrc: GROUP_ICON_SRC.department, spaces: groupedSpaces.departmentSpaces },
            { key: "team", title: "团队知识库", level: SpaceLevel.TEAM, iconSrc: GROUP_ICON_SRC.team, spaces: groupedSpaces.teamSpaces },
            { key: "personal", title: "个人知识库", level: SpaceLevel.PERSONAL, iconSrc: GROUP_ICON_SRC.personal, spaces: groupedSpaces.personalSpaces },
        ];
    }, [groupedSpaces]);

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
        if (activeSpace && selectableSpaces.some((space) => space.id === activeSpace.id)) return;
        setActiveSpace(selectableSpaces[0] ?? null);
    }, [activeSpace, selectableSpaces, setActiveSpace]);

    return {
        groups,
        createOptionsLoading,
        createPermissionByLevel,
        selectableSpaces,
        spaceLoading,
        activeGroup,
        getSpacePermissions,
    };
}
