import axios from "@/controllers/request"

export type RebacSchemaType = {
  type: string
  relations: string[]
}

export async function getRebacSchemaApi(): Promise<{
  schema_version: string
  model_version: string
  types: RebacSchemaType[]
}> {
  return await axios.get(`/api/v1/permissions/rebac-schema`)
}
