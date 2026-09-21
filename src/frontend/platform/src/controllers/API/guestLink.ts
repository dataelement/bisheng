import axios from "../request"

export interface GuestLinkCandidate {
  user_id: number
  user_name: string
}

export interface GuestLinkWarnings {
  operator_is_admin: boolean
  default_not_in_tenant: boolean
  operator_inactive: boolean
}

export interface GuestLinkSettings {
  enabled: boolean
  follow_system_default: boolean
  user_id: number | null
  operator_user_id: number | null
  operator_user_name: string | null
  default_operator_user_id: number | null
  default_operator_user_name: string | null
  default_operator_in_tenant: boolean
  system_guest_access: boolean
  can_edit: boolean
  warnings: GuestLinkWarnings
  candidates: GuestLinkCandidate[]
}

export type GuestLinkKind = "workflow" | "assistant"

export function getGuestLinkApi(
  kind: GuestLinkKind,
  id: string,
  keyword?: string,
): Promise<GuestLinkSettings> {
  const query = keyword?.trim()
  return axios.get(`/api/v1/guest-link/${kind}/${id}`, query ? { params: { keyword: query } } : undefined)
}

export function patchGuestLinkApi(
  kind: GuestLinkKind,
  id: string,
  data: { enabled?: boolean; user_id?: number | null },
): Promise<GuestLinkSettings> {
  return axios.patch(`/api/v1/guest-link/${kind}/${id}`, data)
}
