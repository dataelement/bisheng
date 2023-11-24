import axios, { AxiosResponse } from "axios";

axios.interceptors.response.use(function (response) {
    return response;
}, function (error) {
    if (error.response.status === 401) {
        // cookie expires
        console.error('登录过期 :>> ');
        const isLogin = localStorage.getItem('isLogin')
        localStorage.removeItem('isLogin')
        isLogin && location.reload()
    }
    return Promise.reject(error);
})
// 校验登录
export async function getUserInfo() {
    return await axios.get(`/api/v1/user/info`);
}
// 退出登录
export async function logoutApi() {
    return await axios.post(`/api/v1/user/logout`);
}
// 登录
export async function loginApi(name, pwd) {
    return await axios.post(`/api/v1/user/login`, { user_name: name, password: pwd });
}
// 注册
export async function registerApi(name, pwd) {
    return await axios.post(`/api/v1/user/regist`, { user_name: name, password: pwd });
}
// 用户列表
export async function getUsersApi(name: string, page: number, pageSize: number) {
    return await axios.get(`/api/v1/user/list?page_num=${page}&page_size=${pageSize}&name=${name || ''}`)
}
// 修改用户状态（启\禁用）
export async function disableUserApi(userid, status) {
    return await axios.post(`/api/v1/user/update`, { user_id: userid, delete: status });
}
// 角色列表
export async function getRolesApi() {
    return await axios.get(`/api/v1/role/list`)
}
/**
 * 获取配置
 */
export async function getSysConfigApi() {
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
export async function getRoleSkillsApi(params) {
    return await axios.get(`/api/v1/role_access/flow`, { params });
}
/**
 * 根据角色获取知识库列表
 */
export async function getRoleLibsApi(params) {
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
export async function getRolePermissionsApi(roleId) {
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
export async function getUserRoles(userId) {
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