import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { useQuery } from "@tanstack/react-query";
import {
    getCreateSpaceOptionsApi,
    getSpaceInfoApi,
    getSpacesByLevelApi,
    SpaceLevel,
    SpaceRole,
    SpaceSortType,
    type KnowledgeSpace,
} from "~/api/knowledge";
import {
    hasKnowledgeSpacePermission,
    useKnowledgeSpaceActionPermissions,
    type KnowledgeSpaceActionPermission,
} from "../../hooks/useKnowledgeSpacePermissions";
import { GROUP_ICON_SRC } from "../constants";
import type { SpaceGroup, SpaceGroupKey } from "../types";

export interface SpaceActionPermissions {
    canEditSpace: boolean;
    canDeleteSpace: boolean;
    canManageMembers: boolean;
}

/**
 * 计算某个知识空间在 portal 侧栏上可用的操作权限。
 *
 * 个人知识库只有编辑功能：即便当前用户是 creator / 全局超管，也不能删除、
 * 不能授权/管理成员（与部门/团队/公共库区别对待）。
 */
export function resolveSpacePermissions(
    space: KnowledgeSpace,
    spaceActionPermissions: Record<string, KnowledgeSpaceActionPermission[]>,
): SpaceActionPermissions {
    const hasFullAccess = space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN;
    const hasPermission = (permissionId: KnowledgeSpaceActionPermission) => (
        hasFullAccess || hasKnowledgeSpacePermission(spaceActionPermissions, space.id, permissionId)
    );
    const isPersonal = space.spaceLevel === SpaceLevel.PERSONAL;
    return {
        canEditSpace: hasPermission("edit_space"),
        canDeleteSpace: isPersonal ? false : hasPermission("delete_space"),
        canManageMembers: isPersonal ? false : hasPermission("manage_space_relation"),
    };
}

interface UsePortalSpacesParams {
    activeSpace: KnowledgeSpace | null;
    setActiveSpace: Dispatch<SetStateAction<KnowledgeSpace | null>>;
    expandedGroups: Record<SpaceGroupKey, boolean>;
    preferredSpaceId?: string;
}

function findDefaultPersonalSpace(spaces: KnowledgeSpace[]): KnowledgeSpace | null {
    return spaces.find((space) => space.isFavorite) ?? spaces[0] ?? null;
}

function getSpaceGroupKey(space?: Pick<KnowledgeSpace, "spaceLevel"> | null): SpaceGroupKey | null {
    if (!space) return null;
    switch (space.spaceLevel) {
        case SpaceLevel.PUBLIC:
            return "public";
        case SpaceLevel.DEPARTMENT:
            return "department";
        case SpaceLevel.TEAM:
            return "team";
        case SpaceLevel.PERSONAL:
            return "personal";
        default:
            return null;
    }
}

