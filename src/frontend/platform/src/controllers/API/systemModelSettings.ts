import request from '@/controllers/request'
import type { ModelVisionRow } from './modelPricing'

export type SystemModelKey = 'linsight_llm' | 'knowledge_llm' | 'assistant_llm' | 'evaluation_llm' | 'workflow_llm'
export type ModelReferenceStatus = 'available' | 'missing' | 'outside_tenant' | 'not_shared' | 'offline' | 'wrong_type'
export interface SystemModelSection {
    key: SystemModelKey
    inherited_from_root: boolean
    fallback_blocked: boolean
    references: { slot_key: string; model_id: number; model_name: string | null; status: ModelReferenceStatus }[]
    inheritance_impact?: { slot_key: string; model_id: number; missing_tenant_ids: number[] }[]
}
export interface SystemModelSettings {
    tenant_id: number
    sections: SystemModelSection[]
}
export const getSystemModelSettings = (signal?: AbortSignal, includeImpact = false): Promise<SystemModelSettings> =>
    request.get('/api/v1/llm/system-settings', { params: { include_impact: includeImpact }, signal, silent: true })
export const restoreModelInheritance = async (key: SystemModelKey): Promise<void> => {
    await request.post(`/api/v1/llm/settings/defaults/${key}/inheritance`, {})
}
export const saveModelVision = (modelId: number, vision: boolean): Promise<ModelVisionRow> =>
    request.put(`/api/v1/dsh/admin/models/${modelId}/vision`, { vision }, { silent: true })

export interface ModelSharingStatus {
    enabled: boolean | null
    version: number
    shared_child_ids: number[]
    expected_child_ids: number[]
    missing_child_ids: number[]
    active_plan: { id: string; state: string; operation: string } | null
}
export const getModelSharingStatus = (serverId: number, signal?: AbortSignal): Promise<ModelSharingStatus> =>
    request.get(`/api/v1/llm/${serverId}/sharing-status`, { signal, silent: true })
