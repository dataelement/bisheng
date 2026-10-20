import { act, cleanup, renderHook } from '@testing-library/react'
import type { TFunction } from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useParagraphMetadata } from './useParagraphMetadata'

const api = vi.hoisted(() => ({ addMetadata: vi.fn(), getKnowledgeDetailApi: vi.fn(), getMetaFile: vi.fn(), saveUserMetadataApi: vi.fn() }))
vi.mock('@/controllers/API', () => api)
const translate = ((key: string) => key) as unknown as TFunction
const notify = vi.fn()
const file = { id: 'file-1', fullData: { id: 'file-1', file_name: 'doc.pdf' } }
function setup(canEditKb = true) {
    return renderHook(() => useParagraphMetadata({ id: 'lib-1', selectedFileId: 'file-1', currentFile: file, canEditKb, t: translate, notify }))
}
afterEach(cleanup)
beforeEach(() => { vi.clearAllMocks(); api.saveUserMetadataApi.mockResolvedValue(undefined) })

describe('paragraph metadata after extraction', () => {
    it('keeps metadata read and write operations unavailable without edit permission', async () => {
        const { result } = setup(false)
        await act(async () => { await result.current.handleMetadataClick(); await result.current.handleSaveUserMetadata() })
        expect(api.getMetaFile).not.toHaveBeenCalled()
        expect(api.saveUserMetadataApi).not.toHaveBeenCalled()
    })
    it('sorts loaded fields and preserves timestamps when saving the selected file', async () => {
        api.getMetaFile.mockResolvedValue({ user_metadata: {
            later: { field_name: 'later', field_type: 'string', field_value: 'B', updated_at: 20 },
            earlier: { field_name: 'earlier', field_type: 'string', field_value: 'A', updated_at: 10 },
        } })
        const { result } = setup()
        await act(async () => { await result.current.handleMetadataClick() })
        expect(result.current.mainMetadataList.map(field => field.name)).toEqual(['earlier', 'later'])
        act(() => result.current.handleMainMetadataValueChange('meta_earlier', 'Changed'))
        await act(async () => { await result.current.handleSaveUserMetadata() })
        expect(api.saveUserMetadataApi).toHaveBeenCalledWith('file-1', [
            { field_name: 'earlier', field_value: 'Changed', updated_at: 10 },
            { field_name: 'later', field_value: 'B', updated_at: 20 },
        ])
        expect(result.current.metadataDialog.open).toBe(false)
    })
    it('keeps the draft open when saving fails and surfaces the error', async () => {
        api.getMetaFile.mockResolvedValue({ user_metadata: {} })
        api.saveUserMetadataApi.mockRejectedValue(new Error('Network unavailable'))
        const { result } = setup()
        await act(async () => { await result.current.handleMetadataClick() })
        await act(async () => { await result.current.handleSaveUserMetadata() })
        expect(result.current.metadataDialog.open).toBe(true)
        expect(result.current.metadataError).toBe('metadialog.saveFailed')
        expect(notify).toHaveBeenCalledWith({ type: 'error', description: 'Network unavailable' })
    })
})