export function usePortalSpaces({
    activeSpace,
    setActiveSpace,
    expandedGroups,
    preferredSpaceId,
}: UsePortalSpacesParams) {
    const preferredSpaceQuery = useQuery({
        queryKey: ["knowledgeSpaces", "preferred", preferredSpaceId],
        queryFn: () => getSpaceInfoApi(String(preferredSpaceId)),
        enabled: Boolean(preferredSpaceId),
        placeholderData: (prev) => prev,
    });

    const preferredSpaceGroupKey = getSpaceGroupKey(preferredSpaceQuery.data);
    const shouldLoadGroup = useCallback((groupKey: SpaceGroupKey) => (
        expandedGroups[groupKey] || preferredSpaceGroupKey === groupKey
    ), [expandedGroups, preferredSpaceGroupKey]);

    const personalSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.PERSONAL],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.PERSONAL, { order_by: SpaceSortType.UPDATE_TIME }),
        enabled: shouldLoadGroup("personal"),
        placeholderData: (prev) => prev,
    });

    const publicSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.PUBLIC],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.PUBLIC, { order_by: SpaceSortType.SORT_WEIGHT }),
        enabled: shouldLoadGroup("public"),
        placeholderData: (prev) => prev,
    });
    const departmentSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.DEPARTMENT],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.DEPARTMENT, { order_by: SpaceSortType.SORT_WEIGHT }),
        enabled: shouldLoadGroup("department"),
        placeholderData: (prev) => prev,
    });
    const teamSpacesQuery = useQuery({
        queryKey: ["knowledgeSpaces", "level", SpaceLevel.TEAM],
        queryFn: () => getSpacesByLevelApi(SpaceLevel.TEAM, { order_by: SpaceSortType.SORT_WEIGHT }),
        enabled: shouldLoadGroup("team"),
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
                loading: shouldLoadGroup("public") && publicSpacesQuery.isLoading,
            },
            {
                key: "department",
                title: "部门知识库",
                level: SpaceLevel.DEPARTMENT,
                iconSrc: GROUP_ICON_SRC.department,
                spaces: departmentSpacesQuery.data ?? [],
                loading: shouldLoadGroup("department") && departmentSpacesQuery.isLoading,
            },
            {
                key: "team",
                title: "团队知识库",
                level: SpaceLevel.TEAM,
                iconSrc: GROUP_ICON_SRC.team,
                spaces: teamSpacesQuery.data ?? [],
                loading: shouldLoadGroup("team") && teamSpacesQuery.isLoading,
            },
            {
                key: "personal",
                title: "个人知识库",
                level: SpaceLevel.PERSONAL,
                iconSrc: GROUP_ICON_SRC.personal,
                spaces: personalSpacesQuery.data ?? [],
                loading: shouldLoadGroup("personal") && personalSpacesQuery.isLoading,
            },
        ];
    }, [
        departmentSpacesQuery.data,
        departmentSpacesQuery.isLoading,
        personalSpacesQuery.data,
        personalSpacesQuery.isLoading,
        publicSpacesQuery.data,
        publicSpacesQuery.isLoading,
        shouldLoadGroup,
        teamSpacesQuery.data,
        teamSpacesQuery.isLoading,
    ]);

    const createPermissionByLevel = useMemo<Record<SpaceLevel, boolean>>(() => ({
        [SpaceLevel.PUBLIC]: Boolean(createOptions?.canCreatePublic),
        [SpaceLevel.DEPARTMENT]: Boolean(createOptions?.canCreateDepartment),
        [SpaceLevel.TEAM]: Boolean(createOptions?.canCreateTeam),
        // 个人知识库不允许手动新建（我的收藏 / {用户名}的知识库 由系统按需自动创建）
        [SpaceLevel.PERSONAL]: false,
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
            ? selectableSpaces.find((space) => String(space.id) === String(preferredSpaceId))
                ?? preferredSpaceQuery.data
                ?? null
            : null,
        [preferredSpaceId, preferredSpaceQuery.data, selectableSpaces],
    );
    const preferredSpacePending = Boolean(
        preferredSpaceId
        && !preferredSpace
        && (
            preferredSpaceQuery.isLoading
            || preferredSpaceQuery.isFetching
        ),
    );
    const fullAccessSpaceIds = useMemo(
        () => selectableSpaces
            .filter((space) => space.role === SpaceRole.CREATOR || space.role === SpaceRole.ADMIN)
            .map((space) => space.id),
        [selectableSpaces],
    );
    // 懒查询：打开知识库界面时不再批量查询所有空间的操作权限；只有当用户打开某个空间的
    // 更多菜单（需要展示 空间设置/成员管理/删除 等编辑操作）时，才把该空间加入按需查询集合。
    // creator/admin（fullAccessSpaceIds）与系统管理员由 role 直接判定，无需真正发请求。
    const [requestedPermissionSpaceIds, setRequestedPermissionSpaceIds] = useState<string[]>([]);
    const requestSpacePermissions = useCallback((spaceId: string | number) => {
        const key = String(spaceId);
        setRequestedPermissionSpaceIds((prev) => (prev.includes(key) ? prev : [...prev, key]));
    }, []);
    const { permissions: spaceActionPermissions } = useKnowledgeSpaceActionPermissions(
        requestedPermissionSpaceIds,
        { fullAccessSpaceIds },
    );
    const activeGroup = useMemo(
        () => groups.find((group) => group.spaces.some((space) => space.id === activeSpace?.id))
            ?? groups.find((group) => group.key === getSpaceGroupKey(activeSpace)),
        [activeSpace?.id, activeSpace?.spaceLevel, groups],
    );

    const getSpacePermissions = useCallback(
        (space: KnowledgeSpace) => resolveSpacePermissions(space, spaceActionPermissions),
        [spaceActionPermissions],
    );

    useEffect(() => {
        if (preferredSpace) {
            if (String(activeSpace?.id) !== String(preferredSpace.id)) {
                setActiveSpace(preferredSpace);
            }
            return;
        }
        if (preferredSpacePending) return;
        // 用 String() 兜底：新建返回的 space id 可能是数字，避免与列表里的字符串 id 不匹配而误重置
        if (activeSpace && selectableSpaces.some((space) => String(space.id) === String(activeSpace.id))) return;
        if (activeSpace && preferredSpaceId && String(activeSpace.id) === String(preferredSpaceId)) return;
        if (personalSpacesQuery.isLoading) return;
        setActiveSpace(defaultPersonalSpace ?? selectableSpaces[0] ?? null);
    }, [
        activeSpace,
        defaultPersonalSpace,
        personalSpacesQuery.isLoading,
        preferredSpace,
        preferredSpaceId,
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
        requestSpacePermissions,
    };
}
