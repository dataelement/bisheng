import request from '@/controllers/request'
import type {
    DshModelAccessPage,
    DshModelAccessUser,
    DshModelUserPermissionPage,
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
    DshUsageMetrics,
    DshUsageOverviewPage,
    DshUsageTimeSummary,
    DshSubjectPolicy,
    DshSubjectPolicyInput,
    DshSubjectPolicyInventory,
    DshSubjectType,
} from '@/types/dsh'

const admin = '/api/v1/dsh/admin'
const malformed = () => new Error('Invalid DSH response')

export async function getDshModelUsers(
    modelId: number,
    query: { cursor?: string; keyword?: string; limit: number },
    signal?: AbortSignal,
): Promise<DshModelAccessPage> {
    const data: DshModelAccessPage = await request.get(
        `${admin}/models/${modelId}/users`,
        { params: query, signal },
    )
    if (
        !data ||
        data.model?.id !== modelId ||
        typeof data.model.name !== 'string' ||
        !Number.isSafeInteger(data.tenant_id) ||
        data.tenant_id < 1 ||
        !Array.isArray(data.items) ||
        data.items.length > query.limit ||
        typeof data.has_more !== 'boolean' ||
        (data.has_more && !data.next_cursor) ||
        data.items.some(
            (row) =>
                !Number.isSafeInteger(row.user_id) ||
                row.user_id < 1 ||
                typeof row.user_name !== 'string' ||
                !Number.isSafeInteger(row.version) ||
                row.version < 0 ||
                typeof row.enabled !== 'boolean' ||
                !Number.isSafeInteger(row.monthly_token_limit) ||
                row.monthly_token_limit < 0 ||
                (row.pending_operation_id !== null &&
                    typeof row.pending_operation_id !== 'string'),
        )
    )
        throw malformed()
    return data
}

export async function getDshModelUserPermissions(
    modelId: number,
    query: {
        cursor?: string
        keyword?: string
        limit: number
        department_id?: number
        membership?: 'DIRECT' | 'EFFECTIVE'
        unassigned_only?: boolean
        include_seats?: boolean
    },
    signal?: AbortSignal,
): Promise<DshModelUserPermissionPage> {
    const data: DshModelUserPermissionPage = await request.get(
        `${admin}/models/${modelId}/user-permissions`,
        { params: query, signal },
    )
    const validIdName = (value: unknown) => {
        const item = value as { id?: unknown; name?: unknown }
        return (
            !!item &&
            Number.isSafeInteger(item.id) &&
            Number(item.id) > 0 &&
            typeof item.name === 'string' &&
            item.name.length > 0
        )
    }
    if (
        !data ||
        data.model?.id !== modelId ||
        typeof data.model.name !== 'string' ||
        !Number.isSafeInteger(data.tenant_id) ||
        data.tenant_id < 1 ||
        !Array.isArray(data.items) ||
        data.items.length > query.limit ||
        typeof data.has_more !== 'boolean' ||
        data.has_more !== Boolean(data.next_cursor) ||
        data.items.some(
            (row) =>
                !Number.isSafeInteger(row.user_id) ||
                row.user_id < 1 ||
                typeof row.user_name !== 'string' ||
                !Number.isSafeInteger(row.direct_version) ||
                row.direct_version < 0 ||
                typeof row.direct_enabled !== 'boolean' ||
                !Number.isSafeInteger(row.direct_monthly_token_limit) ||
                row.direct_monthly_token_limit < 0 ||
                (row.direct_pending_operation_id !== null &&
                    typeof row.direct_pending_operation_id !== 'string') ||
                !Array.isArray(row.departments) ||
                row.departments.some(
                    (department) =>
                        !validIdName(department) ||
                        typeof department.is_primary !== 'boolean',
                ) ||
                !Array.isArray(row.roles) ||
                row.roles.some((role) => !validIdName(role)) ||
                typeof row.authorized !== 'boolean' ||
                !Number.isSafeInteger(row.monthly_token_limit) ||
                row.monthly_token_limit < 0 ||
                !Array.isArray(row.sources) ||
                row.sources.some(
                    (source) =>
                        !['DEPARTMENT', 'ROLE', 'USER'].includes(
                            source.subject_type,
                        ) ||
                        !Number.isSafeInteger(source.subject_id) ||
                        source.subject_id < 1 ||
                        typeof source.name !== 'string' ||
                        !Number.isSafeInteger(source.monthly_token_limit) ||
                        source.monthly_token_limit < 0 ||
                        typeof source.inherited !== 'boolean' ||
                        typeof source.winning !== 'boolean',
                ) ||
                row.authorized !==
                    (Boolean(row.sources.length) &&
                        row.monthly_token_limit > 0) ||
                row.monthly_token_limit !==
                    Math.max(
                        0,
                        ...row.sources.map(
                            (source) => source.monthly_token_limit,
                        ),
                    ) ||
                row.sources.some(
                    (source) =>
                        source.winning !==
                        (source.monthly_token_limit ===
                            row.monthly_token_limit),
                ) ||
                ![null, 'DIRECT', 'DESCENDANT'].includes(
                    row.department_match,
                ),
        )
    )
        throw malformed()
    return data
}

