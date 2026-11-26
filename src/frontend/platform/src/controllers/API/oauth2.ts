import request from '@/controllers/request'
import type {
    OAuth2ClientCreateInput,
    OAuth2ClientItem,
    OAuth2ClientSecretResult,
    OAuth2ClientUpdateInput,
    OAuth2ConsentDecisionResult,
    OAuth2ConsentDetails,
} from '@/types/oauth2'

const clientsBase = '/api/v1/oauth2/clients'

export async function listOAuth2Clients(params?: {
    keyword?: string
    page?: number
    page_size?: number
}): Promise<{ data: OAuth2ClientItem[]; total: number }> {
    return request.get(clientsBase, { params })
}

export async function createOAuth2Client(
    body: OAuth2ClientCreateInput,
): Promise<OAuth2ClientSecretResult> {
    return request.post(clientsBase, body)
}

export async function updateOAuth2Client(
    clientId: string,
    body: OAuth2ClientUpdateInput,
): Promise<OAuth2ClientItem> {
    return request.put(`${clientsBase}/${encodeURIComponent(clientId)}`, body)
}

export async function rotateOAuth2ClientSecret(
    clientId: string,
): Promise<OAuth2ClientSecretResult> {
    return request.post(
        `${clientsBase}/${encodeURIComponent(clientId)}/rotate-secret`,
    )
}

export async function deleteOAuth2Client(
    clientId: string,
): Promise<{ deleted: boolean }> {
    return request.delete(`${clientsBase}/${encodeURIComponent(clientId)}`)
}

export async function getOAuth2ConsentDetails(
    requestId: string,
    signal?: AbortSignal,
): Promise<OAuth2ConsentDetails> {
    return request.get(
        `/api/v1/oauth2/consent/${encodeURIComponent(requestId)}`,
        { signal },
    )
}

export async function submitOAuth2ConsentDecision(
    requestId: string,
    decision: 'approve' | 'deny',
    signal?: AbortSignal,
): Promise<OAuth2ConsentDecisionResult> {
    return request.post(
        `/api/v1/oauth2/consent/${encodeURIComponent(requestId)}`,
        { decision },
        { signal },
    )
}
