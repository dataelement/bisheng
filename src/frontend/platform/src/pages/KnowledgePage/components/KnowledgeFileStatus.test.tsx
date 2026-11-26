import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { StatusIndicator } from './KnowledgeFileStatus'
afterEach(cleanup)

describe('knowledge file status presentation', () => {
    it('hides unsupported status codes', () => {
        const { container } = render(<StatusIndicator status={99} />)
        expect(container).toBeEmptyDOMElement()
    })
    it('preserves plain parse failures in the help action', () => {
        render(<StatusIndicator status={3} remark="Connection refused" />)
        expect(screen.getByText('parseFailed')).toBeVisible()
        expect(screen.getByRole('button', { name: 'Connection refused' })).toBeVisible()
    })
    it('explains a code-only parse failure instead of the generic operation fallback', () => {
        render(<StatusIndicator status={3} remark={JSON.stringify({ code: 10953 })} />)
        expect(screen.getByRole('button', { name: 'api_errors:10953' })).toBeVisible()
        expect(screen.queryByRole('button', { name: 'api_errors:fallback' })).toBeNull()
    })
    it('resolves structured ASR errors and keeps timeout help', () => {
        const { rerender } = render(<StatusIndicator status={3} remark={JSON.stringify({ status_code: 10954, status_message: 'api key is missing' })} />)
        expect(screen.getByRole('button', { name: 'mediaAsrApiKeyMissing' })).toBeVisible()
        rerender(<StatusIndicator status={6} />)
        expect(screen.getByRole('button', { name: 'timeoutTip' })).toBeVisible()
    })
})
