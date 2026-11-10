import { afterEach, describe, expect, it } from 'vitest'

import { getWorkspaceClientUrl, resolveWorkspaceOrigin } from '@/utils/workspaceUrl'

const globals = globalThis as unknown as { __APP_ENV__: Record<string, string> }
const original = globals.__APP_ENV__

afterEach(() => {
    globals.__APP_ENV__ = original
})

describe('resolveWorkspaceOrigin', () => {
    it('derives the sibling dev port from the browser host', () => {
        expect(
            resolveWorkspaceOrigin({}, { protocol: 'http:', hostname: '127.0.0.1' }, true),
        ).toBe('http://127.0.0.1:4001')
        expect(
            resolveWorkspaceOrigin({}, { protocol: 'http:', hostname: '192.168.1.88' }, true),
        ).toBe('http://192.168.1.88:4001')
    })

    it('prefers an explicitly configured origin', () => {
        expect(
            resolveWorkspaceOrigin(
                { WORKSPACE_ORIGIN: 'https://work.example.com/' },
                { protocol: 'http:', hostname: '192.168.1.88' },
                true,
            ),
        ).toBe('https://work.example.com')
    })

    it('stays relative outside dev (same-origin reverse proxy)', () => {
        expect(
            resolveWorkspaceOrigin({}, { protocol: 'http:', hostname: 'localhost' }, false),
        ).toBe('')
    })
})

describe('getWorkspaceClientUrl', () => {
    it('uses a configured client origin', () => {
        globals.__APP_ENV__ = { BASE_URL: '', WORKSPACE_ORIGIN: 'http://localhost:4001' }

        expect(getWorkspaceClientUrl('/chat/flow/1?x=1', false)).toBe(
            'http://localhost:4001/workspace/chat/flow/1?x=1',
        )
    })

    it('falls back to a same-origin path when no origin is configured', () => {
        globals.__APP_ENV__ = { BASE_URL: '' }

        expect(getWorkspaceClientUrl('/', false)).toBe('/workspace/')
    })

    it('keeps a sub-path deployment prefix', () => {
        globals.__APP_ENV__ = { BASE_URL: '/custom' }

        expect(getWorkspaceClientUrl('/apps', false)).toBe('/custom/workspace/apps')
    })
})
