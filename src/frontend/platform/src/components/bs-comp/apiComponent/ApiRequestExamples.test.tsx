import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { ApiRequestExamples } from './ApiRequestExamples'

const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
vi.mock('@/utils', () => ({ copyText: copy }))
vi.mock('react-syntax-highlighter', () => ({ Prism: ({ children }: { children: ReactNode }) => <pre data-testid="example-code">{children}</pre> }))
afterEach(cleanup)
it('keeps selected example language while identity headers update and copies the visible example', async () => {
    render(<ApiRequestExamples kind="assistant" applicationId="assistant-fixture" />)
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Python API' }), { button: 0, ctrlKey: false })
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'api.openApiGuide.external_title' }), { button: 0, ctrlKey: false })
    expect(screen.getByTestId('example-code')).toHaveTextContent('X-End-User')
    expect(screen.getByTestId('example-code')).toHaveTextContent('assistant-fixture')
    expect(screen.getByRole('tab', { name: 'Python API' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'api.openApiGuide.copy_example' }))
    await waitFor(() => expect(copy).toHaveBeenCalledWith(expect.stringContaining('X-End-User')))
})
