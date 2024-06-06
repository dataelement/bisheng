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
export async function getUsersApi(
  name: string,
  page: number,
  pageSize: number
): Promise<{ data: User[]; total: number }> {
  return await axios.get(
    `/api/v1/user/list?page_num=${page}&page_size=${pageSize}&name=${
      name || ""
    }`
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
  return await axios.get(`/api/v1/role/list?role_name=${searchkey}`);
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
 * 新增角色
 */
export async function createRole(name) {
  return await axios.post(`/api/v1/role/add`, {
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
export async function getUserGroupsApi() {
    return {
      msg: "",
      code: "200",
      data: {
        records: [
          {
            id: 2,
            groupName: "lzsceshi",
            adminUser: "2,3m4,5",
            adminUserId: "",
            groupLimit: 10,
            createTime: "2024-06-03 17:23:54",
            updateTime: "2024-06-03 17:23:54",
            logicDelete: 0,
          },
          {
            id: 3,
            groupName: "ljlceshi",
            adminUser: "2,3m4,5",
            adminUserId: "",
            groupLimit: 10,
            createTime: "2024-06-03 17:23:55",
            updateTime: "2024-06-03 17:23:55",
            logicDelete: 0,
          },
          {
            id: 4,
            groupName: "ldbceshi",
            adminUser: "2,3m4,5",
            adminUserId: "",
            groupLimit: 10,
            createTime: "2024-06-03 17:23:56",
            updateTime: "2024-06-03 17:23:56",
            logicDelete: 0,
          },
          {
            id: 5,
            groupName: "shceshi",
            adminUser: "2,3m4,5",
            adminUserId: "",
            groupLimit: 10,
            createTime: "2024-06-03 17:27:45",
            updateTime: "2024-06-03 17:27:45",
            logicDelete: 0,
          },
          {
            id: 6,
            groupName: "zgjceshi",
            adminUser: "2,3m4,5",
            adminUserId: "",
            groupLimit: 10,
            createTime: "2024-06-03 17:29:52",
            updateTime: "2024-06-03 17:29:52",
            logicDelete: 0,
          },
        ],
        total: 5,
        size: 10,
        current: 1,
        pages: 1,
      },
    };
  }
  // 所有用户
  export async function getAllUsersApi() {
    return {
      data: [
        { id: '1', name: "admin" },
        { id: '2', name: "用户X" },
        { id: '3', name: "用户Y" },
        { id: '4', name: "用户Z" },
        { id: '5', name: "用户W" },
        {id: '10', name: '2'},
        {id: '20', name: '3m4'},
        {id: '30', name: '5'}
      ],
    };
  }
// 删除用户组post
export async function delUserGroupApi(userGroupId) {}
// 获取用户组详情
export async function getUserGroupDetail(userGroupId) {
  return {
    msg: "",
    code: "200",
    data: {
      groupName: "lzsceshi",
      adminUser: "2,3m4,5",
      adminUserId: "10,20,30",
      groupLimit: 10,
      assistantList: "",
      skillList: "",
    },
  };
}
// 保存用户组
export async function saveUserGroup(form) {

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
export async function updateUserGroups(userId, userGroups) {

}
// 获取用户组类别
export function getUserGroupTypes() {
  return [
    { id: "01", name: "默认用户组", checked: true},
    { id: "02", name: "用户组A", checked:false},
    { id: "03", name: "用户组B", checked:false },
  ];
}
// 获取用户角色类别
export function getRoleTypes() {
  return [
    { id: "01", name: "普通用户", checked:false},
    { id: "02", name: "用户A", checked:false},
    { id: "03", name: "用户B", checked:false },
  ];
}
// 用户组/角色 筛选功能
export function getSearchRes(name: string, ...param: string[]) {
  console.log([...param]);
  return [];
}
// 获取用户组的所有用户关联的助手
export async function getUserGroupAssistApi() {
  return {
    data: [
      { id: "01", name: "助手一", createdBy: "用户X", flowCtrl: 10 },
      { id: "02", name: "助手二", createdBy: "用户Y", flowCtrl: null },
      { id: "03", name: "助手三", createdBy: "用户Z", flowCtrl: 20 },
      { id: "04", name: "助手四", createdBy: "用户W", flowCtrl: null },
    ],
    total: 4,
  };
}
// 获取用户组的所有用户关联的技能
export async function getUserGroupSkillApi() {
  return {
    data: [
      { id: "01", name: "技能一", createdBy: "用户X", flowCtrl: 13 },
      { id: "02", name: "技能二", createdBy: "用户Y", flowCtrl: null },
      { id: "03", name: "技能三", createdBy: "用户Z", flowCtrl: 15 },
      { id: "04", name: "技能四", createdBy: "用户W", flowCtrl: null },
    ],
    total: 4,
  };
}
