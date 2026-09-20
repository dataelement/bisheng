import { describe, expect, it, vi } from 'vitest'
vi.mock('@/controllers/request', () => ({
    default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}))
import request from '@/controllers/request'
import {
    getDshConfig,
    getDshModelSubjects,
    getDshModelUserPermissions,
    getDshPolicy,
    getDshUsageTimeSummary,
    getDshUsageOverview,
    saveDshPolicy,
    saveDshSubjectPolicy,
    getDshOperation,
    parseDshConfig,
    validateAuthorization,
    validatePage,
} from './dsh'

describe('DSH API contract boundaries', () => {
    it('accepts disabled and rejects partial enabled config', () => {
        expect(parseDshConfig({ enabled: false })).toEqual({ enabled: false })
        expect(() => parseDshConfig({ enabled: true })).toThrow()
        const current = {
            enabled: true,
            client_id: 'dsh-desktop',
            contract_version: '0.4.0',
        }
        expect(parseDshConfig(current)).toEqual(current)
        expect(() =>
            parseDshConfig({ ...current, contract_version: '0.1.0' }),
        ).toThrow()
        expect(() =>
            parseDshConfig({ status_code: 200, data: { enabled: false } }),
        ).toThrow()
    })
    it('adapts only raw config before the existing envelope interceptor', async () => {
        vi.mocked(request.get).mockResolvedValue({ enabled: false })
        await getDshConfig()
        const args = vi.mocked(request.get).mock.calls.at(-1)!
        const transforms = args[1]?.transformResponse
        expect(Array.isArray(transforms)).toBe(true)
        if (!Array.isArray(transforms)) throw new Error('Missing transform')
        const transform = transforms[0] as (raw: string) => unknown
        expect(transform('{"enabled":false}')).toEqual({
            status_code: 200,
            data: { enabled: false },
        })
    })
    it('rejects hostile callback URLs and incomplete ticket responses', () => {
        const valid = {
            identity_ticket: 'fixture',
            state: 'fixture',
            expires_in: 60,
            redirect_uri: 'http://127.0.0.1:49152/dsh/callback',
        }
        expect(validateAuthorization(valid)).toEqual(valid)
        for (const url of [
            'https://evil.example/dsh/callback',
            'http://localhost:1234/dsh/callback',
            'http://127.0.0.1:1234/dsh/callback?next=x',
            'http://user@127.0.0.1:1234/dsh/callback',
            'http://127.0.0.1/dsh/callback',
            'http://127.0.0.1:1234/x/../dsh/callback',
        ])
            expect(() =>
                validateAuthorization({ ...valid, redirect_uri: url }),
            ).toThrow()
        expect(() =>
            validateAuthorization({ ...valid, expires_in: 61 }),
        ).toThrow()
        expect(() =>
            validateAuthorization({ ...valid, identity_ticket: '' }),
        ).toThrow()
    })
    it('requires a cursor when more data is advertised', () => {
        expect(() =>
            validatePage({ items: [], has_more: true, next_cursor: null }),
        ).toThrow()
    })
    it('keeps PROCESSING and rejects an operation ID mismatch', async () => {
        vi.mocked(request.get).mockResolvedValue({
            operation_id: 'one',
            status: 'PROCESSING',
        })
        expect((await getDshOperation('one', '1')).status).toBe('PROCESSING')
        await expect(getDshOperation('two', '1')).rejects.toThrow()
    })
    it('accepts independent model configuration objects and rejects legacy or duplicate configurations', async () => {
        const policy = {
            tenant_id: 1,
            version: 1,
            available_models: [],
            available_models_source: 'live',
            last_call_source: 'persisted',
            usage: null,
            models: [
                { model_id: 7, monthly_token_limit: 100 },
                { model_id: 8, monthly_token_limit: 0 },
            ],
        }
        vi.mocked(request.get).mockResolvedValue(policy)
        expect((await getDshPolicy('2')).models).toEqual(policy.models)
        for (const models of [
            [7],
            [null],
            [{ model_id: 7, monthly_token_limit: -1 }],
            [{ model_id: 7, monthly_token_limit: 1.5 }],
            [policy.models[0], policy.models[0]],
        ]) {
            vi.mocked(request.get).mockResolvedValue({ ...policy, models })
            await expect(getDshPolicy('2')).rejects.toThrow(
                'Invalid DSH response',
            )
        }
    })
    it('sends only model-scoped quotas and preserves the caller operation ID', async () => {
        const body = {
            operation_id: 'same-operation',
            expected_version: 1,
            enabled: true,
            monthly_token_limit: 100,
        }
        await saveDshPolicy('2', 7, '1', body)
        expect(request.put).toHaveBeenCalledWith(
            '/api/v1/dsh/admin/users/2/models/7/policy',
            body,
            { params: { tenant_id: '1' }, preserveError: true },
        )
        const calls = vi.mocked(request.put).mock.calls.length
        await expect(
            saveDshPolicy('2', 7, '1', {
                ...body,
                monthly_token_limit: -1,
            }),
        ).rejects.toThrow()
        expect(request.put).toHaveBeenCalledTimes(calls)
    })
    it('validates the tenant department/role inventory and saves one versioned subject policy', async () => {
        const inventory = {
            tenant_id: 2,
            model_id: 7,
            departments: [
                {
                    subject_type: 'DEPARTMENT',
                    subject_id: 10,
                    name: 'Engineering',
                    parent_id: null,
                    depth: 0,
                    version: 0,
                    enabled: false,
                    monthly_token_limit: 0,
                },
            ],
            roles: [
                {
                    subject_type: 'ROLE',
                    subject_id: 41,
                    name: 'Product manager',
                    role_type: 'tenant',
                    department_id: null,
                    version: 1,
                    enabled: true,
                    monthly_token_limit: 500,
                },
            ],
        }
        vi.mocked(request.get).mockResolvedValue(inventory)
        await expect(getDshModelSubjects(7)).resolves.toEqual(inventory)
        vi.mocked(request.get).mockResolvedValue({
            ...inventory,
            departments: [{ ...inventory.departments[0], depth: -1 }],
        })
        await expect(getDshModelSubjects(7)).rejects.toThrow(
            'Invalid DSH response',
        )

        const body = {
            expected_version: 0,
            enabled: true,
            monthly_token_limit: 300,
        }
        vi.mocked(request.put).mockResolvedValue({
            ...inventory.departments[0],
            version: 1,
            enabled: true,
            monthly_token_limit: 300,
        })
        await saveDshSubjectPolicy(7, 'DEPARTMENT', 10, 2, body)
        expect(request.put).toHaveBeenLastCalledWith(
            '/api/v1/dsh/admin/models/7/subjects/DEPARTMENT/10/policy',
            body,
            { params: { tenant_id: 2 }, preserveError: true },
        )
    })
    it('validates effective user permission sources and sends department membership filters', async () => {
        const page = {
            tenant_id: 2,
            model: {
                id: 7,
                name: 'Bailian / qwen-max',
                is_root_shared: false,
            },
            items: [
                {
                    user_id: 1,
                    user_name: 'admin',
                    direct_version: 0,
                    direct_enabled: false,
                    direct_monthly_token_limit: 0,
                    direct_pending_operation_id: null,
                    departments: [
                        { id: 31, name: 'Temporary visitors', is_primary: true },
                    ],
                    roles: [],
                    authorized: true,
                    monthly_token_limit: 100,
                    department_match: 'DIRECT',
                    sources: [
                        {
                            subject_type: 'DEPARTMENT',
                            subject_id: 31,
                            name: 'Temporary visitors',
                            monthly_token_limit: 100,
                            inherited: false,
                            winning: true,
                        },
                    ],
                },
            ],
            next_cursor: null,
            has_more: false,
        } as const
        vi.mocked(request.get).mockResolvedValue(page)
        await expect(
            getDshModelUserPermissions(7, {
                limit: 50,
                keyword: 'admin',
                department_id: 31,
                membership: 'DIRECT',
            }),
        ).resolves.toEqual(page)
        expect(request.get).toHaveBeenLastCalledWith(
            '/api/v1/dsh/admin/models/7/user-permissions',
            {
                params: {
                    limit: 50,
                    keyword: 'admin',
                    department_id: 31,
                    membership: 'DIRECT',
                },
                signal: undefined,
            },
        )
        vi.mocked(request.get).mockResolvedValue({
            ...page,
            items: [
                {
                    ...page.items[0],
                    monthly_token_limit: 99,
                },
            ],
        })
        await expect(
            getDshModelUserPermissions(7, { limit: 50 }),
        ).rejects.toThrow('Invalid DSH response')
    })
    it('accepts a complete time-range usage summary and rejects fabricated token totals', async () => {
        const metrics = {
            message_count: 2,
            qa_count: 1,
            failed_count: 1,
            cancelled_count: 0,
            running_count: 0,
            usage_unknown_count: 0,
            recorded_usage_count: 2,
            missing_usage_count: 0,
            input_tokens: 10,
            output_tokens: 5,
            total_tokens: 15,
        }
        const summary = {
            start_at: '2026-09-01T00:00:00+08:00',
            end_at: '2026-09-08T00:00:00+08:00',
            timezone: 'Asia/Shanghai',
            granularity: 'day',
            totals: metrics,
            points: Array.from({ length: 7 }, (_, index) => ({
                ...Object.fromEntries(Object.entries(metrics).map(([key, value]) => [key, index === 0 ? value : 0])),
                start_at: `2026-09-0${index + 1}T00:00:00+08:00`,
                end_at: `2026-09-0${index + 2}T00:00:00+08:00`,
            })),
        } as const
        vi.mocked(request.get).mockResolvedValue(summary)
        await expect(
            getDshUsageTimeSummary('20', {
                startAt: summary.start_at,
                endAt: summary.end_at,
                tenantId: '2',
            }),
        ).resolves.toEqual(summary)
        expect(request.get).toHaveBeenLastCalledWith(
            '/api/v1/dsh/admin/users/20/usage-summary',
            expect.objectContaining({
                params: {
                    start_at: summary.start_at,
                    end_at: summary.end_at,
                    tenant_id: '2',
                },
            }),
        )

        const overview = {
            tenant_id: 2,
            department_id: 31,
            start_at: summary.start_at,
            end_at: summary.end_at,
            timezone: summary.timezone,
            totals: metrics,
            summary,
            items: [],
            has_more: false,
            next_cursor: null,
        }
        const query = {
            startAt: summary.start_at,
            endAt: summary.end_at,
            departmentId: 31,
            limit: 10,
            includeSummary: true,
        }
        vi.mocked(request.get).mockResolvedValue(overview)
        await expect(getDshUsageOverview(query)).resolves.toEqual(overview)
        await expect(getDshUsageOverview({ ...query, granularity: 'hour' })).rejects.toThrow('Invalid DSH response')
        await getDshUsageOverview(query)
        expect(request.get).toHaveBeenLastCalledWith(
            '/api/v1/dsh/admin/usage-overview',
            expect.objectContaining({ params: expect.objectContaining({ include_summary: true }) }),
        )
        vi.mocked(request.get).mockResolvedValue({ ...overview, summary: null })
        await expect(getDshUsageOverview(query)).rejects.toThrow('Invalid DSH response')
        await expect(getDshUsageOverview({ ...query, includeSummary: false })).resolves.toEqual({
            ...overview,
            summary: null,
        })
        vi.mocked(request.get).mockResolvedValue({
            ...overview,
            totals: { ...metrics, input_tokens: 11, total_tokens: 16 },
        })
        await expect(getDshUsageOverview(query)).rejects.toThrow('Invalid DSH response')
        vi.mocked(request.get).mockResolvedValue({
            ...summary,
            totals: { ...metrics, total_tokens: 14 },
        })
        await expect(
            getDshUsageTimeSummary('20', {
                startAt: summary.start_at,
                endAt: summary.end_at,
            }),
        ).rejects.toThrow('Invalid DSH response')
    })
    it('accepts all 168 real hourly buckets and rejects a week compressed into one bucket', async () => {
        const zero = { message_count: 0, qa_count: 0, failed_count: 0, cancelled_count: 0, running_count: 0, usage_unknown_count: 0, recorded_usage_count: 0, missing_usage_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0 }
        const start = Date.parse('2026-09-01T00:00:00+08:00')
        const end = start + 7 * 86400000
        const summary = {
            start_at: new Date(start).toISOString(), end_at: new Date(end).toISOString(),
            timezone: 'Asia/Shanghai', granularity: 'hour', totals: zero,
            points: Array.from({ length: 168 }, (_, hour) => ({
                ...zero, start_at: new Date(start + hour * 3600000).toISOString(),
                end_at: new Date(start + (hour + 1) * 3600000).toISOString(),
            })),
        }
        const query = { startAt: summary.start_at, endAt: summary.end_at, granularity: 'hour' as const }
        vi.mocked(request.get).mockResolvedValue(summary)
        await expect(getDshUsageTimeSummary('20', query)).resolves.toEqual(summary)
        expect(request.get).toHaveBeenLastCalledWith('/api/v1/dsh/admin/users/20/usage-summary', expect.objectContaining({ params: expect.objectContaining({ granularity: 'hour' }) }))
        await expect(getDshUsageTimeSummary('20', { ...query, granularity: 'day' })).rejects.toThrow('Invalid DSH response')
        vi.mocked(request.get).mockResolvedValue({ ...summary, points: [{ ...zero, start_at: summary.start_at, end_at: summary.end_at }] })
        await expect(getDshUsageTimeSummary('20', query)).rejects.toThrow('Invalid DSH response')
    })
})
