import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { getAuditChatFileUrlApi } from '@/controllers/API/log'
import { showApiError } from '@/controllers/request'
import { GeneratedFileCards, pickGeneratedFiles } from './DailyGeneratedFiles'
import { MessageContent } from './DailyMessageContent'

vi.mock('@/controllers/API/log', () => ({ getAuditChatFileUrlApi: vi.fn() }))
vi.mock('@/controllers/request', () => {
    const showApiError = vi.fn()
    return {
        showApiError,
        // Same contract as the real one: rejections end at the UI boundary.
        handleUiRequest: (handler: (...args: unknown[]) => unknown) => (...args: unknown[]) => {
            void Promise.resolve().then(() => handler(...args)).catch(showApiError)
        },
    }
})

const report = { file_id: 'g1', file_name: 'report.docx', path: 'output/report.docx', source: 'code_interpreter' }
const upload = { file_id: 'u1', file_name: 'input.xlsx', object_name: 'chat/7/in.xlsx' }

afterEach(() => {
    cleanup()
    vi.clearAllMocks()
})

it('shows only the files the code interpreter produced', () => {
    expect(pickGeneratedFiles([upload, report, null])).toEqual([report])
    expect(pickGeneratedFiles(undefined)).toEqual([])
})

it('downloads a card through the audit link of that conversation', async () => {
    vi.mocked(getAuditChatFileUrlApi).mockResolvedValue({ url: '/bisheng/chat/7/ab.docx?fresh' })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<GeneratedFileCards chatId="chat-1" files={[report]} />)

    fireEvent.click(screen.getByRole('button', { name: 'report.docx' }))

    await waitFor(() => expect(click).toHaveBeenCalled())
    expect(getAuditChatFileUrlApi).toHaveBeenCalledWith('chat-1', 'g1')
    const anchor = click.mock.contexts[0] as HTMLAnchorElement
    expect(anchor.getAttribute('href')).toBe('/bisheng/chat/7/ab.docx?fresh')
    expect(anchor.download).toBe('report.docx')
})

it('surfaces a refused download instead of swallowing it', async () => {
    const refusal = new Error('not in audit scope')
    vi.mocked(getAuditChatFileUrlApi).mockRejectedValue(refusal)
    render(<GeneratedFileCards chatId="chat-1" files={[report]} />)

    fireEvent.click(screen.getByRole('button', { name: 'report.docx' }))

    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(refusal))
})

it('turns an answer link naming a generated file into a download', async () => {
    vi.mocked(getAuditChatFileUrlApi).mockResolvedValue({ url: '/bisheng/chat/7/ab.docx?fresh' })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<MessageContent text="See [the report](./output/report.docx)." chatId="chat-1" files={[report]} />)

    fireEvent.click(screen.getByRole('button', { name: 'the report' }))

    await waitFor(() => expect(getAuditChatFileUrlApi).toHaveBeenCalledWith('chat-1', 'g1'))
})

it('shows an unmatched working-directory link as text and keeps other links', () => {
    const { container } = render(
        <MessageContent
            text="[gone](output/missing.docx) and [site](https://example.com/a)"
            chatId="chat-1"
            files={[report]}
        />,
    )

    const links = container.querySelectorAll('a')
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('https://example.com/a')
    expect(screen.getByText('gone').tagName).toBe('SPAN')
})
