import request from '@/controllers/request'
import type {
    DshModelAccessPage,
    DshModelAccessUser,
    DshAuthorization,
    DshDenial,
    DshConfig,
    DshLicense,
    DshOperation,
    DshPage,
    DshPolicy,
    DshPolicyInput,
    DshSeat,
    DshSeatQuery,
    DshSession,
} from '@/types/dsh'

const admin = '/api/v1/dsh/admin'
const malformed = () => new Error('Invalid DSH response')

export async function getDshModelUsers(
    modelId: number,
    query: { cursor?: string; keyword?: string; limit: number },
    signal?: AbortSignal,
): Promise<DshModelAccessPage> {
    const data: DshModelAccessPage = await request.get(`${admin}/models/${modelId}/users`, { params: query, signal })
    if (!data || data.model?.id !== modelId || typeof data.model.name !== 'string'
        || !Number.isSafeInteger(data.tenant_id) || data.tenant_id < 1
        || !Array.isArray(data.items) || data.items.length > query.limit
        || typeof data.has_more !== 'boolean'
        || (data.has_more && !data.next_cursor)
        || data.items.some((row) => !Number.isSafeInteger(row.user_id) || row.user_id < 1
            || typeof row.user_name !== 'string' || !Number.isSafeInteger(row.version) || row.version < 0
            || typeof row.enabled !== 'boolean' || !Number.isSafeInteger(row.monthly_token_limit) || row.monthly_token_limit < 0
            || (row.pending_operation_id !== null && typeof row.pending_operation_id !== 'string'))) throw malformed()
    return data
}
function validModelConfigs(value: unknown): boolean {
    if (!Array.isArray(value)) return false
    const ids = new Set<number>()
    return value.every((model) => {
        if (
            !model ||
            typeof model !== 'object' ||
            !Number.isSafeInteger(model.model_id) ||
            model.model_id < 1 ||
            !Number.isSafeInteger(model.monthly_token_limit) ||
            model.monthly_token_limit < 0 ||
            ids.has(model.model_id)
        )
            return false
        ids.add(model.model_id)
        return true
    })
}
function validModelCounters(value: unknown): boolean {
    return (
        value === null ||
        (!!value &&
            typeof value === 'object' &&
            !Array.isArray(value) &&
            Object.entries(value).every(
                ([id, amount]) =>
                    /^[1-9]\d*$/.test(id) &&
                    Number.isSafeInteger(amount) &&
                    amount >= 0,
            ))
    )
}
export function parseDshConfig(raw: unknown): DshConfig {
    if (!raw || typeof raw !== 'object' || !('enabled' in raw))
        throw malformed()
    if (raw.enabled === false) return { enabled: false }
    if (
        raw.enabled === true &&
        'client_id' in raw &&
        raw.client_id === 'dsh-desktop' &&
        'contract_version' in raw &&
        raw.contract_version === '0.4.0'
    )
        return {
            enabled: true,
            client_id: raw.client_id,
            contract_version: raw.contract_version,
        }
    throw malformed()
}
export async function getDshConfig(signal?: AbortSignal): Promise<DshConfig> {
    // Adapt the documented raw config to the existing envelope interceptor.
    return await request.get('/api/v1/dsh/config', {
        signal,
        transformResponse: [
            (raw: string) => ({
                status_code: 200,
                data: parseDshConfig(JSON.parse(raw)),
            }),
        ],
    })
}
export function validateAuthorization(
    value: DshAuthorization,
): DshAuthorization {
    if (
        !value ||
        typeof value.identity_ticket !== 'string' ||
        !value.identity_ticket ||
        typeof value.state !== 'string' ||
        !value.state ||
        !Number.isInteger(value.expires_in) ||
        value.expires_in < 1 ||
        value.expires_in > 60
    )
        throw malformed()
    validateLoopback(value.redirect_uri)
    return value
}
export function validateLoopback(redirectUri: string): void {
    const url = new URL(redirectUri)
    if (
        url.protocol !== 'http:' ||
        url.hostname !== '127.0.0.1' ||
        !url.port ||
        Number(url.port) < 1 ||
        url.pathname !== '/dsh/callback' ||
        url.search ||
        url.hash ||
        url.username ||
        url.password ||
        redirectUri !== `http://127.0.0.1:${url.port}/dsh/callback`
    )
        throw malformed()
}
export async function denyDsh(
    authId: string,
    signal?: AbortSignal,
): Promise<DshDenial> {
    const data: DshDenial = await request.post(
        '/api/v1/dsh/authorize',
        { auth_id: authId, decision: 'deny' },
        { signal },
    )
    if (
        !data ||
        data.error !== 'access_denied' ||
        typeof data.state !== 'string' ||
        !data.state
    )
        throw malformed()
    validateLoopback(data.redirect_uri)
    return data
}
export async function authorizeDsh(
    authId: string,
    signal?: AbortSignal,
): Promise<DshAuthorization> {
    return validateAuthorization(
        await request.post(
            '/api/v1/dsh/authorize',
            { auth_id: authId },
            { signal },
        ),
    )
}
export function validatePage<T>(page: DshPage<T>): DshPage<T> {
    if (
        !page ||
        !Array.isArray(page.items) ||
        typeof page.has_more !== 'boolean' ||
        (page.next_cursor !== null && typeof page.next_cursor !== 'string') ||
        (page.has_more && !page.next_cursor)
    )
        throw malformed()
    return page
}
export async function getDshSeats(
    params: DshSeatQuery,
    signal?: AbortSignal,
): Promise<DshPage<DshSeat>> {
    const page: DshPage<DshSeat> = validatePage(
        await request.get(`${admin}/users`, { params, signal }),
    )
    if (
        page.items.some(
            (item) =>
                !item.seat_id ||
                !/^[1-9]\d*$/.test(item.user_id) ||
                !/^[1-9]\d*$/.test(item.tenant_id) ||
                !Number.isSafeInteger(item.grant_version) ||
                item.grant_version < 1 ||
                !['ASSIGNED', 'REVOKED'].includes(item.state),
        )
    )
        throw malformed()
    return page
}
export async function getDshLicense(signal?: AbortSignal): Promise<DshLicense> {
    const data: DshLicense = await request.get(`${admin}/license`, { signal })
    if (
        !data ||
        !Number.isSafeInteger(data.seat_limit) ||
        !Number.isSafeInteger(data.assigned) ||
        !Number.isSafeInteger(data.available) ||
        !data.as_of
    )
        throw malformed()
    return data
}
export async function getDshSessions(
    userId: string,
    tenantId: string,
    cursor?: string,
    signal?: AbortSignal,
): Promise<DshPage<DshSession>> {
    return validatePage(
        await request.get(
            `${admin}/users/${encodeURIComponent(userId)}/sessions`,
            { params: { tenant_id: tenantId, cursor, limit: 20 }, signal },
        ),
    )
}
export async function getDshPolicy(
    userId: string,
    tenantId?: string,
    signal?: AbortSignal,
): Promise<DshPolicy> {
    const data: DshPolicy = await request.get(
        `${admin}/users/${encodeURIComponent(userId)}/policy`,
        { params: { tenant_id: tenantId }, signal },
    )
    if (
        !data ||
        !Number.isSafeInteger(data.version) ||
        !validModelConfigs(data.models) ||
        (data.usage != null &&
            (!validModelCounters(data.usage.models) ||
                !validModelCounters(data.usage.model_limits))) ||
        !Number.isSafeInteger(data.tenant_id) ||
        data.tenant_id < 1 ||
        !Array.isArray(data.available_models) ||
        !['live', 'unavailable'].includes(data.available_models_source) ||
        !['persisted', 'unavailable'].includes(data.last_call_source) ||
        data.available_models.some(
            (model) =>
                !Number.isSafeInteger(model.id) ||
                model.id < 1 ||
                typeof model.name !== 'string' ||
                !model.name ||
                typeof model.is_root_shared !== 'boolean',
        )
    )
        throw malformed()
    return data
}
export async function saveDshPolicy(
    userId: string,
    modelId: number,
    tenantId: string,
    body: DshPolicyInput,
): Promise<DshOperation> {
    if (typeof body.enabled !== 'boolean' || !Number.isSafeInteger(body.monthly_token_limit) || body.monthly_token_limit < 0) throw malformed()
    const config = { params: { tenant_id: tenantId }, preserveError: true }
    return await request.put(
        `${admin}/users/${encodeURIComponent(userId)}/models/${modelId}/policy`,
        body,
        config,
    )
}
export async function commandDshSeat(
    userId: string,
    tenantId: string,
    action: 'revoke' | 'reassign',
    operationId: string,
    grantVersion: number,
): Promise<DshOperation> {
    const config = { params: { tenant_id: tenantId }, preserveError: true }
    return await request.post(
        `${admin}/users/${encodeURIComponent(userId)}/${action}`,
        { operation_id: operationId, expected_grant_version: grantVersion },
        config,
    )
}
export async function getDshOperation(
    operationId: string,
    tenantId: string,
    signal?: AbortSignal,
): Promise<DshOperation> {
    const data: DshOperation = await request.get(
        `${admin}/operations/${encodeURIComponent(operationId)}`,
        { params: { tenant_id: tenantId }, signal },
    )
    if (
        !data ||
        data.operation_id !== operationId ||
        !['PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED'].includes(data.status)
    )
        throw malformed()
    return data
}

export function isDshRequestRejected(error: unknown): boolean {
    if (!error || typeof error !== 'object' || !('response' in error))
        return false
    const response = error.response
    if (!response || typeof response !== 'object') return false
    if (
        'status' in response &&
        [400, 409, 422].includes(Number(response.status))
    )
        return true
    if (
        'data' in response &&
        response.data &&
        typeof response.data === 'object' &&
        'status_code' in response.data
    ) {
        // Platform business failures may keep HTTP 200; only explicit pre-commit rejection codes qualify.
        return [26101, 26129, 26130].includes(Number(response.data.status_code))
    }
    return false
}


export async function getDshModelPolicy(userId: string, modelId: number, tenantId: string, signal?: AbortSignal): Promise<Omit<DshModelAccessUser, 'user_name'>> {
    const data: Omit<DshModelAccessUser, 'user_name'> = await request.get(`${admin}/users/${encodeURIComponent(userId)}/models/${modelId}/policy`, {params: {tenant_id: tenantId}, signal})
    if (!data || !Number.isSafeInteger(data.version) || data.version < 0 || typeof data.enabled !== 'boolean'
        || !Number.isSafeInteger(data.monthly_token_limit) || data.monthly_token_limit < 0) throw malformed()
    return data
}
