import { isDshSeatLimitReached } from '@/controllers/API/dsh'

const errorCodeByReason: Record<string, number> = {
    invalid_request: 26101,
    seat_revoked: 26113,
    license_invalid: 26114,
    license_expired: 26115,
    dsh_disabled: 26116,
    user_disabled: 26117,
    tenant_unavailable: 26118,
    model_not_allowed: 26119,
    authorization_conflict: 26120,
    authorization_unavailable: 26125,
}

/** Resolve known service failures through the shared error-code locale catalog. */
export function getDshRequestErrorKey(error: unknown): string | undefined {
    if (isDshSeatLimitReached(error)) return 'dsh.seatLimitGrantHelp'
    if (!error || typeof error !== 'object') return
    const response = 'response' in error ? error.response : undefined
    const data = response && typeof response === 'object' && 'data' in response
        ? response.data : error
    if (!data || typeof data !== 'object') return
    if ('status_code' in data) {
        const code = Number(data.status_code)
        if (code === 11001 || (Number.isInteger(code) && code >= 26101 && code <= 26130))
            return `api_errors:${code}`
    }
    const failure = 'error' in data ? data.error : data
    if (!failure || typeof failure !== 'object') return
    const reason = 'status' in failure && failure.status === 'FAILED' && 'result_code' in failure
        ? failure.result_code
        : 'code' in failure ? failure.code : undefined
    const code = typeof reason === 'string' ? errorCodeByReason[reason] : undefined
    if (typeof code === 'number') return `api_errors:${code}`
}
