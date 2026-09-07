import axios from "@/controllers/request"
import type {
  PersonalTokenLedgerPage,
  PersonalTokenSetting,
} from "@/types/api/openApi"

export async function getPersonalTokenSettingApi(): Promise<PersonalTokenSetting> {
  return await axios.get("/api/v1/personal-tokens/settings")
}

export async function updatePersonalTokenSettingApi(data: {
  pat_enabled: boolean
  pat_ttl_days: number
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

export async function revokePersonalTokensByHolderApi(userId: number): Promise<void> {
  await axios.post(`/api/v1/personal-tokens/holders/${userId}/revoke`)
}
