/** 异常文件 tab：平台管理员、系统管理员或超管。门户「管理员」不可见。 */
export function canSeeAbnormalFiles(user: {
    role?: string
    is_global_super?: boolean
} | null | undefined): boolean {
    if (!user) return false
    if (user.is_global_super) return true
    const role = (user.role || "").trim()
    return role === "平台管理员" || role === "系统管理员" || role === "admin"
}
