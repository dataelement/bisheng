import request from "./request";

/**
 * 修改密码
 * @param oldPassword 原密码
 * @param newPassword 新密码
 */
export async function updatePasswordApi(data: {
    oldPassword: string;
    newPassword: string;
}): Promise<any> {
    return await request.post(`/api/v1/user/update-password`, data);
}

/**
 * 获取当前用户信息
 */
export async function getCurrentUserApi(): Promise<any> {
    return await request.get(`/api/v1/user/current`);
}
