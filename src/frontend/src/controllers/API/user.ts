import { ROLE, User } from "../../types/api/user";
import axios from "../request";

// 获取 key
export const getPublicKeyApi = async (): Promise<{ public_key: string }> => {
  return await axios.get(`/api/v1/user/public_key`);
};
// 获取验证码
export const getCaptchaApi = (): Promise<any> => {
  return axios.get(`/api/v1/user/get_captcha`);
};

// 校验登录
export async function getUserInfo(): Promise<User> {
  return await axios.get(`/api/v1/user/info`);
}
// 退出登录
export async function logoutApi() {
  return await axios.post(`/api/v1/user/logout`);
}
// 登录
export async function loginApi(name, pwd, captcha_key?, captcha?) {
  return await axios.post(`/api/v1/user/login`, {
    user_name: name,
    password: pwd,
    captcha_key,
    captcha,
  });
}
// 注册
export async function registerApi(name, pwd, captcha_key?, captcha?) {
  return await axios.post(`/api/v1/user/regist`, {
    user_name: name,
    password: pwd,
    captcha_key,
    captcha,
  });
}
// 用户列表
export async function getUsersApi({ name = '', page, pageSize, groupId, roleId }: {
  name: string,
  page: number,
  pageSize: number,
  groupId?: number[],
  roleId?: number[]
}): Promise<{ data: User[]; total: number }> {
  const groupStr = groupId?.reduce((res, id) => `${res}&group_id=${id}`, '') || ''
  const roleStr = roleId?.reduce((res, id) => `${res}&role_id=${id}`, '') || ''

  return await axios.get(
    `/api/v1/user/list?page_num=${page}&page_size=${pageSize}&name=${name}${groupStr}${roleStr}`
  );
}

// 标注任务下用户列表
export async function getLabelUsersApi( taskId: number): Promise<{ data: User[]; total: number }> {
  return await axios.get(
    `/api/v1/mark/get_user?task_id=${taskId}`
  );
}

// 修改用户状态（启\禁用）
export async function disableUserApi(userid, status) {
  return await axios.post(`/api/v1/user/update`, {
    user_id: userid,
    delete: status,
  });
}
// 角色列表
export async function getRolesApi(searchkey = ""): Promise<{ data: ROLE[] }> {
  return await axios.get(`/api/v1/role/list?role_name=${searchkey}`)
    .then(res => res.data);
}
// 用户组下角色列表
export async function getRolesByGroupApi(searchkey = "", groupIds: any[]): Promise<{ data: ROLE[] }> {
  const groupStr = groupIds?.reduce((pre, id) => `${pre}&group_id=${id}`, '') || ''
  return await axios.get(`/api/v1/group/roles?keyword=${searchkey}${groupStr}`)
    .then(res => res.data);
}
/**
 * 获取配置
 */
export async function getSysConfigApi(): Promise<string> {
  return await axios.get(`/api/v1/config`);
}
/**
 * 更新配置
 */
export async function setSysConfigApi(data) {
  return await axios.post(`/api/v1/config/save`, data);
}
/**
 * 根据角色获取技能列表
 */
export async function getRoleSkillsApi(
  params
): Promise<{ data: any[]; total: number }> {
  return await axios.get(`/api/v1/role_access/flow`, { params });
}
/**
 * 根据角色获取技能列表
 */
export async function getRoleAssistApi(
  params
): Promise<{ data: any[]; total: number }> {
  return await axios.get(`/api/v1/role_access/list_type`, { params });
}
/**
 * 根据角色获取知识库列表
 */
export async function getRoleLibsApi(
  params
): Promise<{ data: any[]; total: number }> {
  return await axios.get(`/api/v1/role_access/knowledge`, { params });
}
/**
 * 根据用户组获取资源列表
 */
export async function getGroupResourcesApi(
  params: {
    group_id: string,
    resource_type: number,
    name: string,
    page_size: number,
    page_num: number
  }
): Promise<{ data: any[]; total: number }> {
  return await axios.get(`/api/v1/group/get_group_resources`, { params });
}
/**
 * 新增角色
 */
