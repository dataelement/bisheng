import { LoadingIcon } from '@/components/bs-icons/loading'
import JSZip from 'jszip'
import * as XLSX from 'xlsx'
import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from 'pdfjs-dist/types/src/display/api'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
    source: { kind: 'pdf' | 'text' | 'image' | 'sheet' | 'docx' | 'audio' | 'video'; url: string }
    onError: () => void
}

declare const __APP_ENV__: { BASE_URL: string }
const TIMEOUT = 30000

function PdfPage({ doc, onError }: { doc: PDFDocumentProxy; onError: () => void }) {
    const { t } = useTranslation()
    const [number, setNumber] = useState(1)
    const canvas = useRef<HTMLCanvasElement>(null)
    useEffect(() => {
        let active = true
        let render: RenderTask | undefined
        const timer = window.setTimeout(() => { if (active) onError() }, TIMEOUT)
        void (async () => {
            const page = await doc.getPage(number)
            if (!active) return
            const el = canvas.current!
            const size = page.getViewport({ scale: 1 })
            const viewport = page.getViewport({ scale: Math.min(2, 2000 / Math.max(size.width, size.height)) })
            el.width = Math.ceil(viewport.width)
            el.height = Math.ceil(viewport.height)
            render = page.render({ canvasContext: el.getContext('2d')!, viewport })
            await render.promise
        })().catch(() => { if (active) onError() }).finally(() => window.clearTimeout(timer))
        return () => { active = false; window.clearTimeout(timer); render?.cancel() }
    }, [doc, number, onError])
    return <><div className="flex justify-center gap-3 p-2">
        <button type="button" disabled={number === 1} onClick={() => setNumber(number - 1)}>{t('previousPage')}</button>
        <span>{number} / {doc.numPages}</span>
        <button type="button" disabled={number === doc.numPages} onClick={() => setNumber(number + 1)}>{t('nextPage')}</button>
    </div><canvas key={number} ref={canvas} className="mx-auto h-auto max-w-full" /></>
}

export async function readDocx(bytes: ArrayBuffer) {
    const xml = await (await JSZip.loadAsync(bytes)).file('word/document.xml')?.async('string')
    if (!xml) throw new Error('Missing DOCX body')
    const document = new DOMParser().parseFromString(xml, 'application/xml')
    if (document.querySelector('parsererror') || document.documentElement.localName !== 'document') throw new Error('Invalid DOCX')
    const namespace = document.documentElement.namespaceURI
    return Array.from(document.getElementsByTagNameNS(namespace, 'p'), p =>
        Array.from(p.getElementsByTagNameNS(namespace, '*'), node =>
            node.localName === 't' ? node.textContent : node.localName === 'tab' ? '\t' : node.localName === 'br' ? '\n' : '').join('')).join('\n')
}

export async function readSheet(bytes: ArrayBuffer) {
    const lib = XLSX
    const workbook = lib.read(bytes, { type: 'array', cellHTML: false, codepage: 65001 })
    if (!workbook.SheetNames.length) throw new Error('Empty workbook')
    let cells = 0
    for (const name of workbook.SheetNames) {
        const ref = workbook.Sheets[name]['!ref']
        if (!ref) continue
        const { s, e } = lib.utils.decode_range(ref)
        cells += (e.r - s.r + 1) * (e.c - s.c + 1)
        if (cells > 50000) throw new Error('Workbook too large for inline preview')
    }
    return workbook.SheetNames.map(name => ({ name, rows: lib.utils.sheet_to_json<string[]>(workbook.Sheets[name], { header: 1, raw: false, defval: '' }) }))
}

export function openPdf(lib: typeof import('pdfjs-dist'), data: ArrayBuffer, base: string) {
    return lib.getDocument({ data, cMapUrl: `${base}/cmaps/`, cMapPacked: true, isEvalSupported: false })
}

function Preview({ source: { kind, url }, onError }: Props) {
    const { t } = useTranslation('knowledge')
    const [body, setBody] = useState<ReactNode>(null)
    const errorRef = useRef(onError)
    useEffect(() => { errorRef.current = onError }, [onError])
    useEffect(() => {
        const controller = new AbortController()
        const { signal } = controller
        const handleError = () => { if (!signal.aborted) { controller.abort(); errorRef.current() } }
        const timer = window.setTimeout(handleError, TIMEOUT)
        const handleReady = () => window.clearTimeout(timer)
        let pdf: PDFDocumentLoadingTask | undefined
        let objectUrl: string | undefined
        void (async () => {
            const response = await fetch(url, { signal, redirect: 'error', credentials: 'same-origin' })
            if (!response.ok) throw new Error('Preview unavailable')
            let content: ReactNode
            if (kind === 'image' || kind === 'audio' || kind === 'video') {
                const blob = await response.blob()
                if (signal.aborted) return
                objectUrl = URL.createObjectURL(blob)
                const Media = kind === 'video' ? 'video' : 'audio'
                content = kind === 'image' ? <img src={objectUrl} alt="" className="mx-auto max-w-full" onLoad={handleReady} onError={handleError} />
                    : <Media controls controlsList="nodownload" preload="metadata" className="mx-auto max-w-full" src={objectUrl} onLoadedMetadata={handleReady} onError={handleError} />
            } else if (kind === 'pdf') {
                const data = await response.arrayBuffer()
                if (signal.aborted) return
                pdfjs.GlobalWorkerOptions.workerSrc = `${__APP_ENV__.BASE_URL}/pdf.worker.min.js`
                pdf = openPdf(pdfjs, data, __APP_ENV__.BASE_URL)
                const doc = await pdf.promise
                content = <PdfPage doc={doc} onError={handleError} />
                handleReady()
            } else if (kind === 'sheet') {
                const bytes = await response.arrayBuffer()
                if (signal.aborted) return
                const sheets = await readSheet(bytes)
                content = sheets.map(({ name, rows }) => <section key={name}><h3>{name}</h3><table className="border-collapse text-sm"><tbody>
                    {rows.map((row, i) =>
                        <tr key={i}>{row.map((cell, j) => <td key={j} className="border px-2 py-1">{cell}</td>)}</tr>)}
                </tbody></table></section>)
                handleReady()
            } else {
                const text = kind === 'docx' ? await readDocx(await response.arrayBuffer()) : await response.text()
                content = <pre className="whitespace-pre-wrap break-words p-3">{text || t('fileContentEmpty')}</pre>
                handleReady()
            }
            if (!signal.aborted) setBody(content)
        })().catch(handleError)
        return () => { controller.abort(); handleReady(); if (objectUrl) URL.revokeObjectURL(objectUrl); void pdf?.destroy() }
    }, [kind, url, t])
    return <div className="h-full overflow-auto">{body ?? <LoadingIcon />}</div>
}

export default function AbnormalPreviewBody(props: Props) {
    return <Preview key={`${props.source.kind}:${props.source.url}`} {...props} />
}
