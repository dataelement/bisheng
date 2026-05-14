import request from "./request";

/**
 * 修改密码（复用后端已有 /user/change_password）
 * @param oldPassword 原密码
 * @param newPassword 新密码
 */
function normalizeApiStatusCode(res: any): number | undefined {
  const raw = res?.status_code ?? res?.code;
  if (raw === undefined || raw === null) return undefined;
  const n = typeof raw === "string" ? parseInt(raw, 10) : Number(raw);
  return Number.isNaN(n) ? undefined : n;
}

export async function updatePasswordApi(data: {
  oldPassword: string;
  newPassword: string;
}): Promise<any> {
  const res: any = await request.post(`/api/v1/user/change_password`, {
    password: data.oldPassword,
    new_password: data.newPassword,
  });
  const code = normalizeApiStatusCode(res);
  if (code !== undefined && code !== 200) {
    const msg = String(res?.status_message ?? res?.message ?? "").trim();
    const err = new Error(msg || "change_password_failed");
    (err as any).statusCode = code;
    (err as any).apiResponse = res;
    throw err;
  }
  return res;
}

/**
 * 获取当前用户信息
 */
export async function getCurrentUserApi(): Promise<any> {
  return await request.get(`/api/v1/user/current`);
}

/**
 * 上传头像（唯一的头像接口）
 * 复用后端已有的 /api/v1/upload/icon
 */
export async function uploadAvatarApi(
  file: File,
): Promise<{ file_path?: string; relative_path?: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const resp: any = await request.post(`/api/v1/user/avatar`, formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });

  const data = resp?.data ?? resp ?? {};
  return {
    file_path: data.file_path,
    relative_path: data.relative_path,
  };
}

/**
 * 上传用户头像（唯一的头像接口）
 * 复用后端已有的 /api/v1/upload/icon
 */
export async function saveAvatarUrlApi(avatar: string): Promise<any> {
  return await request.post(`/api/v1/user/avatar`, { avatar });
}

/**
 * 上传用户头像文件，并由后端生成可访问的 MinIO 预签名 URL
 * POST /api/v1/user/avatar (multipart/form-data)
 */
export async function uploadUserAvatarFileApi(file: File): Promise<{ avatar: string }> {
  const formData = new FormData();
  formData.append("file", file);
  
  const resp: any = await request.postMultiPart(`/api/v1/user/avatar`, formData);
  // unify response shape:
  // 1) { status_code, status_message, data: { avatar: "..." } }
  // 2) { status_code, status_message, data: { data: { avatar: "..." } } } (fallback)
  // 3) { avatar: "..." }
  const data = resp?.data ?? resp ?? {};
  const avatar =
    data?.avatar ??
    data?.data?.avatar ??
    resp?.avatar ??
    "";
  return { avatar: String(avatar) };
}

/**
 * 获取密码加密用的公钥
 */
export async function getPublicKeyApi(): Promise<{ public_key: string }> {
  const resp: any = await request.get(`/api/v1/user/public_key`);
  // 后端返回的是 { status_code, status_message, data: { public_key } }
  return resp?.data ?? resp;
}
