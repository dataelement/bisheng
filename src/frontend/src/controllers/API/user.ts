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
    return await axios.post(`/api/v1/user/login`, { user_name: name, password: pwd, captcha_key, captcha });
}
// 注册
export async function registerApi(name, pwd, captcha_key?, captcha?) {
    return await axios.post(`/api/v1/user/regist`, { user_name: name, password: pwd, captcha_key, captcha });
}
// 用户列表
export async function getUsersApi(name: string, page: number, pageSize: number): Promise<{ data: User[], total: number }> {
    return await axios.get(`/api/v1/user/list?page_num=${page}&page_size=${pageSize}&name=${name || ''}`)
}
// 修改用户状态（启\禁用）
export async function disableUserApi(userid, status) {
    return await axios.post(`/api/v1/user/update`, { user_id: userid, delete: status });
}
// 角色列表
export async function getRolesApi(searchkey = ''): Promise<{ data: ROLE[] }> {
    return await axios.get(`/api/v1/role/list?role_name=${searchkey}`)
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
export async function getRoleSkillsApi(params): Promise<{ data: any[], total: number }> {
    return await axios.get(`/api/v1/role_access/flow`, { params });
}
/**
 * 根据角色获取知识库列表
 */
export async function getRoleLibsApi(params): Promise<{ data: any[], total: number }> {
    return await axios.get(`/api/v1/role_access/knowledge`, { params });
}
/**
 * 新增角色
 */
export async function createRole(name) {
    return await axios.post(`/api/v1/role/add`, {
        "role_name": name,
        "remark": "手动创建用户"
    });
}
/**
 * 更新角色权限
 */
enum ACCESS_TYPE {
    USE_LIB = 1,
    USE_SKILL,
    MANAGE_LIB
}
export async function updateRolePermissionsApi(data: { role_id: number, access_id: number[], type: ACCESS_TYPE }) {
    return await axios.post(`/api/v1/role_access/refresh`, data);
}

/**
 * 获取角色下的权限
 */
export async function getRolePermissionsApi(roleId): Promise<{ data: any[], total: number }> {
    const params = { role_id: roleId, page_size: 200, page_num: 1 }
    return axios.get(`/api/v1/role_access/list`, { params })
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
        "role_name": name,
        "remark": "手动创建用户"
    })
}

/**
 * 删除角色
 */
export async function delRoleApi(roleId) {
    return axios.delete(`/api/v1/role/${roleId}`)
}

/**
 * 获取用户的角色信息
 */
export async function getUserRoles(userId): Promise<ROLE[]> {
    return axios.get(`/api/v1/user/role?user_id=${userId}`)
}

/**
 * 更新用户角色
 */
export async function updateUserRoles(userId, roles) {
    return await axios.post(`/api/v1/user/role_add`, {
        user_id: userId,
        role_id: roles
    });
}