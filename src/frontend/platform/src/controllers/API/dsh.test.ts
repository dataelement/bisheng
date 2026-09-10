import { describe, expect, it, vi } from 'vitest'
vi.mock('@/controllers/request', () => ({
    default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}))
import request from '@/controllers/request'
import {
    getDshConfig,
    getDshPolicy,
    saveDshPolicy,
    getDshOperation,
    parseDshConfig,
    validateAuthorization,
    validatePage,
} from './dsh'

describe('DSH API contract boundaries', () => {
    it('accepts disabled and rejects partial enabled config', () => {
        expect(parseDshConfig({ enabled: false })).toEqual({ enabled: false })
        expect(() => parseDshConfig({ enabled: true })).toThrow()
        const current = { enabled: true, client_id: 'dsh-desktop', contract_version: '0.4.0' }
        expect(parseDshConfig(current)).toEqual(current)
        expect(() => parseDshConfig({ ...current, contract_version: '0.1.0' })).toThrow()
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
            enabled: true, monthly_token_limit: 100,
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
})