function validSubjectPolicy(row: DshSubjectPolicy): boolean {
    return (
        !!row &&
        ['DEPARTMENT', 'ROLE'].includes(row.subject_type) &&
        Number.isSafeInteger(row.subject_id) &&
        row.subject_id > 0 &&
        typeof row.name === 'string' &&
        row.name.length > 0 &&
        Number.isSafeInteger(row.version) &&
        row.version >= 0 &&
        typeof row.enabled === 'boolean' &&
        Number.isSafeInteger(row.monthly_token_limit) &&
        row.monthly_token_limit >= 0
    )
}

export async function getDshModelSubjects(
    modelId: number,
    signal?: AbortSignal,
): Promise<DshSubjectPolicyInventory> {
    const data: DshSubjectPolicyInventory = await request.get(
        `${admin}/models/${modelId}/subjects`,
        { signal },
    )
    if (
        !data ||
        data.model_id !== modelId ||
        !Number.isSafeInteger(data.tenant_id) ||
        data.tenant_id < 1 ||
        !Array.isArray(data.departments) ||
        !Array.isArray(data.roles) ||
        data.departments.some(
            (row) =>
                !validSubjectPolicy(row) ||
                row.subject_type !== 'DEPARTMENT' ||
                !Number.isSafeInteger(row.depth) ||
                row.depth < 0 ||
                (row.parent_id !== null &&
                    (!Number.isSafeInteger(row.parent_id) ||
                        row.parent_id < 1)),
        ) ||
        data.roles.some(
            (row) =>
                !validSubjectPolicy(row) ||
                row.subject_type !== 'ROLE' ||
                !['global', 'tenant'].includes(row.role_type) ||
                (row.department_id !== null &&
                    (!Number.isSafeInteger(row.department_id) ||
                        row.department_id < 1)),
        )
    )
        throw malformed()
    return data
}

