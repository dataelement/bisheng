// PRD 3.2.1 定义：第三方同步数据的只读字段（先定义，后续逐步接入编辑页）
export const SYNC_READONLY_DEPARTMENT_FIELDS = [
  "name",
  "parent_id",
  "dept_id",
  "delete",
] as const

export const SYNC_READONLY_MEMBER_FIELDS = [
  "user_name",
  "external_id",
  "primary_department",
] as const

export const isSyncedSource = (source?: string) => (source || "").toLowerCase() !== "local"
