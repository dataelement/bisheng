import axios from "@/controllers/request"
import type {
  PersonalTokenDataScope,
  PersonalTokenLedgerPage,
  PersonalTokenSetting,
} from "@/types/api/openApi"

export async function getPersonalTokenSettingApi(): Promise<PersonalTokenSetting> {
  return await axios.get("/api/v1/personal-tokens/settings")
}

export async function updatePersonalTokenSettingApi(data: {
  pat_enabled: boolean
  pat_ttl_days: number
  data_scope: PersonalTokenDataScope
}): Promise<PersonalTokenSetting> {
  return await axios.put("/api/v1/personal-tokens/settings", data)
}

export async function listPersonalTokensApi(params: {
  page: number
  page_size: number
}): Promise<PersonalTokenLedgerPage> {
  return await axios.get("/api/v1/personal-tokens", { params })
}

export async function revokePersonalTokenApi(id: number): Promise<void> {
  await axios.post(`/api/v1/personal-tokens/${id}/revoke`)
}
