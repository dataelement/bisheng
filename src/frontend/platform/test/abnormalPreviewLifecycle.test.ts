import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import JSZip from 'jszip'
import * as xlsx from 'xlsx'
import { openPdf, readDocx, readSheet } from '../src/pages/LogPage/abnormalUpload/AbnormalPreviewBody'
import { loadAbnormalPreview } from '../src/pages/LogPage/abnormalUpload/AbnormalPreviewDialog'
import { getAbnormalFilePreview } from '../src/controllers/API/abnormalUpload'

vi.mock('../src/controllers/API/abnormalUpload', () => ({ getAbnormalFilePreview: vi.fn() }))
beforeEach(() => vi.stubGlobal('__APP_ENV__', { BASE_URL: '/platform' }))
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks() })

function docx(xml?: string) {
    const zip = new JSZip()
    if (xml) zip.file('word/document.xml', xml)
    return zip.generateAsync({ type: 'arraybuffer' })
}
it('extracts actual DOCX paragraphs, escapes and line breaks without rendering HTML', async () => {
    const bytes = await docx('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>一&lt;b&gt;</w:t><w:tab/><w:t>二</w:t><w:br/><w:t>三</w:t></w:r></w:p><w:p><w:r><w:t>末段</w:t></w:r></w:p></w:body></w:document>')
    expect(await readDocx(bytes)).toBe('一<b>\t二\n三\n末段')
})
it('rejects missing or malformed DOCX bodies', async () => {
    await expect(readDocx(await docx())).rejects.toThrow('Missing DOCX body')
    await expect(readDocx(await docx('<document>'))).rejects.toThrow('Invalid DOCX')
})
it('reads real binary XLSX sheets and formatted cell values', async () => {
    const book = xlsx.utils.book_new()
    xlsx.utils.book_append_sheet(book, xlsx.utils.aoa_to_sheet([['文件', 19]]), '一')
    xlsx.utils.book_append_sheet(book, xlsx.utils.aoa_to_sheet([['末页']]), '二')
    expect(await readSheet(xlsx.write(book, { bookType: 'xlsx', type: 'array' }))).toEqual([{ name: '一', rows: [['文件', '19']] }, { name: '二', rows: [['末页']] }])
})
it('rejects a sparse but large valid sheet before expanding its rectangle', async () => {
    const book = xlsx.utils.book_new()
    xlsx.utils.book_append_sheet(book, { A1: { t: 's', v: 'first' }, Z5000: { t: 's', v: 'last' }, '!ref': 'A1:Z5000' }, 'sparse')
    await expect(readSheet(xlsx.write(book, { type: 'array', bookType: 'xlsx' }))).rejects.toThrow('too large')
})
it('decodes Chinese CSV cells without a BOM or URL suffix', async () => {
    const bytes = new TextEncoder().encode('文件,数量\r\n甲,5').buffer
    expect((await readSheet(bytes))[0].rows).toEqual([['文件', '数量'], ['甲', '5']])
})

it('opens a real PDF and returns its actual page text; rejects invalid PDF data', async () => {
    const lib = await import('pdfjs-dist')
    const stream = 'BT /F1 12 Tf 12 34 Td (AuditMarker) Tj ET'
    const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>', `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    let file = '%PDF-1.4\n'
    const offsets = objects.map((object, i) => { const start = file.length; file += `${i + 1} 0 obj\n${object}\nendobj\n`; return start })
    const xref = file.length
    file += `xref\n0 6\n0000000000 65535 f \n${offsets.map(o => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
    const task = openPdf(lib, new TextEncoder().encode(file).buffer, '')
    try {
        const document = await task.promise
        expect(document.numPages).toBe(1)
        const text = await (await document.getPage(1)).getTextContent()
        expect(text.items).toContainEqual(expect.objectContaining({ str: 'AuditMarker' }))
    } finally { await task.destroy() }
    const invalid = openPdf(lib, new TextEncoder().encode('not a PDF').buffer, '')
    try { await expect(invalid.promise).rejects.toMatchObject({ name: 'InvalidPDFException' }) } finally { await invalid.destroy() }
})

const row = (file_id: number) => ({ knowledge_id: 9, file_id, file_name: 'same.pdf' })
it.each(['success', 'error'])('ignores late %s after switching from A to B, including closing B', async result => {
    const callback = vi.fn(), error = vi.fn()
    let finish!: () => void
    vi.mocked(getAbnormalFilePreview).mockImplementationOnce(() => new Promise((resolve, reject) => {
        finish = () => result === 'success' ? resolve({ original_url: '/bisheng/a.pdf' }) : reject(new Error('late failure'))
    })).mockResolvedValueOnce({ original_url: '/bisheng/b.pdf' })
    const a = new AbortController()
    const old = loadAbnormalPreview(row(1), a.signal, callback, error)
    a.abort()
    const b = new AbortController()
    await loadAbnormalPreview(row(2), b.signal, callback, error)
    expect(callback.mock.calls).toEqual([[{ kind: 'pdf', url: '/platform/bisheng/b.pdf' }]])
    b.abort(); finish(); await old
    expect(callback).toHaveBeenCalledTimes(1)
    expect(error).not.toHaveBeenCalled()
})
it.each([['missing', 'com_sop_preview_failed'], ['denied', 'errors.403'], ['network', 'com_sop_preview_failed']])('reports active %s without displaying content', async (mode, key) => {
    const callback = vi.fn(), error = vi.fn()
    if (mode === 'missing') vi.mocked(getAbnormalFilePreview).mockResolvedValueOnce({})
    else vi.mocked(getAbnormalFilePreview).mockRejectedValueOnce(mode === 'denied' ? { status_code: 403 } : null)
    await loadAbnormalPreview(row(1), new AbortController().signal, callback, error)
    expect(callback).not.toHaveBeenCalled()
    expect(error.mock.calls).toEqual([[key]])
})
