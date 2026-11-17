import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import JSZip from 'jszip';
import type { TrainingDataType } from '@/controllers/API/finetuneV2';
interface Props { file: File; dataType: TrainingDataType }
type Preview = { messages: { role: string; content: string }[]; media: string[] };

// Preview only files already accepted by the server's bounded archive validation.
export async function readDatasetPreview(file: File, dataType: TrainingDataType): Promise<Preview[]> {
    let records: unknown;
    let archive: JSZip | undefined;
    if (file.name.toLowerCase().endsWith('.zip')) {
        archive = await JSZip.loadAsync(await file.arrayBuffer());
        const manifest = archive.file('train.json') || archive.file('train.jsonl') || archive.file('data.json') || archive.file('data.jsonl');
        if (!manifest) throw new Error('Missing training manifest');
        const content = (await manifest.async('string')).replace(/^\uFEFF/, '');
        records = manifest.name.endsWith('.jsonl') ? content.split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)) : JSON.parse(content);
    } else {
        const content = (await file.text()).replace(/^\uFEFF/, '');
        records = file.name.toLowerCase().endsWith('.jsonl') ? content.split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)) : JSON.parse(content);
    }
    if (!Array.isArray(records)) throw new Error('Invalid training manifest');
    const result: Preview[] = [];
    try {
        for (const row of records.slice(0, 3)) {
            const messages = Array.isArray(row.messages) ? row.messages.map((message: { role: string; content: string }) => ({ role: message.role, content: message.content }))
                : [{ role: 'user', content: `${row.instruction || ''}\n${row.input || ''}`.trim() }, { role: 'assistant', content: row.output || '' }];
            const preview: Preview = { messages, media: [] }; result.push(preview);
            const references = dataType === 'video_text' ? row.videos : row.images;
            for (const reference of (references || []).slice(0, 2)) {
                if (!archive || typeof reference !== 'string') continue;
                const member = archive.file(reference);
                if (!member) continue;
                const bytes = await member.async('uint8array');
                const extension = reference.split('.').pop()?.toLowerCase();
                const mime = dataType === 'video_text' ? extension === 'webm' ? 'video/webm' : 'video/mp4' : extension === 'png' ? 'image/png' : extension === 'webp' ? 'image/webp' : 'image/jpeg';
                preview.media.push(URL.createObjectURL(new Blob([new Uint8Array(bytes).buffer], { type: mime })));
            }
        }
        return result;
    } catch (error) { result.flatMap(row => row.media).forEach(url => URL.revokeObjectURL(url)); throw error; }
}
export function DatasetPreview({ file, dataType }: Props) {
    const { t } = useTranslation('model');
    const [samples, setSamples] = useState<Preview[]>([]);
    const [failed, setFailed] = useState(false);
    useEffect(() => {
        let active = true;
        let urls: string[] = [];
        void readDatasetPreview(file, dataType).then(rows => {
            urls = rows.flatMap(row => row.media);
            if (active) setSamples(rows); else urls.forEach(url => URL.revokeObjectURL(url));
        }).catch(() => { if (active) setFailed(true); });
        return () => { active = false; urls.forEach(url => URL.revokeObjectURL(url)); };
    }, [file, dataType]);
    return <details className="pt-2"><summary className="text-sm cursor-pointer">{t('finetune.previewSamples')}</summary>{failed && <p className="text-sm">{t('finetune.previewUnavailable')}</p>}{samples.map((sample, index) => <div key={index} className="border-t mt-2 pt-2 space-y-2">
        {sample.messages.map((message, position) => <p className="text-sm whitespace-pre-wrap break-words" key={position}><strong>{message.role}: </strong>{message.content}</p>)}
        {sample.media.map(url => dataType === 'video_text' ? <video key={url} src={url} controls preload="metadata" className="max-h-40 max-w-full" /> : <img key={url} src={url} alt={t('finetune.previewMedia')} className="max-h-40 max-w-full" />)}
    </div>)}</details>;
}