export async function saveDshSubjectPolicy(
    modelId: number,
    subjectType: DshSubjectType,
    subjectId: number,
    tenantId: number,
    body: DshSubjectPolicyInput,
): Promise<DshSubjectPolicy> {
    if (
        !['DEPARTMENT', 'ROLE'].includes(subjectType) ||
        !Number.isSafeInteger(subjectId) ||
        subjectId < 1 ||
        !Number.isSafeInteger(tenantId) ||
        tenantId < 1 ||
        !Number.isSafeInteger(body.expected_version) ||
        body.expected_version < 0 ||
        typeof body.enabled !== 'boolean' ||
        !Number.isSafeInteger(body.monthly_token_limit) ||
        body.monthly_token_limit < 0
    )
        throw malformed()
    const config = {
        params: { tenant_id: tenantId },
        preserveError: true,
    }
    const data: DshSubjectPolicy = await request.put(
        `${admin}/models/${modelId}/subjects/${subjectType}/${subjectId}/policy`,
        body,
        config,
    )
    if (
        !validSubjectPolicy(data) ||
        data.subject_type !== subjectType ||
        data.subject_id !== subjectId
    )
        throw malformed()
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
            {
                params: { tenant_id: tenantId, cursor, limit: 20 },
                signal,
            },
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

function validUsageMetrics(value: DshUsageMetrics): boolean {
    if (!value || typeof value !== 'object') return false
    const counts = [
        value.message_count,
        value.qa_count,
        value.failed_count,
        value.cancelled_count,
        value.running_count,
        value.usage_unknown_count,
        value.recorded_usage_count,
        value.missing_usage_count,
    ]
    if (counts.some((count) => !Number.isSafeInteger(count) || count < 0))
        return false
    if (
        value.qa_count +
            value.failed_count +
            value.cancelled_count +
            value.running_count +
            value.usage_unknown_count !==
            value.message_count ||
        value.recorded_usage_count + value.missing_usage_count !==
            value.message_count
    )
        return false
    const tokens = [value.input_tokens, value.output_tokens, value.total_tokens]
    if (value.message_count > 0 && value.recorded_usage_count === 0)
        return tokens.every((amount) => amount === null)
    if (
        tokens.some(
            (amount) => !Number.isSafeInteger(amount) || Number(amount) < 0,
        )
    )
        return false
    return value.total_tokens === value.input_tokens! + value.output_tokens!
}

export async function getDshUsageTimeSummary(
    userId: string,
    range: { startAt: string; endAt: string; tenantId?: string; granularity?: 'hour' | 'day' },
    signal?: AbortSignal,
): Promise<DshUsageTimeSummary> {
    const data: DshUsageTimeSummary = await request.get(
        `${admin}/users/${encodeURIComponent(userId)}/usage-summary`,
        {
            params: {
                start_at: range.startAt,
                end_at: range.endAt,
                tenant_id: range.tenantId,
                ...(range.granularity ? { granularity: range.granularity } : {}),
            },
            signal,
        },
    )
    return validateUsageTimeSummary(data, range)
}

function validateUsageTimeSummary(data: DshUsageTimeSummary, range: { startAt: string; endAt: string; granularity?: 'hour' | 'day' }): DshUsageTimeSummary {
    if (range.granularity && data?.granularity !== range.granularity) throw malformed()
    const start = Date.parse(data?.start_at ?? '')
    const end = Date.parse(data?.end_at ?? '')
    const expectedStart = Date.parse(range.startAt)
    const expectedEnd = Date.parse(range.endAt)
    const maxPoints = data?.granularity === 'hour' ? 169 : 367
    const step = data?.granularity === 'hour' ? 3600000 : 86400000
    const points = Array.isArray(data?.points) ? data.points : []
    const pointsAreContinuous = points.every((point, index) => {
        const pointStart = Date.parse(point.start_at)
        const pointEnd = Date.parse(point.end_at)
        const previousEnd =
            index === 0 ? start : Date.parse(points[index - 1].end_at)
        return (
            validUsageMetrics(point) &&
            Number.isFinite(pointStart) &&
            Number.isFinite(pointEnd) &&
            pointStart === previousEnd &&
            pointEnd > pointStart &&
            pointEnd === Math.min(end, (Math.floor((pointStart + 8 * 3600000) / step) + 1) * step - 8 * 3600000)
        )
    })
    const metricKeys = [
        'message_count',
        'qa_count',
        'failed_count',
        'cancelled_count',
        'running_count',
        'usage_unknown_count',
        'recorded_usage_count',
        'missing_usage_count',
    ] as const
    const totalsMatchPoints =
        !!data?.totals &&
        metricKeys.every(
            (key) =>
                points.reduce((total, point) => total + point[key], 0) ===
                data.totals[key],
        ) &&
        (data.totals.total_tokens === null ||
            ['input_tokens', 'output_tokens', 'total_tokens'].every(
                (key) =>
                    points.reduce(
                        (total, point) =>
                            total +
                            ((point[key as keyof typeof point] as
                                number | null) ?? 0),
                        0,
                    ) === data.totals[key as keyof typeof data.totals],
            ))
    if (
        !data ||
        data.timezone !== 'Asia/Shanghai' ||
        !['hour', 'day'].includes(data.granularity) ||
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        start !== expectedStart ||
        end !== expectedEnd ||
        !validUsageMetrics(data.totals) ||
        points.length === 0 ||
        points.length > maxPoints ||
        !pointsAreContinuous ||
        Date.parse(points.at(-1)?.end_at ?? '') !== end ||
        !totalsMatchPoints
    )
        throw malformed()
    return data
}

export async function getDshUsageOverview(
    query: {
        startAt: string
        endAt: string
        cursor?: string
        limit: number
        keyword?: string
        departmentId?: number
        tenantId?: string
        includeSummary?: boolean
        granularity?: 'hour' | 'day'
    },
    signal?: AbortSignal,
): Promise<DshUsageOverviewPage> {
    const data: DshUsageOverviewPage = await request.get(
        `${admin}/usage-overview`,
        {
            params: {
                start_at: query.startAt,
                end_at: query.endAt,
                cursor: query.cursor,
                limit: query.limit,
                keyword: query.keyword,
                department_id: query.departmentId,
                tenant_id: query.tenantId,
                include_summary: query.includeSummary,
                ...(query.granularity ? { granularity: query.granularity } : {}),
            },
            signal,
        },
    )
    if (
        !data ||
        data.timezone !== 'Asia/Shanghai' ||
        Date.parse(data.start_at) !== Date.parse(query.startAt) ||
        Date.parse(data.end_at) !== Date.parse(query.endAt) ||
        data.department_id !== (query.departmentId ?? null) ||
        !Number.isSafeInteger(data.tenant_id) ||
        data.tenant_id < 1 ||
        !validUsageMetrics(data.totals) ||
        !Array.isArray(data.items) ||
        data.items.length > query.limit ||
        typeof data.has_more !== 'boolean' ||
        data.has_more !== Boolean(data.next_cursor) ||
        data.items.some(
            (item) =>
                !Number.isSafeInteger(item.user_id) ||
                item.user_id < 1 ||
                typeof item.user_name !== 'string' ||
                !item.user_name ||
                (item.department_id !== null &&
                    (!Number.isSafeInteger(item.department_id) ||
                        item.department_id < 1)) ||
                (item.department_name !== null &&
                    typeof item.department_name !== 'string') ||
                !validUsageMetrics(item.metrics),
        )
    )
        throw malformed()
    if (query.includeSummary) {
        if (!data.summary) throw malformed()
        validateUsageTimeSummary(data.summary, query)
        for (const key of Object.keys(data.totals) as Array<keyof DshUsageMetrics>) {
            if (data.summary.totals[key] !== data.totals[key]) throw malformed()
        }
    }
    return data
}
export async function saveDshPolicy(
    userId: string,
    modelId: number,
    tenantId: string,
    body: DshPolicyInput,
): Promise<DshOperation> {
    if (
        typeof body.enabled !== 'boolean' ||
        !Number.isSafeInteger(body.monthly_token_limit) ||
        body.monthly_token_limit < 0
    )
        throw malformed()
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

export function isDshSeatLimitReached(error: unknown): boolean {
    if (!error || typeof error !== 'object' || !('response' in error)) return false
    const response = error.response
    if (!response || typeof response !== 'object' || !('data' in response)) return false
    const data = response.data
    return (
        !!data &&
        typeof data === 'object' &&
        'status_code' in data &&
        Number(data.status_code) === 26112
    )
}

export async function getDshModelPolicy(
    userId: string,
    modelId: number,
    tenantId: string,
    signal?: AbortSignal,
): Promise<Omit<DshModelAccessUser, 'user_name'>> {
    const data: Omit<DshModelAccessUser, 'user_name'> = await request.get(
        `${admin}/users/${encodeURIComponent(userId)}/models/${modelId}/policy`,
        { params: { tenant_id: tenantId }, signal },
    )
    if (
        !data ||
        !Number.isSafeInteger(data.version) ||
        data.version < 0 ||
        typeof data.enabled !== 'boolean' ||
        !Number.isSafeInteger(data.monthly_token_limit) ||
        data.monthly_token_limit < 0
    )
        throw malformed()
    return data
}