export async function createRole(groupId, name) {
  return await axios.post(`/api/v1/role/add`, {
    group_id: groupId,
    role_name: name,
    remark: "手动创建用户",
  });
}
/**
 * 更新角色权限
 */
enum ACCESS_TYPE {
  USE_LIB = 1,
  USE_SKILL,
  MANAGE_LIB,
  ASSISTANT = 5,
  TOOL = 4,
  MENU = 99
}
export async function updateRolePermissionsApi(data: {
  role_id: number;
  access_id: number[];
  type: ACCESS_TYPE;
}) {
  return await axios.post(`/api/v1/role_access/refresh`, data);
}

/**
 * 获取角色下的权限
 */
export async function getRolePermissionsApi(
  roleId
): Promise<{ data: any[]; total: number }> {
  const params = { role_id: roleId, page_size: 200, page_num: 1 };
  return axios.get(`/api/v1/role_access/list`, { params });
  // return Promise.all([
  //     axios.get(url, { params: { ...params, type: 1 } }),
  //     axios.get(url, { params: { ...params, type: 2 } }),
  //     axios.get(url, { params: { ...params, type: 3 } })
  // ])
}

/**
 * 更新角色基本信息
 */
export async function updateRoleNameApi(roleId, name) {
  return axios.patch(`/api/v1/role/${roleId}`, {
    role_name: name,
    remark: "手动创建用户",
  });
}

/**
 * 删除角色
 */
export async function delRoleApi(roleId) {
  return axios.delete(`/api/v1/role/${roleId}`);
}

// 用户组列表
export function getUserGroupsApi() {
  return axios.get(`/api/v1/group/list`);
}


// 删除用户组post
export function delUserGroupApi(group_id) {
  return axios.delete(`/api/v1/group/create`, { params: { group_id } });
  // return axios.post(`/api/v1/group/del/${userGroupId}`);
}

// 保存用户组
export function saveUserGroup(form, selected) {
  console.log('form :>> ', form);
  const { groupName: group_name } = form
  return axios.post(`/api/v1/group/create`, {
    group_name,
    group_admins: selected.map(item => item.value),
  });
}

// 修改用户组
export function updateUserGroup(id, form, selected) {
  const { groupName: group_name } = form
  const a = axios.put(`/api/v1/group/create`, {
    id,
    group_name
  });
  const b = axios.post(`/api/v1/group/set_group_admin`, {
    group_id: id,
    user_ids: selected.map(item => item.value)
  })
  return Promise.all([a, b])
}


/**
 * 获取用户的角色信息
 */
export async function getUserRoles(userId): Promise<ROLE[]> {
  return axios.get(`/api/v1/user/role?user_id=${userId}`);
}

/**
 * 更新用户角色
 */
export async function updateUserRoles(userId, roles) {
  return await axios.post(`/api/v1/user/role_add`, {
    user_id: userId,
    role_id: roles,
  });
}
// 更新用户组
export async function updateUserGroups(userId, groupIds) {
  return await axios.post(`/api/v1/group/set_user_group`, {
    user_id: userId,
    group_id: groupIds,
    is_group_admin: false
  });
}

// 超管创建用户组
export async function createUserApi(user_name: string, password: string, group_roles: any[]) {
  return await axios.post('/api/v1/user/create', {
    user_name,
    password,
    group_roles
  })
}

/**
 * 获取所有管理员
 */
export async function getAdminsApi(): Promise<any> {
  return axios.get(`/api/v1/user/admin`);
}


/**
 * 重置密码（管理员专用）
 */
export async function resetPasswordApi(userId, password): Promise<any> {
  return axios.post(`/api/v1/user/reset_password`, {
    user_id: userId,
    password
  });
}

/**
 * 密码过期重置个人密码
 */
export async function changePasswordApi(userName, password, new_password): Promise<any> {
  return axios.post(`/api/v1/user/change_password_public`, {
    username: userName,
    password,
    new_password
  });
}

// 已登录状态重置个人密码
export async function loggedChangePasswordApi(password, new_password): Promise<any> {
  return axios.post(`/api/v1/user/change_password`, {
    password,
    new_password
  })
}