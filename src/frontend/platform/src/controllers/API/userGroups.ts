/**
 * 用户组管理（PRD 3.2.2）— /api/v1/user-groups
 */
import axios from "../request";

const USER_GROUP_PAGE_SIZE = 20;

export type UserGroupV2 = {
  id: number;
  group_name: string;
  visibility: string;
  remark?: string | null;
  member_count?: number;
  create_user?: number | string | null;
  create_user_name?: string | null;
  create_time?: string;
  update_time?: string;
  group_admins?: { user_id: number; user_name: string }[];
};

export async function listUserGroupsV2(params?: {
  page?: number;
  limit?: number;
  keyword?: string;
}): Promise<{ data: UserGroupV2[]; total: number }> {
  // 尾部斜杠与 FastAPI 子路由 @router.get('/') 一致，避免 307 跳到 127.0.0.1:7860 触发跨域 + credentials 与 * 冲突
  return axios.get(`/api/v1/user-groups/`, {
    params: { page: 1, limit: USER_GROUP_PAGE_SIZE, ...params },
  });
}

export async function createUserGroupV2(body: {
  group_name: string;
  visibility: string;
  admin_user_ids?: number[];
  remark?: string | null;
}): Promise<UserGroupV2> {
  return axios.post(`/api/v1/user-groups/`, body);
}

export async function updateUserGroupV2(
  groupId: number,
  body: { group_name?: string; visibility?: string; remark?: string | null },
): Promise<UserGroupV2> {
  return axios.put(`/api/v1/user-groups/${groupId}`, body);
}

export async function deleteUserGroupV2(groupId: number): Promise<void> {
  return axios.delete(`/api/v1/user-groups/${groupId}`);
}

export async function setUserGroupAdminsV2(
  groupId: number,
  user_ids: number[],
): Promise<{ user_id: number; user_name: string }[]> {
  return axios.put(`/api/v1/user-groups/${groupId}/admins`, { user_ids });
}

export type UserGroupMemberRow = {
  user_id: number;
  user_name: string;
  is_group_admin: boolean;
  create_time?: string;
  department_path?: string;
};

export async function getUserGroupMembersV2(
  groupId: number,
  params?: { page?: number; limit?: number; keyword?: string },
): Promise<{ data: UserGroupMemberRow[]; total: number }> {
  return axios.get(`/api/v1/user-groups/${groupId}/members`, {
    params: { page: 1, limit: USER_GROUP_PAGE_SIZE, ...params },
  });
}

export async function paginateAllUserGroupMembers(
  fetchPage: (
    page: number,
    limit: number,
    keyword: string,
  ) => Promise<{ data: UserGroupMemberRow[]; total: number }>,
  params?: { limit?: number; keyword?: string },
): Promise<UserGroupMemberRow[]> {
  const limit = Math.max(1, params?.limit ?? USER_GROUP_PAGE_SIZE);
  const keyword = params?.keyword ?? "";
  const rows: UserGroupMemberRow[] = [];
  let page = 1;
  let total = 0;
  let safety = 0;

  while (safety < 1000) {
    const res = await fetchPage(page, limit, keyword);
    const pageRows = res?.data ?? [];
    total = Number(res?.total ?? rows.length + pageRows.length);
    rows.push(...pageRows);

    if (pageRows.length === 0 || rows.length >= total) break;

    page += 1;
    safety += 1;
  }

  return rows;
}

export async function getAllUserGroupMembersV2(
  groupId: number,
  params?: { limit?: number; keyword?: string },
): Promise<UserGroupMemberRow[]> {
  return paginateAllUserGroupMembers(
    (page, limit, keyword) =>
      getUserGroupMembersV2(groupId, { page, limit, keyword }),
    params,
  );
}

export async function addUserGroupMembersV2(
  groupId: number,
  user_ids: number[],
): Promise<void> {
  return axios.post(`/api/v1/user-groups/${groupId}/members`, { user_ids });
}

/** 全量同步普通成员（与编辑页多选一致），避免逐项 diff 与初始 ref 不一致导致保存无效 */
export async function syncUserGroupMembersV2(
  groupId: number,
  user_ids: number[],
): Promise<void> {
  // 使用 POST：部分网关/代理对 PUT 返回 405；后端同时保留 PUT 兼容
  return axios.post(`/api/v1/user-groups/${groupId}/members/sync`, {
    user_ids,
  });
}

export async function removeUserGroupMemberV2(
  groupId: number,
  userId: number,
): Promise<void> {
  return axios.delete(`/api/v1/user-groups/${groupId}/members/${userId}`);
}
