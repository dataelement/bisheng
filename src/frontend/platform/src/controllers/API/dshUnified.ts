import request from '@/controllers/request'

export type PolicySubject = { kind: 'DEPARTMENT' | 'ROLE' | 'USER'; id: number }
export type PolicySubjectOption = PolicySubject & { name: string; depth: number }
export type ModelVisibility = {
    credit_multiplier?: string
    version: number
    everyone: boolean
    subjects: PolicySubject[]
    users?: { value: number; label: string }[]
}
export type CreditRule = {
    subject_type: PolicySubject['kind']
    subject_id: number
    name?: string
    version: number
    enabled: boolean
    monthly_credits: string
}

const admin = '/api/v1/dsh/admin'
export const getPolicySubjects = (signal?: AbortSignal): Promise<PolicySubjectOption[]> =>
    request.get(`${admin}/policy-subjects`, { signal })
export const getModelVisibility = (id: number, signal?: AbortSignal): Promise<ModelVisibility> =>
    request.get(`${admin}/models/${id}/visibility`, { signal })
export const saveModelVisibility = (id: number, value: ModelVisibility): Promise<ModelVisibility> =>
    request.put(`${admin}/models/${id}/visibility`, {
        version: value.version, everyone: value.everyone,
        credit_multiplier: value.credit_multiplier ?? "1",
        subjects: value.everyone ? [] : value.subjects,
    })
export const getCreditRules = (signal?: AbortSignal): Promise<CreditRule[]> =>
    request.get(`${admin}/credit-rules`, { signal })
export const saveCreditRule = (
    subject: PolicySubject, value: { version: number; enabled: boolean; monthly_credits: string },
): Promise<CreditRule> => request.put(`${admin}/credit-rules/${subject.kind}/${subject.id}`, value)
